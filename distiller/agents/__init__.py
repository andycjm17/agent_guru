#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
agents/ — 可插拔 Agent 平台注册表（观察源 + Skill 落地目标）

解绑 Claude Code：观察哪些平台、Skill 落地到哪个平台，全部由 config.local.json 的
sources / skill_target 驱动（缺省 = 自动探测所有可用平台）。一律走 C.live_cfg，
故 setup 向导 / UI 设置面板改完即时生效，server 长驻无需重启。
"""
from __future__ import annotations

from .. import config as C
from .base import AgentPlatform, slugify, parse_frontmatter
from .claude_code import ClaudeCode
from .cursor import CursorAgent
from .codex import CodexAgent

# 顺序即偏好（默认 skill 落地优先 Claude Code）
_REGISTRY = [ClaudeCode(), CursorAgent(), CodexAgent()]


def all_platforms() -> list:
    return list(_REGISTRY)


def by_key(key: str):
    for p in _REGISTRY:
        if p.key == key:
            return p
    return None


def available_platforms() -> list:
    out = []
    for p in _REGISTRY:
        try:
            if p.available():
                out.append(p)
        except Exception:
            pass
    return out


def enabled_platforms() -> list:
    """启用的观察源：config sources 显式列表（按注册顺序）→ 否则自动探测所有可用。"""
    sel = C.live_cfg("sources", None)
    if isinstance(sel, list) and sel:
        return [p for p in _REGISTRY if p.key in sel]
    return available_platforms()


def skill_target_platform():
    """「应用到生产」默认落到哪个平台：config skill_target → 首个可写的启用平台 → 首个可写平台。"""
    k = C.live_cfg("skill_target", "")
    if k:
        p = by_key(k)
        if p is not None:
            return p
    for pool in (enabled_platforms(), _REGISTRY):
        for p in pool:
            try:
                if p.skills_root() is not None:
                    return p
            except Exception:
                continue
    return _REGISTRY[0]
