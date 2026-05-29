#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
doctor.py — 部署环境自检

在别人的机器上装好后跑一遍，确认依赖/鉴权/路径/配置都就绪，并清楚告知哪些功能可用、
哪些因缺配置而降级。不做任何写操作、不发 DM、不调 claude（除轻量 --version 探测）。

用法:
  python3 -m distiller.doctor
退出码：0 = 无硬性阻断（可能有降级告警）；1 = 有硬性缺失（核心功能不可用）。
"""
from __future__ import annotations

import sys
import pathlib

from . import config as C

OK, WARN, BAD = "✓", "⚠", "✗"

# bytedcli 安装命令（前置：它是飞书 DM/身份/文档的依赖）
BYTEDCLI_INSTALL = "npm install -g @bytedance-dev/bytedcli@latest --registry https://bnpm.byted.org"


def _check_cli(path: str, name: str) -> tuple[bool, str]:
    p = pathlib.Path(path)
    # path 可能是裸名（靠 PATH）；用 which 再确认一次
    import shutil
    resolved = path if p.is_absolute() and p.exists() else shutil.which(path)
    if not resolved:
        return False, f"{BAD} {name}: 未找到（{path}）"
    # 轻量 --version 探测（短超时，失败不致命）
    try:
        r = C.run([resolved, "--version"], timeout=15)
        ver = (r.stdout or r.stderr or "").strip().splitlines()[0][:40] if (r.stdout or r.stderr) else "?"
    except Exception:
        ver = "(--version 无响应)"
    return True, f"{OK} {name}: {resolved}  [{ver}]"


def main(argv=None) -> int:
    hard_fail = False
    lines = ["workflow-distiller · 环境自检", "=" * 40]

    # 1) Python 版本
    v = sys.version_info
    if (v.major, v.minor) >= (3, 9):
        lines.append(f"{OK} Python {v.major}.{v.minor}.{v.micro}")
    else:
        lines.append(f"{BAD} Python {v.major}.{v.minor}（需 ≥ 3.9）")
        hard_fail = True

    # 2) 运行时工具链（node/npm —— bytedcli 经 npm 安装）
    lines.append("")
    lines.append("运行时工具链：")
    node_ok, msg = _check_cli("node", "node"); lines.append("  " + msg)
    npm_ok, msg = _check_cli("npm", "npm"); lines.append("  " + msg)

    # 3) 外部 CLI
    lines.append("")
    lines.append("外部 CLI：")
    claude_ok, msg = _check_cli(C.CLAUDE, "claude"); lines.append("  " + msg)
    byted_ok, msg = _check_cli(C.BYTEDCLI, "bytedcli"); lines.append("  " + msg)
    if not byted_ok:
        hard_fail = True  # bytedcli = 飞书 + Aime 后端的依赖
        if npm_ok:
            lines.append(f"     → 安装: {BYTEDCLI_INSTALL}")
        else:
            lines.append(f"     → 先装 Node.js/npm，再装 bytedcli: {BYTEDCLI_INSTALL}")
    lark_ok, msg = _check_cli(C.LARK_CLI, "lark-cli"); lines.append("  " + msg)
    if not lark_ok and byted_ok:
        lines.append("     ⚠ 缺 lark-cli：Lark 文档读写不可用（一般随 bytedcli 飞书命令就绪）")

    # 3b) LLM 后端（解绑 Claude Code：claude / aime / mira 任一可用即可蒸馏）
    lines.append("")
    lines.append("LLM 后端（蒸馏/周报引擎，任一可用即可）：")
    providers = C.llm_providers_available()
    if providers:
        active = C.active_provider()
        names = {"claude": "Claude Code", "aime": "字节 AIME (bytedcli)", "mira": "Mira/网关 (mira_endpoint)"}
        for p in providers:
            mark = "★当前" if p == active else ""
            lines.append(f"  {OK} {names.get(p, p)} {mark}")
        if not claude_ok:
            lines.append(f"     · 未装 claude，自动使用 {names.get(active, active)} —— 无需 Claude Code")
    else:
        lines.append(f"  {BAD} 无可用 LLM 后端：装 claude 或 bytedcli(含 AIME) 或配 mira_endpoint")
        hard_fail = True

    # 3) 语料目录（Claude Code 会话 或 Cursor 会话，任一即可）
    lines.append("")
    lines.append("观察语料（任一即可）：")
    proj = pathlib.Path(C.CLAUDE_PROJECTS)
    claude_sessions = sum(1 for _ in proj.rglob("*.jsonl")) if proj.exists() else 0
    if proj.exists():
        lines.append(f"  {OK if claude_sessions else WARN} Claude session 目录: {proj}（{claude_sessions} 个 jsonl）")
    else:
        lines.append(f"  {WARN} 无 Claude session 目录: {proj}")
    # Cursor 源
    cursor_n = 0
    try:
        from . import cursor as _cur
        if _cur.cursor_available():
            cursor_n = len(_cur.collect_cursor_sessions())
            lines.append(f"  {OK if cursor_n else WARN} Cursor 会话: 已检测到 Cursor（{cursor_n} 条会话）")
        else:
            lines.append(f"  {WARN} Cursor 会话: 未检测到 Cursor 安装（可选）")
    except Exception:
        lines.append(f"  {WARN} Cursor 会话: 读取异常（已忽略）")
    if claude_sessions == 0 and cursor_n == 0:
        lines.append(f"  {BAD} 无任何可观察会话（Claude/Cursor 都没有）——先用其中之一干点活")
        hard_fail = True
    skills = pathlib.Path(C.CLAUDE_SKILLS)
    lines.append(f"  {OK if skills.exists() else WARN} Skills 目录: {skills}"
                 + ("" if skills.exists() else "（无，UI Skills 区将为空）"))
    meet = pathlib.Path(C.MEETING_STATE)
    lines.append(f"  {OK if meet.exists() else WARN} 会议语料(可选): {meet}"
                 + ("" if meet.exists() else "（无，跳过会议旁路）"))

    # 4) 飞书身份 / 功能可用性（零配置：身份自动探测、周报文档自动创建）
    lines.append("")
    lines.append("飞书身份与功能（零配置）：")
    open_id = C.resolve_lark_user_id()   # config → 缓存 → bytedcli auth status 自动探测
    if open_id:
        src = "config" if C.LARK_USER_ID else "自动探测/缓存"
        cache = C.load_json(C.IDENTITY_CACHE, default={}) or {}
        who = cache.get("user_name") or "本人"
        lines.append(f"  {OK} 飞书身份: {who}（{open_id[:14]}…，来源 {src}）")
        lines.append(f"  {OK} 飞书 DM（retro/weekly 通知）: 可用")
    else:
        lines.append(f"  {BAD} 飞书身份: 无法探测 open_id —— 请先完成 `bytedcli lark auth login`")
        lines.append(f"  {WARN} 飞书 DM: 不可用（身份未就绪）")
        hard_fail = True   # 这正是用户约定的前置：飞书 + bytedcli 授权
    lines.append(f"  {OK} 周报推送（weekly --approve）: "
                 + (f"已配文档 {C.WEEKLY_DOC_URL[:40]}…" if C.WEEKLY_DOC_URL
                    else "首次自动创建周报文档（无需预先配置）"))
    lines.append(f"  {OK if C.TRACKED_PEOPLE else WARN} 单列跟进人: "
                 + ("、".join(C.TRACKED_PEOPLE) if C.TRACKED_PEOPLE else "未配 → 周报不输出该节（可选）"))
    cfg_file = C.PROJECT_ROOT / "config.local.json"
    lines.append(f"  {OK if cfg_file.exists() else WARN} config.local.json: "
                 + (str(cfg_file) if cfg_file.exists() else "无（零配置可跑；如需自定义可复制 example）"))

    # 5) 可写目录
    lines.append("")
    lines.append("可写性：")
    for d in (C.DATA_DIR, C.STATE_DIR, C.LOG_DIR):
        try:
            d.mkdir(parents=True, exist_ok=True)
            probe = d / ".doctor_probe"
            probe.write_text("x", encoding="utf-8")
            probe.unlink()
            lines.append(f"  {OK} {d} 可写")
        except Exception as e:
            lines.append(f"  {BAD} {d} 不可写: {e}")
            hard_fail = True

    # 总结
    lines.append("=" * 40)
    if hard_fail:
        lines.append(f"{BAD} 有硬性缺失，核心功能不可用——见上方 {BAD} 项。")
    else:
        lines.append(f"{OK} 核心就绪。{WARN} 项为按配置的功能降级，可选补齐。")
        lines.append("下一步：python3 -m distiller.pipeline  然后  python3 -m distiller.server")
    print("\n".join(lines))
    return 1 if hard_fail else 0


if __name__ == "__main__":
    sys.exit(main())
