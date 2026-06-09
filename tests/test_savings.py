#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""savings.py 的回归测试：记账、窗口汇总、punchline、reconcile 幂等。"""
from __future__ import annotations

import datetime as dt
import unittest

from distiller import config as C
from distiller import savings as S

from .util import TmpDataCase


class TestPunchline(unittest.TestCase):
    def test_near_zero(self):
        self.assertIn("净省 ~0", S.punchline(0.4))

    def test_positive_anchored(self):
        out = S.punchline(120)
        self.assertIn("净省 ~2.0h", out)
        self.assertIn("4 个 30min 会", out)
        self.assertIn("2 顿午饭", out)

    def test_small_positive_no_anchor(self):
        out = S.punchline(20)
        self.assertIn("净省", out)
        self.assertNotIn("≈", out)   # 不足 1 个会，不报会塌成 0 的锚点

    def test_negative(self):
        out = S.punchline(-90)
        self.assertIn("净亏", out)
        self.assertIn("倒贴 3 个", out)


class TestLedger(TmpDataCase):
    def test_record_net(self):
        e = S.record("wf", 15, 1, note="n")
        self.assertEqual(e["net_min"], 14.0)
        rows = C.read_jsonl(C.SAVINGS_LEDGER)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["workflow"], "wf")

    def test_summary_window(self):
        old = (C.now_utc() - dt.timedelta(days=30)).isoformat()
        S.record("old", 60, 0, ts=old)
        S.record("new", 30, 5)
        s7 = S.summary(7)
        self.assertEqual(s7["n_runs"], 1)
        self.assertEqual(s7["net_min"], 25.0)
        self.assertEqual(s7["by_workflow"], {"new": 25.0})
        s_all = S.summary(0)
        self.assertEqual(s_all["n_runs"], 2)
        self.assertEqual(s_all["net_min"], 85.0)

    def test_summary_skips_dirty_rows(self):
        C.append_jsonl(C.SAVINGS_LEDGER, {"ts": "坏时间戳", "est_saved_min": 99})
        S.record("ok", 10, 0)
        self.assertEqual(S.summary(7)["n_runs"], 1)

    def test_reconcile_idempotent(self):
        C.save_json(C.MEETING_STATE, {
            "tok1": {"status": "sent", "title": "周会", "at": C.now_utc().isoformat()},
            "tok2": {"status": "skipped", "title": "略过"},
            "tok3": "非法条目",
        })
        r1 = S.reconcile()
        self.assertEqual(r1["added"], 1)
        r2 = S.reconcile()
        self.assertEqual(r2["added"], 0)
        rows = C.read_jsonl(C.SAVINGS_LEDGER)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["src_key"], "meeting:tok1")

    def test_reconcile_missing_source(self):
        self.assertEqual(S.reconcile()["added"], 0)


if __name__ == "__main__":
    unittest.main()
