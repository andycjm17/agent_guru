#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""distill._merge_maps 的回归测试：跨批同名工作流合并的全部口径。"""
from __future__ import annotations

import unittest

from distiller.distill import _merge_maps


class TestMergeMaps(unittest.TestCase):
    def test_merge_same_name(self):
        m1 = {"headline": "h1", "workflows": [{
            "name": "A", "n_observed": 2, "instances": ["s1", "s2"],
            "steps": [{"desc": "d1", "bucket": "automate", "confidence": 0.5},
                      {"bucket": "human"}],                       # 缺 desc：应原样保留
        }]}
        m2 = {"headline": "h2", "workflows": [
            {"name": "A", "n_observed": 1, "instances": ["s2", "s3"],
             "steps": [{"desc": "d1", "bucket": "automate", "confidence": 0.9}]},
            {"name": "B", "n_observed": 1, "instances": [], "steps": []},
        ]}
        out = _merge_maps([m1, m2])
        self.assertEqual(out["headline"], "h1")                   # 取首个非空
        self.assertEqual([w["name"] for w in out["workflows"]], ["A", "B"])
        a = out["workflows"][0]
        self.assertEqual(a["instances"], ["s1", "s2", "s3"])      # 并集保序去重
        d1 = [s for s in a["steps"] if s.get("desc") == "d1"]
        self.assertEqual(len(d1), 1)
        self.assertEqual(d1[0]["confidence"], 0.9)                # 同 desc 保高置信
        self.assertEqual(len([s for s in a["steps"] if not s.get("desc")]), 1)
        self.assertEqual(a["n_observed"], 3)                      # max(并集实例数, 两批之和)

    def test_dirty_n_observed_and_confidence(self):
        m1 = {"workflows": [{"name": "A", "n_observed": "5次", "instances": [],
                             "steps": [{"desc": "d", "confidence": 0.5}]}]}
        m2 = {"workflows": [{"name": "A", "n_observed": 2, "instances": [],
                             "steps": [{"desc": "d", "confidence": "high"}]}]}
        a = _merge_maps([m1, m2])["workflows"][0]
        self.assertEqual(a["n_observed"], 2)            # "5次" 降级为 0
        self.assertEqual(a["steps"][0]["confidence"], 0.5)   # "high" 降级为 0，不抢占

    def test_skips_empty_and_unnamed(self):
        out = _merge_maps([None, {}, {"workflows": [{"name": ""}]}])
        self.assertEqual(out, {"headline": "", "workflows": []})


if __name__ == "__main__":
    unittest.main()
