#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
agents/base.py — Agent 平台适配器基类

一个「Agent 平台」同时是两件事：
  1. 观察源：collect_sessions() 产出与 observe 同形的紧凑会话摘要
  2. Skill 落地目标：list/read/install_skill() 把蒸馏出的 Skill 真正写进该平台的生效位置

子类只需声明 key/label，并实现 available() / collect_sessions() / skills_root() / skill_path()
（以及可选的 list_skills/read_skill 重载）。install_skill/read_skill 的「备份后原子写」「读全文」
逻辑由基类统一提供，确保各平台的「应用到生产」都先备份旧版、可回滚。
"""
from __future__ import annotations

import hashlib
import pathlib
import re

from .. import config as C


def slugify(name: str, fallback: str = "skill") -> str:
    """生成 ascii-kebab 文件名 slug。中文等无 ascii 词的名字 → fallback-<hash8>，保证可作文件名。"""
    s = re.sub(r"[^a-zA-Z0-9]+", "-", (name or "").strip().lower()).strip("-")
    if not s:
        s = f"{fallback}-{hashlib.md5((name or '').encode('utf-8')).hexdigest()[:8]}"
    return s[:60]


def parse_frontmatter(text: str) -> dict:
    """从 SKILL.md / .mdc 抠 YAML frontmatter 的 name / description（不引第三方 yaml）。
    支持 description 折叠块（`description: >` 后跟缩进多行）。"""
    lines = (text or "").splitlines()
    if not lines or lines[0].strip() != "---":
        return {}
    fm: list = []
    for ln in lines[1:]:
        if ln.strip() == "---":
            break
        fm.append(ln)
    out = {"name": "", "description": ""}
    i = 0
    while i < len(fm):
        ln = fm[i]
        if ln.startswith("name:"):
            out["name"] = ln.split(":", 1)[1].strip()
        elif ln.startswith("description:"):
            val = ln.split(":", 1)[1].strip()
            if val in (">", "|", ">-", "|-", "", ">+", "|+"):
                buf = []
                j = i + 1
                while j < len(fm) and (fm[j].startswith("  ") or fm[j].strip() == ""):
                    buf.append(fm[j].strip())
                    j += 1
                out["description"] = " ".join(x for x in buf if x)
                i = j
                continue
            else:
                out["description"] = val
        i += 1
    return out


class AgentPlatform:
    key = "base"
    label = "Base"
    skill_kind = "SKILL.md"        # 该平台 skill 文件的人类可读说明（doctor/UI 展示）
    skill_note = ""                # 落地注意事项（如 Cursor 全局是 best-effort）

    # ---- 可用性 / 观察 ----
    def available(self) -> bool:
        return False

    def collect_sessions(self) -> list:
        """返回与 observe.summarize_session 同形的会话摘要列表。失败应自行兜底为 []。"""
        return []

    # ---- skill 落地 ----
    def skills_root(self) -> "pathlib.Path | None":
        """该平台 skill 的根目录；None = 不支持 skill 落地。"""
        return None

    def skill_path(self, name: str) -> "pathlib.Path | None":
        """给定 skill 标识，返回它在本平台的落地文件路径。"""
        return None

    def canonical_name(self, name: str) -> str:
        """落地后 list_skills 会用什么标识来回指这个 skill（保证自主度 key 与列表往返一致）。
        通用推断：SKILL.md → 取父目录名（Claude）；其余 → 取文件名 stem（Cursor/Codex 的 slug）。"""
        p = self.skill_path(name)
        if p is None:
            return (name or "").strip()
        return p.parent.name if p.name.upper().startswith("SKILL") else p.stem

    def list_skills(self) -> list:
        """枚举已落地的 skill：[{name, display, description, path}]。默认按 skills_root 扫。子类可重载。"""
        root = self.skills_root()
        out = []
        if not root or not root.exists():
            return out
        try:
            entries = sorted(root.iterdir())
        except OSError:
            return out
        for d in entries:
            sf = self.skill_path(d.name) if d.is_dir() else d
            try:
                if sf and sf.exists():
                    fm = parse_frontmatter(sf.read_text(encoding="utf-8", errors="replace"))
                    name = d.name if d.is_dir() else d.stem
                    out.append({
                        "name": name,
                        "display": fm.get("name") or name,
                        "description": (fm.get("description") or "")[:300],
                        "path": str(sf),
                    })
            except OSError:
                continue
        return out

    def _within_root(self, p) -> bool:
        """防目录穿越：确认落地/读取路径 resolve 后仍在 skills_root 内（挡住 name='..' 之类逃逸）。"""
        root = self.skills_root()
        if root is None or p is None:
            return False
        try:
            p.resolve().relative_to(root.resolve())
            return True
        except (ValueError, OSError):
            return False

    def read_skill(self, name: str) -> "dict | None":
        p = self.skill_path(name)
        if p and self._within_root(p) and p.exists():
            try:
                return {"name": name, "platform": self.key, "path": str(p),
                        "content": p.read_text(encoding="utf-8", errors="replace")}
            except OSError:
                return None
        return None

    def install_skill(self, name: str, content: str) -> dict:
        """「应用到生产」：备份旧版 → 原子写新版到本平台生效位置。返回 {ok, path, backup, error?}。"""
        p = self.skill_path(name)
        if p is None:
            return {"ok": False, "error": f"{self.label} 不支持 skill 落地或名字非法"}
        if not self._within_root(p):
            return {"ok": False, "error": f"非法 skill 名（疑似目录穿越）: {name!r}"}
        try:
            p.parent.mkdir(parents=True, exist_ok=True)
            backup = C.backup_file(p) if p.exists() else None
            tmp = p.with_suffix(p.suffix + ".tmp")
            tmp.write_text(content, encoding="utf-8")
            tmp.replace(p)
        except OSError as e:
            return {"ok": False, "error": f"写入失败: {e}"}
        C.log(f"agents[{self.key}]: 落地 skill {name} → {p}" + (f"（旧版备份 {backup.name}）" if backup else ""))
        return {"ok": True, "path": str(p), "backup": (str(backup) if backup else None)}
