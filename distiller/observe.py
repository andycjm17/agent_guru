#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
observe.py — 静默观察层

扫 ~/.claude/projects/**/*.jsonl（每个文件 = 一个 session），按 sessionId 聚合，
每会话产出**紧凑摘要**（不搬全文，控 claude -p 上下文）：
  {title, project, start, end, duration_min, intent, tools, n_turns}
会议从 ~/.meeting-actions/state/processed.json 取标题（旁路语料）。

只出摘要 → data/digests.json。这是后续 distill 的唯一输入。

用法:
  python -m distiller.observe            # 扫描并写 digests.json
  python -m distiller.observe --print    # 顺带打印摘要
"""
from __future__ import annotations

import sys

from . import config as C


# 需要从「真实用户意图」里剔除的噪声前缀（命令回显 / 系统注入 / 本地命令）
_NOISE_PREFIXES = (
    "<command-name>", "<command-message>", "<command-args>",
    "<local-command-stdout>", "<local-command-caveat>",
    "<system-reminder>", "<bash-input>", "<bash-stdout>",
    "caveat:",
)

# 本工具（及会议自动化）的 `claude -p` 子进程会以 session 形式落盘，它们不是人类工作流——
# 按 prompt 的**名字无关**标记识别并剔除，避免语料自我污染（反馈环）。绝不匹配任何人名。
# 维护约定：本项目每新增一处 `claude -p` 调用，都把它名字无关的开场登记到 SIGNATURES。
_AUTOMATION_PROMPT_SIGNATURES = (
    "你是「工作流蒸馏器」",      # distill.py（开场，无人名）
    "你是周报起草助手",          # weekly_update.py（开场，无人名）
)
# 名字无关的任务标记（用 substring 匹配，覆盖外部会议自动化等开头带人名的 prompt）
_AUTOMATION_PHRASES = (
    "产出「会议 action 速递」",   # meeting_actions.py 类会议总结
)

# 相邻事件间隔超过该上限即视为「离开/挂起」，只累加上限内的部分 → 活跃时长（比 wall-clock 跨时更接近真实工时）
_ACTIVE_GAP_CAP_MIN = 5.0


def _is_automation_echo(intent: str, tools: dict) -> bool:
    if tools:
        return False  # 有真实工具调用的不是 -p 回声
    low = (intent or "").lower().lstrip()
    if any(low.startswith(sig.lower()) for sig in _AUTOMATION_PROMPT_SIGNATURES):
        return True
    return any(p in low for p in _AUTOMATION_PHRASES)


def _is_real_user_text(content) -> bool:
    """判定一条 user 消息是否是真实意图文本（而非 tool_result / 命令回显 / 系统注入）。"""
    if not isinstance(content, str):
        return False  # list 形态多为 tool_result，跳过
    s = content.strip()
    if not s:
        return False
    low = s.lower()
    for p in _NOISE_PREFIXES:
        if low.startswith(p):
            return False
    # 纯 slash 命令（/effort 之类）不算意图
    if s.startswith("/") and "\n" not in s and len(s) < 40:
        return False
    return True


def _truncate(s: str, n: int = 200) -> str:
    s = " ".join(s.split())
    return s if len(s) <= n else s[:n] + "…"


def summarize_session(path) -> dict | None:
    """把一个 session jsonl 文件压成一条紧凑摘要。"""
    events = C.read_jsonl(path)
    if not events:
        return None

    session_id = None
    cwd = None
    title = None
    timestamps: list = []     # 所有事件时间（aware UTC）；首尾即起止，无需另维护 ts_min/ts_max
    intents: list[str] = []
    tools: dict[str, int] = {}
    n_user = 0
    n_assistant = 0

    for o in events:
        session_id = session_id or o.get("sessionId")
        if o.get("cwd"):
            cwd = o["cwd"]
        t = C.parse_ts(o.get("timestamp"))   # 统一解析 + naive 补 UTC，避免混比崩溃
        if t:
            timestamps.append(t)

        typ = o.get("type")
        if typ == "ai-title" and o.get("aiTitle"):
            title = o["aiTitle"]            # 取最后一次（最精炼）
        elif typ == "user" and not o.get("isMeta"):
            content = o.get("message", {}).get("content")
            if _is_real_user_text(content):
                n_user += 1
                if len(intents) < 2:
                    intents.append(_truncate(content))
        elif typ == "assistant":
            n_assistant += 1
            content = o.get("message", {}).get("content")
            if isinstance(content, list):
                for b in content:
                    if isinstance(b, dict) and b.get("type") == "tool_use":
                        name = b.get("name", "?")
                        tools[name] = tools.get(name, 0) + 1

    if not session_id:
        return None

    timestamps.sort()
    ts_first = timestamps[0] if timestamps else None
    ts_last = timestamps[-1] if timestamps else None
    duration_min = None      # wall-clock 跨时（会话开着不关会很大，仅作参考）
    active_min = None        # 活跃时长：相邻事件间隔 cap 在 _ACTIVE_GAP_CAP_MIN，更接近真实工时
    if ts_first and ts_last:
        duration_min = round((ts_last - ts_first).total_seconds() / 60.0, 1)
    if len(timestamps) >= 2:   # 少于 2 个事件没有区间可测 → active_min 留 None（区别于真实 0）
        active = 0.0
        for a, b in zip(timestamps, timestamps[1:]):
            active += min((b - a).total_seconds() / 60.0, _ACTIVE_GAP_CAP_MIN)
        active_min = round(active, 1)

    project = None
    if cwd:
        project = cwd.rstrip("/").split("/")[-1] or cwd

    intent = " ／ ".join(intents) if intents else ""
    return {
        "kind": "session",
        "session_id": session_id,
        "title": title or "(无标题)",
        "project": project,
        "start": ts_first.isoformat() if ts_first else None,
        "end": ts_last.isoformat() if ts_last else None,
        "duration_min": duration_min,
        "active_min": active_min,
        "intent": intent,
        "tools": dict(sorted(tools.items(), key=lambda kv: -kv[1])),
        "n_user_turns": n_user,
        "n_assistant_turns": n_assistant,
        "is_automation_echo": _is_automation_echo(intent, tools),
    }


def collect_sessions() -> list[dict]:
    """扫 ~/.claude/projects 下所有顶层 session jsonl（排除 subagent 子会话）。"""
    out = []
    if not C.CLAUDE_PROJECTS.exists():
        return out
    for path in sorted(C.CLAUDE_PROJECTS.rglob("*.jsonl")):
        # 排除 subagent / workflow 子会话：它们隶属某个主 session，不是独立工作流实例
        parts = set(path.parts)
        if "subagents" in parts or "workflows" in parts:
            continue
        try:
            s = summarize_session(path)
        except Exception as e:
            C.log(f"observe: 跳过坏 session 文件 {path.name}: {e!r}")
            continue
        if not s:
            continue
        if s.get("is_automation_echo"):
            continue  # 工具自身/会议自动化的 claude -p 子进程，不计入人类工作流
        if s["n_user_turns"] > 0 or s["tools"]:
            out.append(s)
    # 按开始时间排序
    out.sort(key=lambda s: s.get("start") or "")
    return out


def collect_meetings() -> list[dict]:
    """从 meeting-actions state 取已处理会议（旁路语料）。"""
    out = []
    state = C.load_json(C.MEETING_STATE, default={}) or {}
    for token, v in state.items():
        if not isinstance(v, dict):
            continue
        out.append({
            "kind": "meeting",
            "token": token,
            "title": v.get("title", "(无标题会议)"),
            "status": v.get("status"),
            "at": v.get("at"),
        })
    out.sort(key=lambda m: m.get("at") or "")
    return out


def collect_cursor() -> list:
    """可选：Cursor 会话语料（不强绑定 Claude Code）。缺失/异常静默返回 []。"""
    if str(C._cfg("cursor_enabled", "auto")).lower() in ("0", "false", "off", "no"):
        return []
    try:
        from . import cursor as _cur
        return _cur.collect_cursor_sessions()
    except Exception as e:
        C.log(f"observe: Cursor 源读取异常（忽略）: {e!r}")
        return []


def build_digests() -> dict:
    sessions = collect_sessions()                 # Claude Code ~/.claude/projects
    cursor_sessions = collect_cursor()            # Cursor（可选并列源）
    if cursor_sessions:
        sessions = sorted(sessions + cursor_sessions, key=lambda s: s.get("start") or "")
        C.log(f"observe: 合并 Cursor 会话 {len(cursor_sessions)} 条")
    meetings = collect_meetings()
    return {
        "generated_at": C.now_utc().isoformat(),
        "n_sessions": len(sessions),
        "n_cursor_sessions": len(cursor_sessions),
        "n_meetings": len(meetings),
        "sessions": sessions,
        "meetings": meetings,
    }


def main(argv=None):
    argv = argv or sys.argv[1:]
    C.ensure_dirs()
    digests = build_digests()
    C.save_json(C.DIGESTS_FILE, digests)
    C.log(f"observe: {digests['n_sessions']} sessions + {digests['n_meetings']} meetings → {C.DIGESTS_FILE}")
    if "--print" in argv:
        for s in digests["sessions"]:
            tools = ",".join(f"{k}×{v}" for k, v in s["tools"].items()) or "-"
            print(f"  · 活跃~{s['active_min']}m (跨时{s['duration_min']}m) {s['title']}  | proj={s['project']} | tools={tools}")
            if s["intent"]:
                print(f"      intent: {s['intent'][:120]}")
        for m in digests["meetings"]:
            print(f"  ◇ 会议: {m['title']}")
    return digests


if __name__ == "__main__":
    main()
