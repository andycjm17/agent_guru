#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
weekly_update.py — wedge 闭环：「每周 1-on-1-on-1 update」工作流拆桶

  - 收集本周进展（session digests + 会议摘要）= 自动
  - 按 §3.9 / weekly 约定撰写              = skill（判断交 claude，格式交 Python）
  - 拍板 / 取舍 / 推送到 live 周报文档      = 人（--approve 闸门）

设计：claude -p 只产出**结构化 JSON**（Track 聚类 + 进度 + Actions@owner + 会上讨论 +
配置的跟进人单列），Python 确定性渲染成符合 weekly 约定的 DocxXML 周块——格式保真、
不依赖 LLM 拼 XML。默认只出 draft-for-approval；--approve 才推 Lark 并写 savings。

weekly 约定（来自 memory）：
  - 无「汇报人」行；week = 滚动 7 天窗口，end=会议日，周号取 end 的 ISO 周
  - 标签格式 <year>-W<NN>（MM/DD – MM/DD）；新周置顶，<hr/> 分隔
  - 每 PRD 一个 <h2> → 2 列表（进度 ｜ Action，checkbox，表头 light-gray，vertical-align top）
  - 「会上讨论」<h2> 收在本周末尾；config.local.json 的 tracked_people 单列开发跟进

用法:
  python -m distiller.weekly_update              # 出本周草稿（不推 Lark）
  python -m distiller.weekly_update --end 2026-05-28
  python -m distiller.weekly_update --approve    # 批准后推送到周报文档 + 写 savings
"""
from __future__ import annotations

import sys
import re
import argparse
import datetime as dt

from . import config as C
from . import savings as S
from . import render as R   # 复用 esc / table / push 模式

WEEKLY_DOC_URL = C.WEEKLY_DOC_URL        # 来自 config.local.json；空 = 未配置
TRACKED_PEOPLE = C.TRACKED_PEOPLE        # 来自 config.local.json；空 = 不输出单列跟进节
DRAFT_XML = "data/_weekly_draft.xml"


# ---------- 周窗口 ----------
def week_window(end: dt.date) -> dict:
    start = end - dt.timedelta(days=7)
    iso = end.isocalendar()   # 跨年用 ISO 年(iso[0])而非日历年，避免年初/年末周号年份错配
    label = f"{iso[0]}-W{iso[1]:02d}（{start.strftime('%m/%d')} – {end.strftime('%m/%d')}）"
    return {"start": start, "end": end, "label": label}


def _in_window(ts: str | None, start: dt.date, end: dt.date) -> bool:
    # 采集用半开区间 (start, end]：标签端点照常含 start 仅作展示，但收集排除 start 日，
    # 使相邻两周不在边界日(上周会议日)重叠重复统计。
    d = C.parse_ts(ts)
    if d is None:
        return False
    return start < d.date() <= end


# ---------- 信号聚合（自动） ----------
def collect_week_signals(digests: dict, win: dict) -> dict:
    sessions = [s for s in digests.get("sessions", [])
                if _in_window(s.get("start"), win["start"], win["end"])]
    meetings = [m for m in digests.get("meetings", [])
                if _in_window(m.get("at"), win["start"], win["end"])]
    return {"sessions": sessions, "meetings": meetings}


PROMPT_TMPL = """你是周报起草助手，在帮{who}起草「每周 1-on-1-on-1 Update」周报的**结构化骨架**。
下面是本周（{label}）TA 用 AI 干活的 session 摘要 + 会议清单。请聚类成若干 Track（按 PRD/主题），
每个 Track 给本周进度与待办，并把会上讨论、以及【{people}】相关的开发事项单独拎出来。

严格只输出 JSON（不要 markdown 代码块、不要解释），结构：
{{
  "tracks": [
    {{
      "name": "Track / PRD 名（如『clip 透传实验』『Violation Insight 评测』）",
      "prd_hint": "若能从标题推断关联 PRD/wiki 主题，写一句；否则空串",
      "progress": ["本周进度要点（动词开头、结论先行、各一句）"],
      "actions": [{{"owner": "负责人（没有就写 待定）", "text": "下一步事项", "done": false}}]
    }}
  ],
  "tracked_dev": [{{"owner": "{people_pipe}", "text": "该人相关的开发跟进事项（无跟进人则留空数组）"}}],
  "discussion": ["需要在 1-on-1-on-1 会上讨论/拍板/取舍的点（开放问题、风险、需对齐的决策）"]
}}

要求：
- 进度与 Action 都基于下面真实信号，不要编造未出现的项目；信息不足的 Track 宁可少写。
- Action 的 owner 用真实人名；涉及 {people} 的开发事项**必须**同时进 tracked_dev。
- discussion 只放真正需要人拍板/对齐的，不放已确定的执行项。
- 全程中文，技术名词英文；不用 emoji。

