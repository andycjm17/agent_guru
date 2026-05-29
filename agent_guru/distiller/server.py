#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
server.py — 轻量本地 UI（纯 stdlib http.server，无 npm/无构建）

localhost:PORT 单页三块：
  1. 省时 punchline banner（savings.summary，含负值染红）
  2. Workflow Map 表（工作流 | 主桶 | 频率 | 估时 | 分桶占比 | next step）
  3. Skills 配置：扫 ~/.claude/skills/*/SKILL.md frontmatter，每个 skill 一个自主度下拉，
     POST 回写 data/skills_config.json

API:
  GET  /                 → ui/index.html
  GET  /api/map          → map.json
  GET  /api/savings?days=7
  GET  /api/skills       → [{name, description, autonomy}]
  POST /api/skills       → {name, autonomy} 回写 skills_config.json

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

DEFAULT_PORT = C.UI_PORT   # 来自 config.local.json（默认 8787）


# ---------- skills 扫描 ----------
def _parse_frontmatter(text: str) -> dict:
    """从 SKILL.md 抠 YAML frontmatter 的 name / description（不引第三方 yaml）。
    支持 description 折叠块（`description: >` 后跟缩进多行）。
    """
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}
    fm: list[str] = []
    for ln in lines[1:]:
        if ln.strip() == "---":
            break
        fm.append(ln)
    out = {"name": "", "description": ""}
    i = 0
    while i < len(fm):
        ln = fm[i]
        if ln.startswith("name:"):
            out["name"] = ln.split(":", 1)[1].strip()
        elif ln.startswith("description:"):
            val = ln.split(":", 1)[1].strip()
            if val in (">", "|", ">-", "|-", "", ">+", "|+"):
                # 折叠块：收集后续更深缩进的行
                buf = []
                j = i + 1
                while j < len(fm) and (fm[j].startswith("  ") or fm[j].strip() == ""):
                    buf.append(fm[j].strip())
                    j += 1
                out["description"] = " ".join(x for x in buf if x)
                i = j
                continue
            else:
                out["description"] = val
        i += 1
    return out


_CFG_LOCK = threading.Lock()   # 串行化 skills_config 的读改写，避免多线程并发丢更新


def scan_skills() -> list[dict]:
    cfg = C.load_json(C.SKILLS_CONFIG, default={}) or {}
    out = []
    if C.CLAUDE_SKILLS.exists():
        for d in sorted(C.CLAUDE_SKILLS.iterdir()):
            sf = d / "SKILL.md"
            if not sf.exists():
                continue
            # 单个坏/不可读 SKILL.md 不应让整个 /api/skills 崩——逐个隔离
            try:
                fm = _parse_frontmatter(sf.read_text(encoding="utf-8", errors="replace"))
            except OSError as e:
                C.log(f"server: 跳过不可读 skill {d.name}: {e!r}")
                continue
            name = fm.get("name") or d.name
            autonomy = (cfg.get(name) or {}).get("autonomy", "suggest")
            out.append({
                "name": name,
                "description": (fm.get("description") or "")[:300],
                "autonomy": autonomy,
            })
    return out


def set_skill_autonomy(name: str, autonomy: str) -> bool:
    if autonomy not in C.AUTONOMY_LEVELS:
        return False
    with _CFG_LOCK:   # load→mutate→save 原子化
        cfg = C.load_json(C.SKILLS_CONFIG, default={}) or {}
        cfg.setdefault(name, {})["autonomy"] = autonomy
        cfg[name]["updated_at"] = C.now_utc().isoformat()
        C.save_json(C.SKILLS_CONFIG, cfg)
    C.log(f"server: skill 自主度 {name} → {autonomy}")
    return True


# ---------- HTTP ----------
class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        pass  # 静默，避免刷屏

    def _send(self, code, body, ctype="application/json; charset=utf-8"):
        if isinstance(body, (dict, list)):
            body = json.dumps(body, ensure_ascii=False)
        data = body.encode("utf-8") if isinstance(body, str) else body
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        u = urlparse(self.path)
        path = u.path
        if path == "/" or path == "/index.html":
            html = (C.UI_DIR / "index.html")
            if html.exists():
                self._send(200, html.read_text(encoding="utf-8"), "text/html; charset=utf-8")
            else:
                self._send(404, "ui/index.html 不存在", "text/plain; charset=utf-8")
        elif path == "/api/map":
            self._send(200, C.load_json(C.MAP_FILE, default={"workflows": [], "headline": "(还没跑 distill)"}))
        elif path == "/api/savings":
            raw = parse_qs(u.query).get("days", ["7"])[0] or "7"
            try:
                days = int(raw)
            except (TypeError, ValueError):
                return self._send(400, {"error": f"非法 days: {raw!r}（需整数）"})
            days = min(days, 36500)   # 上限 ~100 年，挡 timedelta OverflowError；days<=0 仍走累计分支
            self._send(200, S.summary(days))
        elif path == "/api/skills":
            self._send(200, {"skills": scan_skills(),
                             "levels": [{"value": v, "label": C.AUTONOMY_ZH[v]} for v in C.AUTONOMY_LEVELS]})
        else:
            self._send(404, {"error": "not found"})

    def do_POST(self):
        try:
            u = urlparse(self.path)
            if u.path != "/api/skills":
                return self._send(404, {"error": "not found"})
            # Content-Length 防御：非法/负值/超大一律拒（避免 read(-1) 挂死线程）
            try:
                length = int(self.headers.get("Content-Length", "0") or 0)
            except (TypeError, ValueError):
                return self._send(400, {"ok": False, "error": "bad content-length"})
            if length < 0 or length > 1_000_000:
                return self._send(400, {"ok": False, "error": "bad content-length"})
            try:
                body = json.loads(self.rfile.read(length) or b"{}")
            except Exception:
                return self._send(400, {"ok": False, "error": "bad json"})
            autonomy = body.get("autonomy", "")
            ok = set_skill_autonomy(body.get("name", ""), autonomy)
            if ok:
                self._send(200, {"ok": True})
            else:
                self._send(400, {"ok": False,
                                 "error": f"非法 autonomy: {autonomy!r}（合法值 {C.AUTONOMY_LEVELS}）"})
        except Exception as e:
            C.log(f"server: do_POST 异常 {e!r}")
            try:
                self._send(500, {"ok": False, "error": "internal error"})
            except Exception:
                pass


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
