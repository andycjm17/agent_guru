#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
server.py — 本地 UI（纯 stdlib http.server，无 npm/无构建）

单页四块：
  1. 省时 punchline banner（savings.summary）
  2. Workflow Map 表（行可点 → 抽屉：步骤分桶 / 下一步 / 「蒸馏成 Skill」）
  3. Skills（行可点 → 抽屉：SKILL.md 编辑器 + 自主度 + 「应用到生产」备份后写回平台）
  4. ⚙ 设置（观察源 / 通知渠道 / skill 落地目标 / Slack webhook，写回 config.local.json）

API:
  GET  /                       → ui/index.html
  GET  /api/map                → map.json
  GET  /api/savings?days=7
  GET  /api/skills?platform=   → {skills, levels, platforms, target}
  GET  /api/skill?platform=&name=   → {name, platform, content, path}
  POST /api/skill              → {platform, name, content, autonomy?} 备份+写回生产
  POST /api/skill/promote      → {workflow} LLM 把工作流草拟成 SKILL.md（不落地，回草稿）
  GET  /api/platforms          → 观察源/通知渠道/skill 落地目标 当前状态
  POST /api/platforms          → {sources, sinks, skill_target, slack_webhook} 写回 config
  POST /api/skills             → {name, autonomy} 仅改自主度（向后兼容旧前端）

用法:
  python -m distiller.server [--port 8787] [--no-open]
"""
from __future__ import annotations

import sys
import json
import argparse
import webbrowser
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

from . import config as C
from . import savings as S
from . import agents as A
from . import sinks as K

DEFAULT_PORT = C.UI_PORT

_CFG_LOCK = threading.Lock()   # 串行化 skills_config / config.local 的读改写


# ---------- skills（经 agents 注册表，跨平台）----------
def _autonomy_key(platform: str, name: str) -> str:
    # claude_code 保留裸 name（向后兼容既有 skills_config.json），其余平台命名空间隔离
    return name if platform == "claude_code" else f"{platform}:{name}"


def scan_skills(platform_key: str) -> list:
    p = A.by_key(platform_key) or A.skill_target_platform()
    cfg = C.load_json(C.SKILLS_CONFIG, default={}) or {}
    out = []
    try:
        skills = p.list_skills()
    except Exception as e:
        C.log(f"server: list_skills[{p.key}] 异常: {e!r}")
        skills = []
    for s in skills:
        ak = _autonomy_key(p.key, s["name"])
        out.append({
            **s,
            "platform": p.key,
            "autonomy": (cfg.get(ak) or {}).get("autonomy", "suggest"),
        })
    return out


def set_skill_autonomy(platform: str, name: str, autonomy: str) -> bool:
    if autonomy not in C.AUTONOMY_LEVELS:
        return False
    with _CFG_LOCK:
        cfg = C.load_json(C.SKILLS_CONFIG, default={}) or {}
        ak = _autonomy_key(platform, name)
        cfg.setdefault(ak, {})["autonomy"] = autonomy
        cfg[ak]["updated_at"] = C.now_utc().isoformat()
        C.save_json(C.SKILLS_CONFIG, cfg)
    C.log(f"server: 自主度 {ak} → {autonomy}")
    return True


def platforms_payload() -> dict:
    """供 UI 设置面板：每个观察源/通知渠道的可用/启用状态 + skill 落地目标。"""
    enabled_src = {p.key for p in A.enabled_platforms()}
    enabled_snk = {s.key for s in K.enabled_sinks()}
    target = A.skill_target_platform()
    sources = []
    for p in A.all_platforms():
        try:
            avail = p.available()
        except Exception:
            avail = False
        sources.append({"key": p.key, "label": p.label, "available": avail,
                        "enabled": p.key in enabled_src,
                        "skill_kind": p.skill_kind, "skill_note": getattr(p, "skill_note", "")})
    sinks_info = []
    for s in K.all_sinks():
        try:
            avail = s.available()
        except Exception:
            avail = False
        sinks_info.append({"key": s.key, "label": s.label, "available": avail,
                           "enabled": s.key in enabled_snk})
    return {
        "sources": sources,
        "sinks": sinks_info,
        "skill_target": target.key,
        "slack_webhook_set": bool(C.live_cfg("slack_webhook", "")),
        "sources_explicit": isinstance(C.live_cfg("sources", None), list),
        "sinks_explicit": isinstance(C.live_cfg("sinks", None), list),
    }


# ---------- 工作流 → Skill 草稿（LLM 起草，不落地）----------
def _promote_prompt(wf: dict, platform) -> str:
    steps = "\n".join(
        f"  {i}. [{C.BUCKET_ZH.get(s.get('bucket'), s.get('bucket',''))}] "
        f"{s.get('desc','')} → {s.get('next_action','')}"
        for i, s in enumerate(wf.get("steps", []) or [], 1)
    )
    if platform.key == "cursor":
        fmt = ("输出一个 Cursor Project Rule（.mdc）：以 YAML frontmatter 开头，含 "
               "description（一句触发条件）、globs（相关文件 glob，可空字符串）、alwaysApply: false，"
               "frontmatter 后是 markdown 正文。")
    elif platform.key == "codex":
        fmt = ("输出一个 Codex 自定义 prompt（markdown）：可选 YAML frontmatter（description、argument-hint），"
               "正文用第二人称祈使写清这个可复用流程怎么做。")
    else:
        fmt = ("输出一个 Claude Code SKILL.md：以 YAML frontmatter 开头（name: 用英文 kebab-case；"
               "description: 一句『何时该用本 skill』的触发描述），frontmatter 后是 markdown 正文，"
               "分『何时使用 / 步骤 / 注意』。")
    return f"""你在把一个被观察到的复发工作流蒸馏成一个可复用的 Agent Skill。{fmt}