=== 本周 session（{n_sess} 条）===
{sessions}

=== 本周会议（{n_meet} 条）===
{meetings}
"""


def build_prompt(signals: dict, win: dict) -> str:
    def fmt_s(s):
        tools = ", ".join(f"{k}×{v}" for k, v in (s.get("tools") or {}).items()) or "无工具"
        act = s.get("active_min")
        act_s = f"活跃~{act}min" if act is not None else "活跃?"   # 与 distill 口径一致，不用高估的 wall-clock
        return f"- 「{s.get('title')}」proj={s.get('project')} {act_s} | 意图: {s.get('intent') or '(无)'} | 工具: {tools}"

    def fmt_m(m):
        return f"- {m.get('title')}"

    sess = "\n".join(fmt_s(s) for s in signals["sessions"]) or "(本周无 session)"
    meet = "\n".join(fmt_m(m) for m in signals["meetings"]) or "(本周无会议)"
    people = " / ".join(TRACKED_PEOPLE) if TRACKED_PEOPLE else "（本部署未配置跟进人）"
    people_pipe = "|".join(TRACKED_PEOPLE) if TRACKED_PEOPLE else "（无）"
    name = C.resolve_user_name()
    who = f" {name} " if name else "本人"   # 自动读取的用户名；探测不到用中性「本人」
    return PROMPT_TMPL.format(
        who=who, label=win["label"], people=people, people_pipe=people_pipe,
        n_sess=len(signals["sessions"]), n_meet=len(signals["meetings"]),
        sessions=sess, meetings=meet,
    )


# ---------- 确定性渲染 DocxXML（格式保真） ----------
def _is_done(v) -> bool:
    """布尔归一：LLM 可能返回字符串 "false"/"0"（bool("false")==True 会误判已完成）。
    与 as_num 同口径，对脏值稳健。"""
    if isinstance(v, bool):
        return v
    if isinstance(v, (int, float)):
        return v != 0
    return str(v).strip().lower() in ("true", "1", "yes", "done", "完成", "已完成")


def render_week_xml(data: dict, win: dict) -> str:
    out: list[str] = [f"<h1>{R.esc(win['label'])}</h1>"]
    for tr in data.get("tracks", []):
        out.append(f"<h2>{R.esc(tr.get('name', ''))}</h2>")
        if tr.get("prd_hint"):
            out.append(f"<p>关联：{R.esc(tr['prd_hint'])}</p>")
        prog = tr.get("progress", []) or []
        acts = tr.get("actions", []) or []
        prog_cell = "".join(f"<p>{R.esc(p)}</p>" for p in prog) or "<p>—</p>"
        act_cell = "".join(
            f'<checkbox done="{"true" if _is_done(a.get("done")) else "false"}">'
            f"@{R.esc(a.get('owner', '待定'))} {R.esc(a.get('text', ''))}</checkbox>"
            for a in acts
        ) or "<p>—</p>"
        out.append(
            "<table><colgroup><col/><col/></colgroup>"
            '<thead><tr><th background-color="light-gray">进度</th>'
            '<th background-color="light-gray">Action</th></tr></thead>'
            f'<tbody><tr><td vertical-align="top">{prog_cell}</td>'
            f'<td vertical-align="top">{act_cell}</td></tr></tbody></table>'
        )

    tracked = data.get("tracked_dev", []) or []
    if tracked:
        hdr = (" / ".join(TRACKED_PEOPLE) if TRACKED_PEOPLE else "重点") + " 开发跟进"
        out.append(f"<h2>{R.esc(hdr)}</h2>")
        out.append("<ul>" + "".join(
            f"<li>@{R.esc(t.get('owner', ''))}：{R.esc(t.get('text', ''))}</li>" for t in tracked
        ) + "</ul>")

    disc = data.get("discussion", []) or []
    out.append("<h2>会上讨论</h2>")
    out.append("<ul>" + "".join(f"<li>{R.esc(d)}</li>" for d in disc) + "</ul>"
               if disc else "<p>（本周无需会上讨论的开放项）</p>")
    out.append("<hr/>")
    return "".join(out)


def render_preview(data: dict, win: dict) -> str:
    """给人看的纯文本预览。"""
    lines = [f"# {win['label']}", ""]
    for tr in data.get("tracks", []):
        lines.append(f"## {tr.get('name', '')}")
        if tr.get("prd_hint"):
            lines.append(f"   关联：{tr['prd_hint']}")
        lines.append("   进度：")
        for p in tr.get("progress", []) or ["—"]:
            lines.append(f"     · {p}")
        lines.append("   Action：")
        for a in tr.get("actions", []) or []:
            box = "[x]" if _is_done(a.get("done")) else "[ ]"
            lines.append(f"     {box} @{a.get('owner', '待定')} {a.get('text', '')}")
        lines.append("")
    tracked = data.get("tracked_dev", []) or []
    if tracked:
        lines.append("## " + (" / ".join(TRACKED_PEOPLE) if TRACKED_PEOPLE else "重点") + " 开发跟进")
        for t in tracked:
            lines.append(f"   · @{t.get('owner', '')}：{t.get('text', '')}")
        lines.append("")
    lines.append("## 会上讨论")
    for d in data.get("discussion", []) or ["（无）"]:
        lines.append(f"   · {d}")
    return "\n".join(lines)


# ---------- 推送（人工闸门） ----------
def _resolve_weekly_doc() -> str:
    """周报文档目标：config 显式 URL → 之前自动创建并存下的 weekly_doc.json。空 = 还没有。"""
    if WEEKLY_DOC_URL:
        return WEEKLY_DOC_URL
    stored = C.load_json(C.WEEKLY_DOC_FILE, default={}) or {}
    return stored.get("url") or stored.get("token") or ""


def _create_weekly_doc(week_xml: str) -> dict:
    """零配置首跑：自动创建『每周 1-on-1-on-1 Update』文档，本周块即初始内容；存 token 供后续复用。"""
    xml = "<title>每周 1-on-1-on-1 Update</title>" + week_xml
    (C.PROJECT_ROOT / DRAFT_XML).write_text(xml, encoding="utf-8")
    cmd = [C.LARK_CLI, "docs", "+create", "--api-version", "v2",
           "--content", f"@{DRAFT_XML}", "--doc-format", "xml"]
    C.log("weekly: 未配置周报文档 → 自动创建")
    r = C.run(cmd, timeout=180, cwd=str(C.PROJECT_ROOT))
    obj = C.extract_json(r.stdout or "")
    url, token = R._find_doc_ref(obj) if obj else (None, None)
    if not url:
        m = R._URL_RE.search(r.stdout or "")
        url = m.group(0) if m else None
    if url or token:
        C.save_json(C.WEEKLY_DOC_FILE, {"url": url, "token": token,
                                        "created_at": C.now_utc().isoformat()})
    ok = bool(url or token) or (obj.get("ok") if isinstance(obj, dict) else r.returncode == 0)
    return {"ok": bool(ok), "action": "create(自动新建周报文档)", "url": url or token,
            "raw": ((r.stdout or "") + (r.stderr or ""))[:400]}


def approve_and_push(week_xml: str) -> dict:
    """把本周块插入周报文档最前（新周置顶）。无现成文档则自动创建（零配置）。
    策略：fetch with-ids 找到第一个『周 H1』(\\d{4}-W\\d) 的前一个 block，
    block_insert_after 到它之后；找不到则 append 兜底。
    """
    doc = _resolve_weekly_doc()
    if not doc:
        return _create_weekly_doc(week_xml)

    (C.PROJECT_ROOT / DRAFT_XML).write_text(week_xml, encoding="utf-8")

    # 1) 取带 id 的文档，定位插入锚点
    fr = C.run([C.LARK_CLI, "docs", "+fetch", "--doc", doc,
                "--api-version", "v2", "--detail", "with-ids"], timeout=120)
    obj = C.extract_json(fr.stdout or "")
    content = ""
    if obj:
        # content 在 data.document.content；with-ids 后块带 data-block-id 属性
        def find_content(o):
            if isinstance(o, dict):
                if "content" in o and isinstance(o["content"], str):
                    return o["content"]
                for v in o.values():
                    r = find_content(v)
                    if r:
                        return r
            elif isinstance(o, list):
                for v in o:
                    r = find_content(v)
                    if r:
                        return r
            return None
        content = find_content(obj) or ""

    # 定位第一个『周 H1』(\d{4}-W\d) 所在 block，锚到它「前一个」block →
    # block_insert_after 该锚点 = 新周落在所有历史周之前（置顶，符合 weekly 约定）。
    ids_pos = [(m.group(1), m.start()) for m in re.finditer(r'data-block-id="([^"]+)"', content)]
    anchor_id = None
    week_idx = None
    for idx, (_bid, pos) in enumerate(ids_pos):
        end = ids_pos[idx + 1][1] if idx + 1 < len(ids_pos) else len(content)
        if re.search(r"\d{4}-W\d", content[pos:end]):
            week_idx = idx
            break
    if week_idx is None and ids_pos:
        anchor_id = ids_pos[0][0]              # 文档还没有历史周块：插到顶部 intro 之后
    elif week_idx is not None and week_idx > 0:
        anchor_id = ids_pos[week_idx - 1][0]   # 第一个周块的前一个块 → 插其后 = 置顶
    elif week_idx == 0:
        # 周块即文档首块、无前块可锚（lark-cli 无 block_insert_before）→ 只能 append 到末尾，
        # 这违反「新周置顶」约定，显式告警让人知道需手工把新周拖到顶部。
        C.log("weekly: ⚠ 首个周块即文档首块，无法置顶插入，降级为 append（请手工调整顺序或在顶部加序言块）")

    if anchor_id:
        cmd = [C.LARK_CLI, "docs", "+update", "--api-version", "v2",
               "--doc", doc, "--command", "block_insert_after",
               "--block-id", anchor_id, "--content", f"@{DRAFT_XML}", "--doc-format", "xml"]
        action = f"block_insert_after({anchor_id[:8]}…，置顶)"
    else:
        cmd = [C.LARK_CLI, "docs", "+update", "--api-version", "v2",
               "--doc", doc, "--command", "append",
               "--content", f"@{DRAFT_XML}", "--doc-format", "xml"]
        action = "append(兜底)"

    C.log(f"weekly: 推送 {action}")
    r = C.run(cmd, timeout=180, cwd=str(C.PROJECT_ROOT))
    raw = (r.stdout or "") + (("\n[stderr] " + r.stderr) if r.stderr else "")
    # 与 render/lark_dm 同口径：优先看返回 JSON 的 ok 字段，避免脆弱子串匹配误判
    pobj = C.extract_json(r.stdout or "")
    if pobj is not None and "ok" in pobj:
        ok = bool(pobj.get("ok"))
    else:
        ok = (r.returncode == 0)
    return {"ok": ok, "action": action, "raw": raw[:400]}


def main(argv=None):
    argv = argv if argv is not None else sys.argv[1:]
    C.ensure_dirs()
    p = argparse.ArgumentParser(prog="distiller.weekly_update")
    p.add_argument("--end", default=None, help="周窗口结束日 YYYY-MM-DD（默认今天）")
    p.add_argument("--approve", action="store_true", help="批准并推送到 live 周报文档")
    p.add_argument("--force", action="store_true", help="忽略本周已推送记录，强制重推")
    args = p.parse_args(argv)

    end = dt.date.fromisoformat(args.end) if args.end else dt.date.today()
    win = week_window(end)
    C.log(f"weekly: 窗口 {win['label']}")

    digests = C.load_json(C.DIGESTS_FILE)
    if not digests:
        C.log("weekly: 缺 digests.json，请先跑 observe")
        return None
    signals = collect_week_signals(digests, win)
    C.log(f"weekly: 本周信号 {len(signals['sessions'])} session + {len(signals['meetings'])} 会议")
    if not signals["sessions"] and not signals["meetings"]:
        C.log("weekly: 本周无信号，跳过")
        return None

    data = C.llm(build_prompt(signals, win), timeout=300, expect_json=True)
    if not data:
        C.log(f"weekly: LLM[{C.active_provider()}] 起草失败")
        return None

    week_xml = render_week_xml(data, win)
    (C.PROJECT_ROOT / DRAFT_XML).write_text(week_xml, encoding="utf-8")
    preview = render_preview(data, win)
    print("\n========== 本周周报草稿（draft-for-approval）==========\n")
    print(preview)
    print(f"\n[DocxXML 已写 {DRAFT_XML}（{len(week_xml)} 字符）]")

    if not args.approve:
        tgt = _resolve_weekly_doc()
        print("\n→ 这是草稿。加 --approve 推送（人工闸门）。" +
              ("目标文档：" + tgt if tgt else "首次 --approve 将自动创建周报文档。"))
        return {"data": data, "xml": week_xml, "preview": preview}

    # 幂等闸门：同一周避免重复插块 + 重复写 savings（照搬 retro 的 state 模式）
    wk_key = f"weekly-{win['label']}"
    state = C.load_json(C.PROCESSED_FILE, default={}) or {}
    if wk_key in state and not args.force:
        C.log(f"weekly: {win['label']} 已推送过（{state[wk_key].get('at')}），跳过；--force 可重推")
        print(f"\n→ 本周已推送过（{state[wk_key].get('at')}）。如需重推加 --force。")
        return {"skipped": True}

    res = approve_and_push(week_xml)
    if res["ok"]:
        doc_ref = res.get("url") or _resolve_weekly_doc() or "(周报文档)"
        C.log(f"weekly: 已推送 [{res['action']}] → {doc_ref}")
        print(f"\n已写入周报文档：{doc_ref}")
        # 仅在成功后标记 state（失败保持可重试）+ 写 savings（诚实估算）
        state[wk_key] = {"at": C.now_utc().isoformat(), "action": res["action"]}
        C.save_json(C.PROCESSED_FILE, state)
        S.record("每周1-on-1-on-1 update", est_saved_min=40, est_overhead_min=6,
                 note=f"{win['label']} 草稿生成+推送")
    else:
        C.log(f"weekly: 推送失败 {res['raw']}")
        print(f"\n推送失败：{res['raw']}")
    return res


if __name__ == "__main__":
    main()
