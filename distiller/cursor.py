#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
cursor.py — 可选观察源：读取 Cursor 的会话历史（与 Claude Code 的 ~/.claude/projects 并列）

让本工具不强绑定 Claude Code——Cursor 用户的 AI 会话也能被观察、蒸馏。
Cursor 把会话存在 SQLite：<User>/globalStorage/state.vscdb 与 workspaceStorage/*/state.vscdb，
表 cursorDiskKV（key=composerData:<id> / bubbleId:<cid>:<bid>）与 ItemTable（composer.composerData 等）。
该格式随 Cursor 版本变化，且只读——本模块全程 best-effort + try/except：任何缺失/异常即返回 []，
绝不影响主流程。产出与 Claude session 同形的紧凑摘要（kind='cursor'）。
"""
from __future__ import annotations

import json
import sqlite3
import datetime as dt
import pathlib

from . import config as C


def _storage_bases() -> list:
    cfg = C._cfg("cursor_storage_dir")
    if cfg:
        return [pathlib.Path(cfg)]
    home = C.HOME
    cands = [
        home / "Library" / "Application Support" / "Cursor" / "User",  # macOS
        home / ".config" / "Cursor" / "User",                          # Linux
        home / "AppData" / "Roaming" / "Cursor" / "User",              # Windows
    ]
    return [p for p in cands if p.exists()]


def cursor_available() -> bool:
    return bool(_storage_bases())


def _dbs() -> list:
    out = []
    for base in _storage_bases():
        g = base / "globalStorage" / "state.vscdb"
        if g.exists():
            out.append(g)
        ws = base / "workspaceStorage"
        if ws.exists():
            try:
                out.extend(sorted(ws.glob("*/state.vscdb")))
            except Exception:
                pass
    return out


def _epoch_iso(ms):
    try:
        return dt.datetime.fromtimestamp(float(ms) / 1000.0, dt.timezone.utc).isoformat()
    except Exception:
        return None


def _truncate(s: str, n: int = 200) -> str:
    s = " ".join((s or "").split())
    return s if len(s) <= n else s[:n] + "…"


def _bubble_texts(cur, composer_id: str, headers: list):
    """新版 Cursor：消息在 bubbleId:<cid>:<bid> 行里；按 headers 顺序取 (type,text)。"""
    msgs = []
    for h in headers or []:
        bid = h.get("bubbleId") if isinstance(h, dict) else None
        if not bid:
            continue
        try:
            cur.execute("SELECT value FROM cursorDiskKV WHERE key=?", (f"bubbleId:{composer_id}:{bid}",))
            row = cur.fetchone()
            if not row:
                continue
            b = json.loads(row[0])
            msgs.append((b.get("type"), (b.get("text") or "").strip()))
        except Exception:
            continue
    return msgs


def _digest_from_composer(comp: dict, cur=None) -> dict | None:
    if not isinstance(comp, dict):
        return None
    name = (comp.get("name") or "").strip()
    cid = comp.get("composerId") or comp.get("id") or ""
    # 消息：老版内联 conversation；新版走 bubbleId
    conv = comp.get("conversation") or []
    msgs = [(m.get("type"), (m.get("text") or "").strip()) for m in conv if isinstance(m, dict)]
    if not msgs and cur is not None and comp.get("fullConversationHeadersOnly"):
        msgs = _bubble_texts(cur, cid, comp.get("fullConversationHeadersOnly"))
    user_msgs = [t for ty, t in msgs if ty == 1 and t]
    ai_n = sum(1 for ty, t in msgs if ty == 2)
    intents = [_truncate(t) for t in user_msgs[:2]]

    created = comp.get("createdAt")
    updated = comp.get("lastUpdatedAt") or created
    start = _epoch_iso(created) if isinstance(created, (int, float)) else None
    end = _epoch_iso(updated) if isinstance(updated, (int, float)) else None
    dur = None
    if isinstance(created, (int, float)) and isinstance(updated, (int, float)) and updated >= created:
        dur = round((updated - created) / 60000.0, 1)

    title = name or (intents[0][:40] if intents else "(Cursor 会话)")
    if not (name or intents or user_msgs):
        return None   # 完全空的占位会话，跳过
    return {
        "kind": "cursor",
        "title": title,
        "project": comp.get("projectName") or None,
        "start": start, "end": end,
        "duration_min": dur, "active_min": dur,
        "intent": " ／ ".join(intents),
        "tools": {},   # Cursor 不以同构方式暴露工具调用
        "n_user_turns": len(user_msgs),
        "n_assistant_turns": ai_n,
        "is_automation_echo": False,
        "source": "cursor",
    }


def collect_cursor_sessions(limit: int = 300) -> list:
    """扫所有 Cursor state.vscdb，抽 composer 会话 → 同形摘要。失败静默返回已得部分。"""
    out = []
    try:
        dbs = _dbs()
    except Exception:
        return out
    for db in dbs:
        try:
            con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
            cur = con.cursor()
        except Exception:
            continue
        try:
            # 1) cursorDiskKV: composerData:<id>
            try:
                cur.execute("SELECT value FROM cursorDiskKV WHERE key LIKE 'composerData:%'")
                for (v,) in cur.fetchall():
                    try:
                        d = _digest_from_composer(json.loads(v), cur)
                        if d:
                            out.append(d)
                    except Exception:
                        continue
            except Exception:
                pass
            # 2) ItemTable: composer.composerData -> allComposers（老布局）
            try:
                cur.execute("SELECT value FROM ItemTable WHERE key='composer.composerData'")
                row = cur.fetchone()
                if row:
                    for comp in (json.loads(row[0]).get("allComposers") or []):
                        try:
                            d = _digest_from_composer(comp, cur)
                            if d:
                                out.append(d)
                        except Exception:
                            continue
            except Exception:
                pass
        finally:
            try:
                con.close()
            except Exception:
                pass
        if len(out) >= limit:
            break

    # 去重（title+start）
    seen, uniq = set(), []
    for d in out:
        key = (d.get("title"), d.get("start"))
        if key in seen:
            continue
        seen.add(key)
        uniq.append(d)
    uniq.sort(key=lambda s: s.get("start") or "")
    return uniq[:limit]
