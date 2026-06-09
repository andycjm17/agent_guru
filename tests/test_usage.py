#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""usage.skill_usage 的回归测试：实测计数、子会话排除、时间窗。"""
from __future__ import annotations

import datetime as dt
import json
import unittest

from distiller import config as C
from distiller import usage

from .util import TmpDataCase


def _skill_event(skill, ts):
    return {"timestamp": ts,
            "message": {"content": [{"type": "tool_use", "name": "Skill",
                                     "input": {"skill": skill}}]}}


class TestSkillUsage(TmpDataCase):
    def _write_session(self, relpath, events):
        p = C.CLAUDE_PROJECTS / relpath
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("\n".join(json.dumps(e, ensure_ascii=False) for e in events),
                     encoding="utf-8")

    def test_counts_and_exclusions(self):
        now = C.now_utc().isoformat()
        other_tool = {"timestamp": now,
                      "message": {"content": [{"type": "tool_use", "name": "Bash", "input": {}}]}}
        self._write_session("projA/s1.jsonl",
                            [_skill_event("alpha", now), _skill_event("alpha", now),
                             _skill_event("beta", now), other_tool])
        self._write_session("subagents/s2.jsonl", [_skill_event("alpha", now)])   # 子会话不算
        out = usage.skill_usage(7)
        self.assertEqual(out["total"], 3)
        self.assertEqual(out["by_skill"], {"alpha": 2, "beta": 1})

    def test_window_excludes_old_events(self):
        old = (C.now_utc() - dt.timedelta(days=30)).isoformat()
        self._write_session("projA/s1.jsonl", [_skill_event("alpha", old)])
        self.assertEqual(usage.skill_usage(7)["total"], 0)
        self.assertEqual(usage.skill_usage(0)["total"], 1)   # days<=0 = 累计

    def test_missing_root(self):
        self.assertEqual(usage.skill_usage(7), {"total": 0, "by_skill": {}})


if __name__ == "__main__":
    unittest.main()
