#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""server.py 的回归测试：CSRF 来源校验、自主度 key 与写盘。"""
from __future__ import annotations

import unittest

from distiller import config as C
from distiller import server

from .util import TmpDataCase


def _handler_with_origin(origin):
    h = server.Handler.__new__(server.Handler)   # 不建真实 socket，仅测纯逻辑
    h.headers = {} if origin is None else {"Origin": origin}
    return h


class TestOriginOk(unittest.TestCase):
    def test_no_origin_allowed(self):
        self.assertTrue(_handler_with_origin(None)._origin_ok())

    def test_local_origins_allowed(self):
        for o in ("http://127.0.0.1:8787", "http://localhost:8787", "http://[::1]:8787"):
            self.assertTrue(_handler_with_origin(o)._origin_ok(), o)

    def test_cross_site_rejected(self):
        self.assertFalse(_handler_with_origin("https://evil.example")._origin_ok())

    def test_bind_address_is_not_a_browser_origin(self):
        # 回归：0.0.0.0 是服务端绑定地址、不是合法浏览器来源，不应放行
        self.assertFalse(_handler_with_origin("http://0.0.0.0:8787")._origin_ok())

    def test_garbage_origin_rejected(self):
        self.assertFalse(_handler_with_origin("not a url")._origin_ok())


class TestAutonomy(TmpDataCase):
    def test_autonomy_key_namespacing(self):
        self.assertEqual(server._autonomy_key("claude_code", "foo"), "foo")   # 向后兼容
        self.assertEqual(server._autonomy_key("cursor", "foo"), "cursor:foo")

    def test_set_skill_autonomy_roundtrip(self):
        self.assertTrue(server.set_skill_autonomy("cursor", "foo", "draft"))
        cfg = C.load_json(C.SKILLS_CONFIG)
        self.assertEqual(cfg["cursor:foo"]["autonomy"], "draft")

    def test_invalid_level_rejected(self):
        self.assertFalse(server.set_skill_autonomy("cursor", "foo", "yolo"))
        self.assertIsNone(C.load_json(C.SKILLS_CONFIG))


if __name__ == "__main__":
    unittest.main()
