#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
agents/cursor.py — Cursor 适配器

观察源：Cursor 的 state.vscdb（复用顶层 cursor.py 的 SQLite 解析）
Skill 落地：.cursor/rules/<slug>.mdc（项目级 Project Rule，带 description/globs/alwaysApply frontmatter）

注意（据官方文档调研）：Cursor 没有「全局 ~/.cursor/rules 目录」——用户级 rule 只存在 state.vscdb，
无法用文件写入生效。所以本适配器的 skill 落地是「写一个 .mdc 到约定目录」：
  - config.local.json 配 cursor_rules_dir → 写那里（推荐指向某个项目的 .cursor/rules）
  - 未配 → 退到 ~/.cursor/rules（best-effort：Cursor 当前不自动加载全局，需你手工 symlink 进项目）
UI/doctor 会把这条 best-effort 说明透传给用户，不假装它一定全局生效。
"""
from __future__ import annotations

import pathlib

from .. import config as C
from .base import AgentPlatform, slugify


class CursorAgent(AgentPlatform):
    key = "cursor"
    label = "Cursor"
    skill_kind = ".cursor/rules/<slug>.mdc（Project Rule）"
    skill_note = ("Cursor 无全局 rules 目录；默认写 ~/.cursor/rules 为 best-effort，"
                  "建议在 config 配 cursor_rules_dir 指向某项目的 .cursor/rules 以确保生效。")

    def available(self) -> bool:
        try:
            from .. import cursor as _cur
            if _cur.cursor_available():
                return True
        except Exception:
            pass
        return (C.HOME / ".cursor").exists()

    def collect_sessions(self) -> list:
        if str(C.live_cfg("cursor_enabled", "auto")).lower() in ("0", "false", "off", "no"):
            return []
        try:
            from .. import cursor as _cur
            return _cur.collect_cursor_sessions()
        except Exception as e:
            C.log(f"agents[cursor]: 观察异常（忽略）: {e!r}")
            return []

    def _rules_dir(self) -> pathlib.Path:
        d = C.live_cfg("cursor_rules_dir", "") or C.CURSOR_RULES_DIR
        return pathlib.Path(d) if d else (C.HOME / ".cursor" / "rules")

    def skills_root(self) -> "pathlib.Path | None":
        return self._rules_dir()

    def skill_path(self, name: str) -> "pathlib.Path | None":
        slug = slugify(name)
        return self._rules_dir() / f"{slug}.mdc"
