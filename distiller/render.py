#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
render.py — 交付层（Lark 文档）

map.json → DocxXML（结论先行 / 表格优先 / 分桶 / 数据口径，正式产出无 emoji）
→ lark-cli docs +create（首次，存 token 到 lark_doc.json）/ +update overwrite（后续）。

直接调 lark-cli（绕开 bytedcli 包装层在 v2 markdown 路径上的 60s 超时）。
--content @file 需相对 cwd 路径，故 cwd=PROJECT_ROOT，文件写在 data/ 下用相对路径传。

用法:
  python -m distiller.render --dry     # 只生成 XML 并打印，不推 Lark
  python -m distiller.render           # 生成 + 推 Lark（首次 create / 后续 update）
"""
from __future__ import annotations

import sys
import re

from . import config as C

DOC_TITLE_BASE = "工作流蒸馏 Map"   # 标题不写死人名；运行时按自动探测到的用户名追加
XML_REL = "data/_map_doc.xml"   # 相对 PROJECT_ROOT；--content @ 需相对路径


def _doc_title() -> str:
    name = C.resolve_user_name()
    return f"{DOC_TITLE_BASE} · {name}" if name else DOC_TITLE_BASE


# ---------- XML 构造 ----------
def esc(s) -> str:
    s = "" if s is None else str(s)
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def th_row(cells: list[str]) -> str:
    tds = "".join(f'<th background-color="light-gray">{esc(c)}</th>' for c in cells)
    return f"<tr>{tds}</tr>"


def td_row(cells: list[str]) -> str:
    tds = "".join(f"<td>{esc(c)}</td>" for c in cells)
    return f"<tr>{tds}</tr>"


def table(headers: list[str], rows: list[list[str]]) -> str:
    head = f"<thead>{th_row(headers)}</thead>"
    body = "<tbody>" + "".join(td_row(r) for r in rows) + "</tbody>"
    return f"<table>{head}{body}</table>"


def _bucket_breakdown(steps: list[dict]) -> str:
    counts: dict[str, int] = {}
    for st in steps:
        b = st.get("bucket")
        counts[b] = counts.get(b, 0) + 1
    parts = [f"{C.BUCKET_ZH.get(b, b)}×{n}" for b, n in counts.items()]
    return " / ".join(parts) or "-"


def build_xml(m: dict) -> str:
    wfs = m.get("workflows", [])
    out: list[str] = [f"<title>{esc(_doc_title())}</title>"]

    # 结论先行
    out.append(f"<callout>{esc(m.get('headline', ''))}</callout>")
    bysrc = m.get("by_source") or {}
    src_note = ("（" + "、".join(f"{k} {v}" for k, v in bysrc.items() if v) + "）") if any(bysrc.values()) else ""
    cohort = (f"数据口径：观察 {m.get('n_sessions', '?')} 个 AI 会话{src_note} + "
              f"{m.get('n_meetings', '?')} 场会议；生成于 {m.get('generated_at', '')[:19]} UTC。"
              f"耗时一律为诚实估算（标 ~），非实测工时。")
    out.append(f"<p>{esc(cohort)}</p>")

    # 一、总览表
    out.append("<h2>一、工作流总览</h2>")
    overview_rows = []
    for w in wfs:
        overview_rows.append([
            w.get("name", ""),
            C.BUCKET_ZH.get(w.get("primary_bucket"), w.get("primary_bucket", "")),
            w.get("frequency", ""),
            f"~{w.get('est_minutes_per_run', '?')}min",
            str(w.get("n_observed", "")),
            w.get("recommendation", ""),
        ])
    out.append(table(["工作流", "主桶", "频率", "估时/次", "实例数", "下一步建议"], overview_rows))

    # 二、分桶汇总（四桶 × 哪些工作流主导）
    out.append("<h2>二、四桶汇总</h2>")
    by_bucket: dict[str, list[str]] = {b: [] for b in C.BUCKETS}
    step_counts: dict[str, int] = {b: 0 for b in C.BUCKETS}
    for w in wfs:
        pb = w.get("primary_bucket")
        if pb in by_bucket:
            by_bucket[pb].append(w.get("name", ""))
        for st in w.get("steps", []):
            b = st.get("bucket")
            if b in step_counts:
                step_counts[b] += 1
    bucket_rows = []
    crit = {
        "eliminate": "没人看 / 历史包袱 → 停掉",
        "automate": "确定性、规则化 → 脚本/launchd",
        "skill": "需判断但可蒸馏 → SKILL.md",
        "human": "人际 / 信任 / 拍板 → 留给人",
    }
    for b in C.BUCKETS:
        bucket_rows.append([
            C.BUCKET_ZH.get(b, b),
            crit[b],
            str(step_counts[b]),
            "、".join(by_bucket[b]) or "—",
        ])
    out.append(table(["桶", "判据", "步骤数", "主导该桶的工作流"], bucket_rows))

    # 三、逐条工作流详情
    out.append("<h2>三、逐条工作流详情</h2>")
    for i, w in enumerate(wfs, 1):
        out.append(f"<h3>{i}. {esc(w.get('name', ''))}</h3>")
        meta = (f"主桶 {C.BUCKET_ZH.get(w.get('primary_bucket'), '?')}｜频率 {w.get('frequency', '')}"
                f"｜单次 ~{w.get('est_minutes_per_run', '?')}min｜观察 {w.get('n_observed', '')} 次"
                f"｜步骤分桶 {_bucket_breakdown(w.get('steps', []))}")
        out.append(f"<p>{esc(meta)}</p>")
        if w.get("summary"):
            out.append(f"<p>{esc(w['summary'])}</p>")
        step_rows = []
        for j, st in enumerate(w.get("steps", []) or [], 1):
            conf = st.get("confidence")
            conf_s = f"{conf:.0%}" if isinstance(conf, (int, float)) else str(conf or "")
            step_rows.append([
                str(j),
                st.get("desc", ""),
                C.BUCKET_ZH.get(st.get("bucket"), st.get("bucket", "")),
                conf_s,
                st.get("next_action", ""),
            ])
        if step_rows:
            out.append(table(["#", "步骤", "桶", "置信", "推进动作"], step_rows))
        else:
            out.append("<p>（暂无步骤拆解）</p>")
        if w.get("instances"):
            inst = "、".join(str(x) for x in w["instances"])
            out.append(f"<p>实例：{esc(inst)}</p>")
        if w.get("recommendation"):
            out.append(f"<callout>下一步：{esc(w['recommendation'])}</callout>")

    # 四、边界声明
    out.append("<h2>四、数据口径与边界</h2>")
    out.append("<ul>"
               "<li>耗时为诚实估算（标 ~），跨时非实际工时；省时口径见 UI banner，含负值。</li>"
               "<li>桶向下流动（人→Skill→自动化）由 UI 自主度开关控制：建议 → 待批草稿 → 自动+通知 → 全自动。</li>"
               "<li>Agent 观察不到的残差 ≈ 不可替代的人类残差（走廊对话、会上拍板不经过 AI），工具只对看得见的下手。</li>"
               "</ul>")
    return "".join(out)


# ---------- 通用 markdown 渲染（给 local / slack 等非飞书 sink）----------
def build_markdown(m: dict) -> str:
    wfs = m.get("workflows", [])
    L = [f"> {m.get('headline', '')}", ""]
    L.append(f"_数据口径：观察 {m.get('n_sessions', '?')} 会话 + {m.get('n_meetings', '?')} 会议；"
             f"生成于 {(m.get('generated_at') or '')[:19]} UTC；耗时为诚实估算（~）。_")
    L.append("")
    L.append("## 一、工作流总览")
    L.append("| 工作流 | 主桶 | 频率 | 估时/次 | 实例 | 下一步 |")
    L.append("|---|---|---|---|---|---|")
    for w in wfs:
        L.append("| {} | {} | {} | ~{}min | {} | {} |".format(
            w.get("name", ""), C.BUCKET_ZH.get(w.get("primary_bucket"), w.get("primary_bucket", "")),
            w.get("frequency", ""), w.get("est_minutes_per_run", "?"),
            w.get("n_observed", ""), (w.get("recommendation", "") or "").replace("|", "／").replace("\n", " ")))
    L.append("")
    L.append("## 二、逐条工作流")
    for i, w in enumerate(wfs, 1):
        L.append(f"### {i}. {w.get('name', '')}")
        L.append(f"主桶 {C.BUCKET_ZH.get(w.get('primary_bucket'), '?')}｜频率 {w.get('frequency', '')}"
                 f"｜~{w.get('est_minutes_per_run', '?')}min｜观察 {w.get('n_observed', '')} 次")
        if w.get("summary"):
            L.append(w["summary"])
        for j, st in enumerate(w.get("steps", []) or [], 1):
            b = C.BUCKET_ZH.get(st.get("bucket"), st.get("bucket", ""))
            L.append(f"  {j}. [{b}] {st.get('desc', '')} → {st.get('next_action', '')}")
        if w.get("recommendation"):
            L.append(f"**下一步**：{w['recommendation']}")
        L.append("")
    return "\n".join(L)


def deliver(m: dict, no_external: bool = False) -> dict:
    """交付 Map：生成 DocxXML(飞书) + markdown(local/slack)，扇出给所有启用 sink。
    no_external=True 时只在本地生成 XML，不向外推（pipeline --no-lark）。"""
    from . import sinks
    xml = build_xml(m)
    (C.PROJECT_ROOT / XML_REL).parent.mkdir(parents=True, exist_ok=True)
    (C.PROJECT_ROOT / XML_REL).write_text(xml, encoding="utf-8")
    if no_external:
        return {"ok": True, "no_external": True, "xml_len": len(xml)}
    md = build_markdown(m)
    res = sinks.broadcast_report(_doc_title(), md, doc_key="map", docx_xml=xml)
    return res


# ---------- Lark 推送 ----------
_URL_RE = re.compile(r"https?://[^\s\"'<>]*larkoffice\.com/[^\s\"'<>]+")
_TOKEN_KEYS = ("url", "doc_url", "document_url", "document_id", "doc_token", "token", "obj_token", "objToken")


def _find_doc_ref(obj):
    """从 lark-cli 返回的 JSON 里递归找文档 URL / token。返回 (url, token)。"""
    url = None
    token = None

    def walk(o):
        nonlocal url, token
        if isinstance(o, dict):
            for k, v in o.items():
                kl = k.lower()
                if isinstance(v, str):
                    if "url" in kl and "larkoffice.com" in v and not url:
                        url = v
                    elif kl in ("document_id", "doc_token", "token", "obj_token", "objtoken") and not token:
                        token = v
                walk(v)
        elif isinstance(o, list):
            for x in o:
                walk(x)

    walk(obj)
    return url, token


def push_to_lark(xml: str) -> dict:
    """首次 create，后续 overwrite。返回 {ok, url, token, raw}。"""
    (C.PROJECT_ROOT / XML_REL).parent.mkdir(parents=True, exist_ok=True)
    (C.PROJECT_ROOT / XML_REL).write_text(xml, encoding="utf-8")

    stored = C.load_json(C.LARK_DOC_FILE, default={}) or {}
    doc_ref = stored.get("url") or stored.get("token")

    if doc_ref:
        cmd = [C.LARK_CLI, "docs", "+update", "--api-version", "v2",
               "--doc", doc_ref, "--command", "overwrite",
               "--content", f"@{XML_REL}", "--doc-format", "xml"]
        action = "update"
    else:
        cmd = [C.LARK_CLI, "docs", "+create", "--api-version", "v2",
               "--content", f"@{XML_REL}", "--doc-format", "xml"]
        action = "create"

    C.log(f"render: lark {action} → {' '.join(cmd)}")
    r = C.run(cmd, timeout=180, cwd=str(C.PROJECT_ROOT))
    raw = (r.stdout or "") + (("\n[stderr] " + r.stderr) if r.stderr else "")
    obj = C.extract_json(r.stdout or "")
    url, token = _find_doc_ref(obj) if obj else (None, None)
    if not url:
        m = _URL_RE.search(r.stdout or "")
        url = m.group(0) if m else None

    if action == "create" and (url or token):
        C.save_json(C.LARK_DOC_FILE, {"url": url, "token": token,
                                      "created_at": C.now_utc().isoformat()})
        try:
            C.LARK_DOC_FILE.chmod(0o600)   # 含文档 token，收紧到仅本人可读写
        except OSError:
            pass

    # 成功判定：优先看 lark-cli 返回 JSON 的 ok 字段（最权威），其次取到 url/token，最后才退回 rc==0
    if obj is not None and "ok" in obj:
        ok = bool(obj.get("ok"))
    else:
        ok = bool(url or token) or (r.returncode == 0)
    if not ok:
        # 失败时把完整 raw（不截断）落到带时间戳的独立日志，便于事后诊断
        ts = C.now_utc().strftime("%Y%m%dT%H%M%SZ")
        errlog = C.LOG_DIR / f"render_fail_{ts}.log"
        try:
            errlog.write_text(f"action={action} rc={r.returncode}\ncmd={' '.join(cmd)}\n\n{raw}", encoding="utf-8")
        except OSError:
            pass
        C.log(f"render: lark {action} 失败 rc={r.returncode}，全文见 {errlog.name}; head={raw[:300]}")
    return {"ok": ok, "action": action, "url": url or doc_ref, "token": token, "raw": raw[:500]}


def main(argv=None):
    argv = argv or sys.argv[1:]
    C.ensure_dirs()
    m = C.load_json(C.MAP_FILE)
    if not m:
        C.log("render: 缺 map.json，请先跑 distill")
        return None
    xml = build_xml(m)
    (C.PROJECT_ROOT / XML_REL).parent.mkdir(parents=True, exist_ok=True)
    (C.PROJECT_ROOT / XML_REL).write_text(xml, encoding="utf-8")
    C.log(f"render: 生成 DocxXML {len(xml)} 字符 → {XML_REL}")

    if "--dry" in argv:
        print(xml[:2000])
        print(f"\n...(共 {len(xml)} 字符，已写 {XML_REL}；--dry 未推任何渠道)")
        return {"xml": xml}

    res = deliver(m)
    oks = "、".join(k for k, v in (res.get("results") or {}).items() if v.get("ok")) or "(无)"
    if res.get("url"):
        C.log(f"render: 已交付 → {oks}；URL {res['url']}")
        print(f"\n已交付到渠道：{oks}\n  链接/路径：{res['url']}")
    else:
        C.log(f"render: 已交付 → {oks}（无 URL）")
        print(f"\n已交付到渠道：{oks}")
    return res


if __name__ == "__main__":
    main()
