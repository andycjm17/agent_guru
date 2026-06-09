#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""agents/base.py 的回归测试：slug、frontmatter 解析、skill 落地（备份/原子写/防穿越）。"""
from __future__ import annotations

import pathlib
import unittest

from distiller import config as C
from distiller.agents import base

from .util import TmpDataCase


class TmpPlatform(base.AgentPlatform):
    key = "tmp"
    label = "Tmp"

    def __init__(self, root):
        self._root = pathlib.Path(root)

    def available(self):
        return True

    def skills_root(self):
        return self._root

    def skill_path(self, name):
        return self._root / base.slugify(name) / "SKILL.md"


class RawNamePlatform(TmpPlatform):
    """不收敛 name 的平台——专测 _within_root 对目录穿越的拦截。"""

    def skill_path(self, name):
        return self._root / name / "SKILL.md"


SKILL_MD = """---
name: demo-skill
description: >
  第一行
  第二行
---
正文
"""


class TestSlugify(unittest.TestCase):
    def test_ascii_kebab(self):
        self.assertEqual(base.slugify("Hello,  World!"), "hello-world")

    def test_non_ascii_falls_back_to_hash(self):
        s = base.slugify("会后速递")
        self.assertTrue(s.startswith("skill-"))
        self.assertEqual(s, base.slugify("会后速递"))          # 确定性
        self.assertNotEqual(s, base.slugify("另一个名字"))

    def test_length_cap(self):
        self.assertLessEqual(len(base.slugify("x" * 200)), 60)


class TestParseFrontmatter(unittest.TestCase):
    def test_simple(self):
        fm = base.parse_frontmatter("---\nname: a\ndescription: b\n---\nbody")
        self.assertEqual(fm, {"name": "a", "description": "b"})

    def test_folded_description(self):
        fm = base.parse_frontmatter(SKILL_MD)
        self.assertEqual(fm["name"], "demo-skill")
        self.assertEqual(fm["description"], "第一行 第二行")

    def test_no_frontmatter(self):
        self.assertEqual(base.parse_frontmatter("just text"), {})
        self.assertEqual(base.parse_frontmatter(""), {})


class TestSkillIO(TmpDataCase):
    def setUp(self):
        super().setUp()
        self.plat = TmpPlatform(self.tmp / "skills")

    def test_install_read_roundtrip(self):
        res = self.plat.install_skill("My Skill", SKILL_MD)
        self.assertTrue(res["ok"], res)
        self.assertIsNone(res["backup"])
        got = self.plat.read_skill("My Skill")
        self.assertEqual(got["content"], SKILL_MD)
        self.assertEqual(self.plat.canonical_name("My Skill"), "my-skill")

    def test_overwrite_backs_up_old_version(self):
        self.plat.install_skill("s", "v1")
        res = self.plat.install_skill("s", "v2")
        self.assertTrue(res["ok"], res)
        backup = pathlib.Path(res["backup"])
        self.assertTrue(str(backup).startswith(str(C.BACKUP_DIR)))
        self.assertEqual(backup.read_text(encoding="utf-8"), "v1")
        self.assertEqual(self.plat.read_skill("s")["content"], "v2")

    def test_list_skills_reads_frontmatter(self):
        self.plat.install_skill("demo skill", SKILL_MD)
        items = self.plat.list_skills()
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["name"], "demo-skill")
        self.assertEqual(items[0]["display"], "demo-skill")
        self.assertIn("第一行", items[0]["description"])

    def test_traversal_install_rejected(self):
        evil = RawNamePlatform(self.tmp / "skills")
        res = evil.install_skill("../escape", "x")
        self.assertFalse(res["ok"])
        self.assertNotIn("ok-path", res)
        self.assertFalse((self.tmp / "escape").exists())

    def test_traversal_read_rejected(self):
        outside = self.tmp / "outside" / "SKILL.md"
        outside.parent.mkdir(parents=True)
        outside.write_text("secret", encoding="utf-8")
        evil = RawNamePlatform(self.tmp / "skills")
        self.assertIsNone(evil.read_skill("../outside"))


if __name__ == "__main__":
    unittest.main()