严格只输出 JSON（不要 markdown 代码块、不要解释）：
{{"name": "<英文 kebab-case 短名>", "content": "<完整的 skill 文件全文，含 frontmatter>"}}

工作流名：{wf.get('name','')}
摘要：{wf.get('summary','')}
建议下一步：{wf.get('recommendation','')}
步骤：
{steps or '  (无步骤拆解)'}

要求：content 要可直接保存即用；正文中文、技术名词英文；不编造工作流里没有的东西；结论先行、步骤清晰。"""


def promote_workflow(workflow_name: str, platform_key: str = "") -> dict:
    m = C.load_json(C.MAP_FILE, default={}) or {}
    wf = next((w for w in m.get("workflows", []) if w.get("name") == workflow_name), None)
    if not wf:
        return {"ok": False, "error": f"未找到工作流: {workflow_name!r}"}
    platform = A.by_key(platform_key) or A.skill_target_platform()
    obj = C.llm(_promote_prompt(wf, platform), timeout=300, expect_json=True)
    if not isinstance(obj, dict) or not obj.get("content"):
        return {"ok": False, "error": f"LLM[{C.active_provider()}] 起草失败或返回为空"}
    name = (obj.get("name") or A.slugify(workflow_name)).strip()
    return {"ok": True, "name": A.slugify(name), "content": obj["content"],
            "platform": platform.key, "from_workflow": workflow_name}


# ---------- HTTP ----------
class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        pass

    def _send(self, code, body, ctype="application/json; charset=utf-8"):
        if isinstance(body, (dict, list)):
            body = json.dumps(body, ensure_ascii=False)
        data = body.encode("utf-8") if isinstance(body, str) else body
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _read_body(self) -> dict:
        try:
            length = int(self.headers.get("Content-Length", "0") or 0)
        except (TypeError, ValueError):
            return {}
        if length <= 0 or length > 4_000_000:
            return {}
        try:
            return json.loads(self.rfile.read(length) or b"{}")
        except Exception:
            return {}

    def do_GET(self):
        u = urlparse(self.path)
        path = u.path
        q = parse_qs(u.query)
        if path in ("/", "/index.html"):
            html = (C.UI_DIR / "index.html")
            if html.exists():
                self._send(200, html.read_text(encoding="utf-8"), "text/html; charset=utf-8")
            else:
                self._send(404, "ui/index.html 不存在", "text/plain; charset=utf-8")
        elif path == "/api/map":
            self._send(200, C.load_json(C.MAP_FILE, default={"workflows": [], "headline": "(还没跑 distill)"}))
        elif path == "/api/savings":
            raw = (q.get("days", ["7"])[0]) or "7"
            try:
                days = int(raw)
            except (TypeError, ValueError):
                return self._send(400, {"error": f"非法 days: {raw!r}"})
            self._send(200, S.summary(min(days, 36500)))
        elif path == "/api/skills":
            pk = (q.get("platform", [""])[0]) or A.skill_target_platform().key
            self._send(200, {
                "skills": scan_skills(pk),
                "platform": pk,
                "levels": [{"value": v, "label": C.AUTONOMY_ZH[v]} for v in C.AUTONOMY_LEVELS],
                "platforms": [{"key": p.key, "label": p.label,
                               "writable": p.skills_root() is not None}
                              for p in A.all_platforms()],
                "target": A.skill_target_platform().key,
            })
        elif path == "/api/skill":
            pk = (q.get("platform", [""])[0]) or A.skill_target_platform().key
            name = (q.get("name", [""])[0])
            p = A.by_key(pk) or A.skill_target_platform()
            data = p.read_skill(name) if name else None
            if data is None:
                return self._send(404, {"ok": False, "error": "skill 不存在", "platform": pk, "name": name})
            self._send(200, {"ok": True, **data})
        elif path == "/api/platforms":
            self._send(200, platforms_payload())
        else:
            self._send(404, {"error": "not found"})

    def _origin_ok(self) -> bool:
        """CSRF 防护：浏览器跨站 fetch 必带 Origin；只放行同机来源。
        无 Origin（curl / CLI / 本工具自身的同源请求有时不带）一律放行，不影响本地使用。"""
        origin = self.headers.get("Origin", "")
        if not origin:
            return True
        try:
            host = urlparse(origin).hostname
        except Exception:
            return False
        return host in ("127.0.0.1", "localhost", "::1", "0.0.0.0")

    def do_POST(self):
        try:
            u = urlparse(self.path)
            path = u.path
            if not self._origin_ok():
                return self._send(403, {"ok": False, "error": "跨站 POST 拒绝（CSRF 防护）"})
            body = self._read_body()
            if path == "/api/skills":
                # 向后兼容：仅改自主度
                ok = set_skill_autonomy(body.get("platform", "claude_code"),
                                        body.get("name", ""), body.get("autonomy", ""))
                return self._send(200 if ok else 400, {"ok": ok})
            if path == "/api/skill":
                return self._post_skill(body)
            if path == "/api/skill/promote":
                res = promote_workflow(body.get("workflow", ""), body.get("platform", ""))
                return self._send(200 if res.get("ok") else 400, res)
            if path == "/api/platforms":
                return self._post_platforms(body)
            return self._send(404, {"error": "not found"})
        except Exception as e:
            C.log(f"server: do_POST 异常 {e!r}")
            try:
                self._send(500, {"ok": False, "error": "internal error"})
            except Exception:
                pass

    def _post_skill(self, body: dict):
        pk = body.get("platform") or A.skill_target_platform().key
        name = (body.get("name") or "").strip()
        content = body.get("content")
        if not name or not isinstance(content, str) or not content.strip():
            return self._send(400, {"ok": False, "error": "缺 name 或 content"})
        p = A.by_key(pk)
        if p is None:
            return self._send(400, {"ok": False, "error": f"未知平台 {pk!r}"})
        with _CFG_LOCK:
            res = p.install_skill(name, content)
        if not res.get("ok"):
            return self._send(400, res)
        # 自主度按「落地后 list_skills 会用的标识」keying，保证与列表/内联下拉往返一致
        cname = p.canonical_name(name)
        autonomy = body.get("autonomy")
        if autonomy in C.AUTONOMY_LEVELS:
            set_skill_autonomy(pk, cname, autonomy)
            res["autonomy"] = autonomy
        res["platform"] = pk
        res["name"] = cname
        self._send(200, res)

    def _post_platforms(self, body: dict):
        patch = {}
        if isinstance(body.get("sources"), list):
            patch["sources"] = [s for s in body["sources"] if A.by_key(s)]
        if isinstance(body.get("sinks"), list):
            patch["sinks"] = [s for s in body["sinks"] if K.by_key(s)]
        if "skill_target" in body:
            st = body.get("skill_target") or ""
            if st and not A.by_key(st):
                return self._send(400, {"ok": False, "error": f"未知 skill_target {st!r}"})
            patch["skill_target"] = st
        if "slack_webhook" in body:
            patch["slack_webhook"] = (body.get("slack_webhook") or "").strip()
        if not patch:
            return self._send(400, {"ok": False, "error": "无可更新字段"})
        with _CFG_LOCK:
            C.update_local_config(patch)
        self._send(200, {"ok": True, "saved": list(patch.keys()), "state": platforms_payload()})


def serve(port: int = DEFAULT_PORT, open_browser: bool = True):
    C.ensure_dirs()
    httpd = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    url = f"http://127.0.0.1:{port}/"
    C.log(f"server: 监听 {url}  (Ctrl-C 退出)")
    print(f"\n  workflow-distiller UI → {url}\n")
    if open_browser:
        threading.Timer(0.6, lambda: webbrowser.open(url)).start()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        C.log("server: 退出")
        httpd.shutdown()


def main(argv=None):
    argv = argv if argv is not None else sys.argv[1:]
    p = argparse.ArgumentParser(prog="distiller.server")
    p.add_argument("--port", type=int, default=DEFAULT_PORT)
    p.add_argument("--no-open", action="store_true")
    args = p.parse_args(argv)
    serve(args.port, open_browser=not args.no_open)


if __name__ == "__main__":
    main()
