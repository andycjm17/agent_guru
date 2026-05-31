#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
agents/claude_code.py — Claude Code 适配器

观察源：~/.claude/projects/**/*.jsonl（复用 observe.py 的低层扫描）
Skill 落地：~/.claude/skills/<name>/SKILL.md（Claude Code 原生 skill 形态）
"""
from __future__ import annotations

import pathlib

from .. import config as C
from .base import AgentPlatform


class ClaudeCode(AgentPlatform):
    key = "claude_code"
    label = "Claude Code"
    skill_kind = "~/.claude/skills/<name>/SKILL.md"

    def available(self) -> bool:
        return pathlib.Path(C.CLAUDE_PROJECTS).exists() or pathlib.Path(C.CLAUDE_SKILLS).exists()

    def collect_sessions(self) -> list:
        # 延迟导入打断循环：observe.build_digests 会回头调本注册表
        from .. import observe
        try:
            return observe.collect_sessions()
        except Exception as e:
            C.log(f"agents[claude_code]: 观察异常（忽略）: {e!r}")
            return []

    def skills_root(self) -> "pathlib.Path | None":
        return pathlib.Path(C.CLAUDE_SKILLS)

    def skill_path(self, name: str) -> "pathlib.Path | None":
        # name 即 skill 目录名（既有 skill 的目录名==frontmatter name，往返一致）
        safe = (name or "").strip().strip("/").split("/")[0]
        if not safe or safe in (".", "..") or "\\" in safe:
            return None   # 挡住目录穿越/空段（base._within_root 还有二道兜底）
        return pathlib.Path(C.CLAUDE_SKILLS) / safe / "SKILL.md"
