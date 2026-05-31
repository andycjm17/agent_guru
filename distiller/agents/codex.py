#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
agents/codex.py — OpenAI Codex CLI 适配器

观察源：~/.codex/sessions/YYYY/MM/DD/rollout-*.jsonl
  每行 = 一个 RolloutLine 信封 {timestamp, type, payload}：
    - type="event_msg"     payload.type="user_message"|"agent_message"  → message 文本
    - type="response_item" payload.type="message" role=user/assistant content[].text；
                            payload.type="function_call" → 工具名
    - type="SessionMeta"   payload.cwd / session_id（首行）
  老版本（<0.44）可能是「裸记录」无信封——本解析器对两种形态都防御式处理，缺字段即跳过。
Skill 落地：~/.codex/prompts/<slug>.md（Codex 自定义 prompt / 斜杠命令；可选 YAML frontmatter）

只读会话历史、绝不改；任何缺失/异常静默返回已得部分，绝不影响主流程。
"""
from __future__ import annotations

import pathlib

from .. import config as C
from .base import AgentPlatform, slugify

_ACTIVE_GAP_CAP_MIN = 5.0


def _truncate(s: str, n: int = 200) -> str:
    s = " ".join((s or "").split())
    return s if len(s) <= n else s[:n] + "…"


def _texts_from_content(content) -> str:
    """从 response_item.message.content[] 里拼出文本（input_text / text / output_text）。"""
    if isinstance(content, str):
        return content
    parts = []
    if isinstance(content, list):
        for b in content:
            if isinstance(b, dict):
                t = b.get("type") or ""
                if t in ("input_text", "text", "output_text") and b.get("text"):
                    parts.append(str(b["text"]))
    return " ".join(parts)


def _summarize_codex_file(path) -> "dict | None":
    events = C.read_jsonl(path)
    if not events:
        return None
    cwd = None
    timestamps = []
    intents = []
    tools = {}
    n_user = 0
    n_assistant = 0

    for o in events:
        if not isinstance(o, dict):
            continue
        t = C.parse_ts(o.get("timestamp"))
        if t:
            timestamps.append(t)
        typ = o.get("type")
        payload = o.get("payload") if isinstance(o.get("payload"), dict) else None

        # ---- 带信封的新格式 ----
        if payload is not None:
            if not cwd and payload.get("cwd"):
                cwd = payload.get("cwd")
            ptype = payload.get("type")
            if typ == "event_msg":
                if ptype == "user_message":
                    msg = (payload.get("message") or "").strip()
                    if msg and not msg.startswith("<"):
                        n_user += 1
                        if len(intents) < 2:
                            intents.append(_truncate(msg))
                elif ptype == "agent_message":
                    n_assistant += 1
                elif ptype and ("ToolCall" in ptype or "tool_call" in ptype.lower()):
                    nm = payload.get("tool") or payload.get("name") or ptype
                    tools[nm] = tools.get(nm, 0) + 1
            elif typ == "response_item":
                if ptype == "message":
                    role = payload.get("role")
                    txt = _texts_from_content(payload.get("content")).strip()
                    if role == "user":
                        if txt and not txt.startswith("<"):
                            n_user += 1
                            if len(intents) < 2:
                                intents.append(_truncate(txt))
                    elif role == "assistant":
                        n_assistant += 1
                elif ptype in ("function_call", "local_shell_call", "custom_tool_call"):
                    nm = payload.get("name") or ptype
                    tools[nm] = tools.get(nm, 0) + 1
            continue

        # ---- 裸记录兜底（老格式 / 直接 message 形态）----
        if not cwd and o.get("cwd"):
            cwd = o.get("cwd")
        role = o.get("role")
        if role in ("user", "assistant"):
            txt = _texts_from_content(o.get("content")).strip()
            if role == "user" and txt and not txt.startswith("<"):
                n_user += 1
                if len(intents) < 2:
                    intents.append(_truncate(txt))
            elif role == "assistant":
                n_assistant += 1

    if not timestamps and not intents:
        return None

    timestamps.sort()
    ts_first = timestamps[0] if timestamps else None
    ts_last = timestamps[-1] if timestamps else None
    duration_min = None
    active_min = None
    if ts_first and ts_last:
        duration_min = round((ts_last - ts_first).total_seconds() / 60.0, 1)
    if len(timestamps) >= 2:
        active = 0.0
        for a, b in zip(timestamps, timestamps[1:]):
            active += min((b - a).total_seconds() / 60.0, _ACTIVE_GAP_CAP_MIN)
        active_min = round(active, 1)

    project = None
    if cwd:
        project = str(cwd).rstrip("/").split("/")[-1] or str(cwd)
    intent = " ／ ".join(intents)
    title = (intents[0][:40] if intents else (project or "(Codex 会话)"))

    # 自动化回声判定：复用 observe 的同口径启发式
    try:
        from .. import observe as _obs
        echo = _obs._is_automation_echo(intent, tools)
    except Exception:
        echo = False

    return {
        "kind": "codex",
        "title": title,
        "project": project,
        "start": ts_first.isoformat() if ts_first else None,
        "end": ts_last.isoformat() if ts_last else None,
        "duration_min": duration_min,
        "active_min": active_min,
        "intent": intent,
        "tools": dict(sorted(tools.items(), key=lambda kv: -kv[1])),
        "n_user_turns": n_user,
        "n_assistant_turns": n_assistant,
        "is_automation_echo": echo,
        "source": "codex",
    }


class CodexAgent(AgentPlatform):
    key = "codex"
    label = "Codex CLI"
    skill_kind = "~/.codex/prompts/<slug>.md（自定义 prompt / 斜杠命令）"

    def available(self) -> bool:
        return pathlib.Path(C.CODEX_HOME).exists()

    def collect_sessions(self, limit: int = 400) -> list:
        root = pathlib.Path(C.CODEX_HOME) / "sessions"
        if not root.exists():
            return []
        out = []
        try:
            files = sorted(root.rglob("*.jsonl"))
        except OSError:
            return []
        for path in files:
            try:
                s = _summarize_codex_file(path)
            except Exception as e:
                C.log(f"agents[codex]: 跳过坏会话 {path.name}: {e!r}")
                continue
            if not s or s.get("is_automation_echo"):
                continue
            if s.get("n_user_turns", 0) > 0 or s.get("tools"):
                out.append(s)
            if len(out) >= limit:
                break
        out.sort(key=lambda s: s.get("start") or "")
        return out

    def skills_root(self) -> "pathlib.Path | None":
        return pathlib.Path(C.CODEX_HOME) / "prompts"

    def skill_path(self, name: str) -> "pathlib.Path | None":
        return pathlib.Path(C.CODEX_HOME) / "prompts" / f"{slugify(name)}.md"
