#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
setup.py — 首次平台选择向导（解绑 Claude Code + 飞书）

探测本机可用的 Agent 平台（Claude Code / Cursor / Codex）与通知渠道（飞书 / 本地 / Slack），
让你勾选常用的，写回 config.local.json。UI 的「⚙ 设置」面板是同款能力，二选一即可。

用法:
  python -m distiller.setup            # 交互向导
  python -m distiller.setup --print    # 只打印探测结果，不改配置
  python -m distiller.setup --auto     # 不交互，直接按「全部可用」写入（CI/无人值守）
"""
from __future__ import annotations

import sys

from . import config as C
from . import agents as A
from . import sinks as K

OK, NO = "✓", "·"


def _detect_lines() -> list:
    lines = ["探测结果：", "  观察源（Agent 平台）:"]
    for p in A.all_platforms():
        try:
            av = p.available()
        except Exception:
            av = False
        lines.append(f"    {OK if av else NO} {p.label}  —  skill 落地：{p.skill_kind}")
    lines.append("  通知 / 输出渠道（sink）:")
    for s in K.all_sinks():
        try:
            av = s.available()
        except Exception:
            av = False
        lines.append(f"    {OK if av else NO} {s.label}{'' if av else '（未配置/不可用）'}")
    return lines


def _ask_multi(prompt: str, options: list, default_keys: list) -> list:
    """options=[(key,label,available)]；返回选中的 key 列表。回车=默认。"""
    print("\n" + prompt)
    for i, (k, label, av) in enumerate(options, 1):
        d = "默认选中" if k in default_keys else ""
        print(f"  {i}. {label} {'(已检测)' if av else '(未检测)'} {d}")
    raw = input(f"输入序号(逗号分隔，回车=默认[{','.join(default_keys) or '无'}])： ").strip()
    if not raw:
        return list(default_keys)
    picked = []
    for tok in raw.replace("，", ",").split(","):
        tok = tok.strip()
        if tok.isdigit() and 1 <= int(tok) <= len(options):
            picked.append(options[int(tok) - 1][0])
    return picked or list(default_keys)


def _ask_one(prompt: str, options: list, default_key: str) -> str:
    print("\n" + prompt)
    for i, (k, label) in enumerate(options, 1):
        print(f"  {i}. {label} {'(默认)' if k == default_key else ''}")
    raw = input(f"输入序号(回车=默认 {default_key})： ").strip()
    if raw.isdigit() and 1 <= int(raw) <= len(options):
        return options[int(raw) - 1][0]
    return default_key


def run_wizard(auto: bool = False) -> dict:
    print("\n".join(_detect_lines()))

    src_opts = [(p.key, p.label, _safe(p.available)) for p in A.all_platforms()]
    snk_opts = [(s.key, s.label, _safe(s.available)) for s in K.all_sinks()]
    src_default = [k for k, _, av in src_opts if av] or [src_opts[0][0]]
    snk_default = [k for k, _, av in snk_opts if av and k != "local"] or ["local"]

    if auto:
        sources, sinks_sel = src_default, snk_default
    else:
        sources = _ask_multi("① 选「观察源」（工具观察你在这些平台的会话来蒸馏工作流）：",
                             src_opts, src_default)
        sinks_sel = _ask_multi("② 选「通知/输出渠道」（周复盘 DM、Map/周报发到哪）：",
                              snk_opts, snk_default)

    patch = {"sources": sources, "sinks": sinks_sel}

    # skill 落地目标：默认首个可写的已选观察源
    writable = [k for k in sources if (A.by_key(k) and A.by_key(k).skills_root() is not None)]
    target_default = writable[0] if writable else (sources[0] if sources else "claude_code")
    if auto:
        patch["skill_target"] = target_default
    else:
        tgt_opts = [(p.key, p.label) for p in A.all_platforms() if p.skills_root() is not None]
        patch["skill_target"] = _ask_one("③ 「应用到生产」默认把 Skill 落地到哪个平台：",
                                         tgt_opts, target_default)

    if "slack" in sinks_sel and not C.live_cfg("slack_webhook", ""):
        if auto:
            print("  ⚠ 选了 Slack 但未配 slack_webhook —— 请稍后在 config.local.json 填 https://hooks.slack.com/...")
        else:
            wh = input("\n④ Slack Incoming Webhook URL（选了 slack 才需要，回车跳过）： ").strip()
            if wh:
                patch["slack_webhook"] = wh

    C.update_local_config(patch)
    print("\n已写入 config.local.json：")
    for k, v in patch.items():
        shown = "（已设置）" if k == "slack_webhook" else v
        print(f"  {k} = {shown}")
    print(f"\n配置文件：{C.LOCAL_CONFIG_PATH}")
    print("下一步：python3 -m distiller.doctor  然后  python3 -m distiller.pipeline")
    return patch


def _safe(fn) -> bool:
    try:
        return bool(fn())
    except Exception:
        return False


def main(argv=None):
    argv = argv if argv is not None else sys.argv[1:]
    if "--print" in argv:
        print("\n".join(_detect_lines()))
        return 0
    try:
        run_wizard(auto="--auto" in argv)
    except (EOFError, KeyboardInterrupt):
        print("\n（已取消，未改配置）")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
