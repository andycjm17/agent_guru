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

OK, WARN, BAD, NO = "✓", "⚠", "✗", "·"

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
        # 解绑后 bytedcli 不再是硬前置：仅飞书 DM/文档 + 字节 AIME 后端需要它。
        # 真正的硬性要求（LLM 后端 / 至少一个 sink / 至少一个观察源）由下方各节独立判定。
        if npm_ok:
            lines.append(f"     ⚠ 无 bytedcli → 飞书 + 字节 AIME 不可用（其余后端/渠道仍可跑）；如需: {BYTEDCLI_INSTALL}")
        else:
            lines.append(f"     ⚠ 无 bytedcli（且无 npm）→ 飞书/AIME 不可用；如需先装 Node.js/npm 再 {BYTEDCLI_INSTALL}")
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

    # 3) 观察源（Agent 平台，可插拔：Claude Code / Cursor / Codex，任一可观察即可）
    from . import agents as A
    from . import sinks as K
    lines.append("")
    enabled_src = {p.key for p in A.enabled_platforms()}
    sel = C.live_cfg("sources", None)
    lines.append(f"观察源（启用 = {'config 指定' if isinstance(sel, list) and sel else '自动探测所有可用'}）：")
    total_sessions = 0
    for p in A.all_platforms():
        try:
            av = p.available()
        except Exception:
            av = False
        n = -1
        if av:
            try:
                n = len(p.collect_sessions() or [])
            except Exception:
                n = -1
        total_sessions += max(n, 0)
        mark = OK if (av and p.key in enabled_src) else (WARN if av else NO)
        state = (f"{n} 条会话" if n >= 0 else "未检测/不可用")
        en = "启用" if p.key in enabled_src else "未启用"
        lines.append(f"  {mark} {p.label}: {state}（{en}；skill 落地 {p.skill_kind}）")
    if total_sessions == 0:
        lines.append(f"  {BAD} 所有启用观察源都没有可观察会话——先用 Claude/Cursor/Codex 干点活")
        hard_fail = True
    meet = pathlib.Path(C.MEETING_STATE)
    lines.append(f"  {OK if meet.exists() else WARN} 会议语料(可选): {meet}"
                 + ("" if meet.exists() else "（无，跳过会议旁路）"))

    # 4) 通知 / 输出渠道（可插拔：feishu / local / slack，至少一个可用）
    lines.append("")
    snk_sel = C.live_cfg("sinks", None)
    enabled_snk = {s.key for s in K.enabled_sinks()}
    lines.append(f"通知/输出渠道（启用 = {'config 指定' if isinstance(snk_sel, list) and snk_sel else '自动'}）：")
    any_sink = False
    for s in K.all_sinks():
        try:
            av = s.available()
        except Exception:
            av = False
        any_sink = any_sink or (av and s.key in enabled_snk)
        mark = OK if (av and s.key in enabled_snk) else (WARN if av else NO)
        en = "启用" if s.key in enabled_snk else "未启用"
        lines.append(f"  {mark} {s.label}: {'可用' if av else '未配置'}（{en}）")
    if not any_sink:
        lines.append(f"  {WARN} 无启用且可用的渠道——已自动兜底 local（写 data/out/）")

    # 5) 飞书身份（可选：仅 feishu 渠道需要；缺失只降级，不再硬阻断）
    lines.append("")
    lines.append("飞书身份（仅 feishu 渠道需要，缺失=降级）：")
    open_id = C.resolve_lark_user_id()
    if open_id:
        src = "config" if C.LARK_USER_ID else "自动探测/缓存"
        cache = C.load_json(C.IDENTITY_CACHE, default={}) or {}
        who = cache.get("user_name") or "本人"
        lines.append(f"  {OK} 飞书身份: {who}（{open_id[:14]}…，来源 {src}）· 飞书 DM/文档可用")
    else:
        lines.append(f"  {WARN} 飞书身份: 未探测到 open_id —— feishu 渠道降级；如需飞书请 `bytedcli lark auth login`")
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
