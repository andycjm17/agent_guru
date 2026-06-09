#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""config.py 纯函数与 JSON IO 的回归测试。"""
from __future__ import annotations

import datetime as dt
import os
import unittest
from unittest import mock

from distiller import config as C

from .util import TmpDataCase


class TestExtractJson(unittest.TestCase):
    def test_direct_object(self):
        self.assertEqual(C.extract_json('{"a": 1}'), {"a": 1})

    def test_direct_array(self):
        self.assertEqual(C.extract_json('[1, 2]'), [1, 2])

    def test_fenced_block(self):
        txt = '说明文字\n```json\n{"a": [1, 2]}\n```\n尾巴'
        self.assertEqual(C.extract_json(txt), {"a": [1, 2]})

    def test_balanced_scan_with_noise(self):
        txt = '前缀 {"a": 1, "b": {"c": 2}} 后缀'
        self.assertEqual(C.extract_json(txt), {"a": 1, "b": {"c": 2}})

    def test_braces_inside_strings(self):
        txt = '噪音 {"a": "}b{"} 噪音'
        self.assertEqual(C.extract_json(txt), {"a": "}b{"})

    def test_garbage_returns_none(self):
        self.assertIsNone(C.extract_json("纯文本，没有 JSON"))
        self.assertIsNone(C.extract_json(""))
        self.assertIsNone(C.extract_json(None))


class TestParseTs(unittest.TestCase):
    def test_z_suffix(self):
        d = C.parse_ts("2026-06-09T10:00:00Z")
        self.assertEqual(d, dt.datetime(2026, 6, 9, 10, 0, tzinfo=dt.timezone.utc))

    def test_naive_becomes_utc(self):
        d = C.parse_ts("2026-06-09T10:00:00")
        self.assertEqual(d.tzinfo, dt.timezone.utc)

    def test_invalid(self):
        self.assertIsNone(C.parse_ts("not-a-date"))
        self.assertIsNone(C.parse_ts(None))
        self.assertIsNone(C.parse_ts(""))

    def test_comparable_with_now_utc(self):
        self.assertLess(C.parse_ts("2000-01-01T00:00:00"), C.now_utc())


class TestAsNum(unittest.TestCase):
    def test_values(self):
        self.assertEqual(C.as_num("15"), 15.0)
        self.assertEqual(C.as_num(3), 3.0)
        self.assertEqual(C.as_num("15min"), 0.0)      # LLM 脏值降级
        self.assertEqual(C.as_num(None, default=7), 7)


class TestSlackMrkdwn(unittest.TestCase):
    def test_bold_link_heading_escape(self):
        out = C.to_slack_mrkdwn("# 标题\n**粗** [链](https://x.y/z) a&b<c>")
        self.assertIn("*粗*", out)
        self.assertIn("<https://x.y/z|链>", out)
        self.assertNotIn("#", out.splitlines()[0])
        self.assertIn("a&amp;b&lt;c&gt;", out)


class TestIntCfg(unittest.TestCase):
    def test_env_valid(self):
        with mock.patch.dict(os.environ, {"WD_UNITTEST_PORT": "9001"}):
            self.assertEqual(C._int_cfg("unittest_port", 7), 9001)

    def test_env_dirty_falls_back(self):
        with mock.patch.dict(os.environ, {"WD_UNITTEST_PORT": "abc"}):
            self.assertEqual(C._int_cfg("unittest_port", 7), 7)

    def test_unset_uses_default(self):
        self.assertEqual(C._int_cfg("unittest_port_missing", 42), 42)


class TestJsonIO(TmpDataCase):
    def test_save_load_roundtrip(self):
        p = C.DATA_DIR / "x" / "y.json"
        obj = {"中文": ["a", 1, {"k": None}]}
        C.save_json(p, obj)
        self.assertEqual(C.load_json(p), obj)
        # 原子写不留 .tmp 残骸
        self.assertEqual([f for f in p.parent.iterdir() if f.suffix == ".tmp"], [])

    def test_load_corrupt_returns_default(self):
        p = C.DATA_DIR / "bad.json"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("{broken", encoding="utf-8")
        self.assertEqual(C.load_json(p, default={"d": 1}), {"d": 1})

    def test_load_missing_returns_default(self):
        self.assertIsNone(C.load_json(C.DATA_DIR / "nope.json"))

    def test_jsonl_append_read_skips_bad_lines(self):
        p = C.DATA_DIR / "rows.jsonl"
        C.append_jsonl(p, {"a": 1})
        with p.open("a", encoding="utf-8") as f:
            f.write("不是 json\n\n")
        C.append_jsonl(p, {"b": 2})
        self.assertEqual(C.read_jsonl(p), [{"a": 1}, {"b": 2}])

    def test_read_jsonl_missing(self):
        self.assertEqual(C.read_jsonl(C.DATA_DIR / "nope.jsonl"), [])


if __name__ == "__main__":
    unittest.main()
