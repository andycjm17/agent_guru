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
import datetime as dt

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

# 观察窗口默认天数（config observe_days 可覆盖；0 = 不限）。语料是「近期复发的工作流」，
# 无窗会把全部历史喂给 LLM——重度用户上千个 session = 上百批蒸馏调用，跑数小时。
_DEFAULT_OBSERVE_DAYS = 30


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
    entrypoint = None
    timestamps: list = []     # 所有事件时间（aware UTC）；首尾即起止，无需另维护 ts_min/ts_max
    intents: list[str] = []
    tools: dict[str, int] = {}
    n_user = 0
    n_assistant = 0

    for o in events:
        session_id = session_id or o.get("sessionId")
        entrypoint = entrypoint or o.get("entrypoint")
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
        "entrypoint": entrypoint or "",
        # entrypoint=="sdk-cli" 等 sdk* 是 `claude -p` / Agent SDK 落盘的结构性标记（交互式为
        # "cli"/"claude-desktop"）——这是判别 headless 自动化最可靠的口径，不依赖 prompt 内容。
        # 字段缺失（旧版本会话）保守视为真人，仍由 prompt 签名过滤兜底。
        "is_headless": bool(entrypoint and str(entrypoint).lower().startswith("sdk")),
        "is_automation_echo": _is_automation_echo(intent, tools),
    }


def collect_sessions(days: "int | None" = None) -> list[dict]:
    """扫 ~/.claude/projects 下所有顶层 session jsonl（排除 subagent 子会话）。

    只看最近 days 天（None = 取 config observe_days，默认 30；0 = 不限）。先按文件 mtime
    预过滤（窗外文件免解析，扫描提速），再按会话 end 时间终判。headless（sdk*）会话剔除。"""
    out = []
    if not C.CLAUDE_PROJECTS.exists():
        return out
    if days is None:
        days = C._int_cfg("observe_days", _DEFAULT_OBSERVE_DAYS)
    cutoff = (C.now_utc() - dt.timedelta(days=min(days, 36500))) if days > 0 else None
    n_headless = 0
    for path in sorted(C.CLAUDE_PROJECTS.rglob("*.jsonl")):
        # 排除 subagent / workflow 子会话：它们隶属某个主 session，不是独立工作流实例
        parts = set(path.parts)
        if "subagents" in parts or "workflows" in parts:
            continue
        if cutoff is not None:
            try:
                mtime = dt.datetime.fromtimestamp(path.stat().st_mtime, dt.timezone.utc)
            except OSError:
                continue
            if mtime < cutoff:
                continue   # 最后写入早于窗口 → 窗内无事件
        try:
            s = summarize_session(path)
        except Exception as e:
            C.log(f"observe: 跳过坏 session 文件 {path.name}: {e!r}")
            continue
        if not s:
            continue
        if s.get("is_headless"):
            n_headless += 1
            continue  # claude -p / Agent SDK 批量调用（评测、回测等），不是人类工作流
        if s.get("is_automation_echo"):
            continue  # 工具自身/会议自动化的 claude -p 子进程，不计入人类工作流
        if cutoff is not None:
            end = C.parse_ts(s.get("end"))
            if end is not None and end < cutoff:
                continue
        if s["n_user_turns"] > 0 or s["tools"]:
            out.append(s)
    if n_headless:
        C.log(f"observe: 已排除 {n_headless} 条 headless(claude -p / SDK) 会话")
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
    """从所有「启用的 Agent 平台」收集会话摘要（Claude Code / Cursor / Codex …），并入会议旁路语料。
    平台集合由 config sources 驱动，缺省自动探测——这是「解绑 Claude Code」的入口。"""
    from .agents import enabled_platforms
    sessions: list = []
    by_source: dict = {}
    for p in enabled_platforms():
        try:
            ss = p.collect_sessions() or []
        except Exception as e:
            C.log(f"observe: 平台 {p.key} 观察异常（忽略）: {e!r}")
            ss = []
        for s in ss:
            s.setdefault("source", p.key)
        by_source[p.key] = len(ss)
        if ss:
            C.log(f"observe: {p.label} 贡献 {len(ss)} 条会话")
        sessions += ss
    sessions.sort(key=lambda s: s.get("start") or "")
    meetings = collect_meetings()
    return {
        "generated_at": C.now_utc().isoformat(),
        "n_sessions": len(sessions),
        "by_source": by_source,                       # 各平台贡献的会话数（doctor/UI 展示）
        "n_cursor_sessions": by_source.get("cursor", 0),  # 向后兼容旧字段
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
            act = s["active_min"] if s["active_min"] is not None else "?"
            dur = s["duration_min"] if s["duration_min"] is not None else "?"
            print(f"  · 活跃~{act}m (跨时{dur}m) {s['title']}  | proj={s['project']} | tools={tools}")
            if s["intent"]:
                print(f"      intent: {s['intent'][:120]}")
        for m in digests["meetings"]:
            print(f"  ◇ 会议: {m['title']}")
    return digests


if __name__ == "__main__":
    main()
