#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""observe.collect_sessions 的回归测试：headless 剔除、时间窗、子会话排除、意图过滤。"""
from __future__ import annotations

import datetime as dt
import json
import os
import unittest

from distiller import config as C
from distiller import observe

from .util import TmpDataCase


def _events(session_id, ts, entrypoint="cli", text="帮我修个 bug", with_tool=True):
    out = [{"type": "user", "sessionId": session_id, "timestamp": ts,
            "entrypoint": entrypoint, "cwd": "/tmp/proj",
            "message": {"content": text}}]
    if with_tool:
        out.append({"type": "assistant", "sessionId": session_id, "timestamp": ts,
                    "entrypoint": entrypoint,
                    "message": {"content": [{"type": "tool_use", "name": "Bash"}]}})
    return out


class TestCollectSessions(TmpDataCase):
    def _write(self, relpath, events, mtime=None):
        p = C.CLAUDE_PROJECTS / relpath
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("\n".join(json.dumps(e, ensure_ascii=False) for e in events),
                     encoding="utf-8")
        if mtime is not None:
            os.utime(p, (mtime, mtime))
        return p

    def test_headless_sdk_sessions_excluded(self):
        now = C.now_utc().isoformat()
        self._write("proj/human.jsonl", _events("s-human", now, entrypoint="cli"))
        self._write("proj/desktop.jsonl", _events("s-desk", now, entrypoint="claude-desktop"))
        self._write("proj/judge.jsonl", _events("s-judge", now, entrypoint="sdk-cli"))
        self._write("proj/legacy.jsonl", _events("s-old-ver", now, entrypoint=None))  # 字段缺失保守视为真人
        got = {s["session_id"] for s in observe.collect_sessions(days=7)}
        self.assertEqual(got, {"s-human", "s-desk", "s-old-ver"})

    def test_window_by_end_timestamp(self):
        old = (C.now_utc() - dt.timedelta(days=30)).isoformat()
        # mtime 刚刚（绕过 mtime 预过滤），事件时间在窗外 → 仍应被 end 终判剔除
        self._write("proj/old.jsonl", _events("s-old", old))
        self.assertEqual(observe.collect_sessions(days=7), [])
        self.assertEqual(len(observe.collect_sessions(days=0)), 1)   # 0 = 不限

    def test_window_mtime_prefilter(self):
        old_dt = C.now_utc() - dt.timedelta(days=30)
        self._write("proj/old.jsonl", _events("s-old", old_dt.isoformat()),
                    mtime=old_dt.timestamp())
        self.assertEqual(observe.collect_sessions(days=7), [])

    def test_subagent_sessions_excluded(self):
        now = C.now_utc().isoformat()
        self._write("proj/subagents/sub.jsonl", _events("s-sub", now))
        self.assertEqual(observe.collect_sessions(days=7), [])

    def test_summary_shape(self):
        now = C.now_utc().isoformat()
        self._write("proj/a.jsonl", _events("s1", now))
        (s,) = observe.collect_sessions(days=7)
        self.assertEqual(s["project"], "proj")
        self.assertEqual(s["entrypoint"], "cli")
        self.assertFalse(s["is_headless"])
        self.assertEqual(s["tools"], {"Bash": 1})
        self.assertEqual(s["n_user_turns"], 1)
        self.assertIn("修个 bug", s["intent"])


if __name__ == "__main__":
    unittest.main()
