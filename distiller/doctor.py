#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
doctor.py — 部署环境自检

在别人的机器上装好后跑一遍，确认依赖/鉴权/路径/配置都就绪，并清楚告知哪些功能可用、
哪些因缺配置而降级。不做任何写操作、不发 DM、不调 claude（除轻量 --version 探测）。

用法:
  python3 -m distiller.doctor            # 只读检测，不动系统
  python3 -m distiller.doctor --fix      # 检测后把「能自动装的」装上（建目录、npm 装 bytedcli）
  python3 -m distiller.doctor --fix -y   # 同上但跳过确认（非交互/CI）
退出码：0 = 无硬性阻断（可能有降级告警）；1 = 有硬性缺失（核心功能不可用）。
"""
from __future__ import annotations

import sys
import shutil
import pathlib
import argparse
import subprocess

from . import config as C

OK, WARN, BAD, NO = "✓", "⚠", "✗", "·"

# bytedcli 安装命令（前置：它是飞书 DM/身份/文档的依赖）
BYTEDCLI_INSTALL = "npm install -g @bytedance-dev/bytedcli@latest --registry https://bnpm.byted.org"
# 同一条命令的 argv 形式（--fix 直接 subprocess 调用，免 shell）
BYTEDCLI_NPM_ARGS = ["npm", "install", "-g", "@bytedance-dev/bytedcli@latest",
                     "--registry", "https://bnpm.byted.org"]


def _check_cli(path: str, name: str) -> tuple[bool, str]:
    p = pathlib.Path(path)
    # path 可能是裸名（靠 PATH）；用 which 再确认一次
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


def _confirm(prompt: str, assume_yes: bool) -> bool:
    """--fix 的确认门：-y 直接放行；非 TTY（CI/管道）不擅自改系统，返回 False。"""
    if assume_yes:
        return True
    if not sys.stdin.isatty():
        return False
    try:
        return input(prompt).strip().lower() in ("y", "yes")
    except EOFError:
        return False


def _autofix(assume_yes: bool) -> list:
    """--fix：检测前把「能自动装的」装上，返回操作记录行。
    可自动化：建数据/日志目录、npm 全局装 bytedcli。
    不可自动化：飞书 SSO 登录（交互式）、装 Node/npm（缺它就装不了 bytedcli）——仅提示。
    在检测之前调用，使随后的检测体现修复后的状态。"""
    out = ["", "自动修复（--fix）：", "-" * 40]

    # 1) 目录（无副作用，--fix 直接建）
    made = []
    for d in (C.DATA_DIR, C.STATE_DIR, C.LOG_DIR):
        try:
            if not d.exists():
                d.mkdir(parents=True, exist_ok=True)
                made.append(d.name)
        except OSError as e:
            out.append(f"  {BAD} 建目录失败 {d}: {e}")
    out.append(f"  {OK} 目录就绪" + (f"（新建 {'、'.join(made)}）" if made else "（已存在）"))

    # 2) bytedcli（缺则 npm 全局安装）
    if shutil.which("bytedcli"):
        out.append(f"  {OK} bytedcli 已在 PATH，跳过安装")
    elif not shutil.which("npm"):
        out.append(f"  {WARN} 无 npm，装不了 bytedcli；请先装 Node.js（含 npm）后重跑 --fix")
    elif _confirm(f"  缺 bytedcli，npm 全局安装？[{BYTEDCLI_INSTALL}] [y/N] ", assume_yes):
        out.append(f"  → 执行：{BYTEDCLI_INSTALL}")
        print("  → 正在 npm 安装 bytedcli（约 1–2 分钟，进度见下）…", flush=True)
        try:
            r = subprocess.run(BYTEDCLI_NPM_ARGS, timeout=600)  # 继承 stdio：npm 进度直接打到终端
            if r.returncode == 0 and shutil.which("bytedcli"):
                out.append(f"  {OK} bytedcli 安装成功 → {shutil.which('bytedcli')}")
            else:
                out.append(f"  {BAD} 安装未成功（退出码 {r.returncode}）；可手动执行上面命令")
        except subprocess.TimeoutExpired:
            out.append(f"  {BAD} 安装超时（>600s）；网络/registry 可能受限，可手动重试")
        except Exception as e:
            out.append(f"  {BAD} 安装异常: {e!r}")
    else:
        out.append(f"  {NO} 跳过 bytedcli 安装（未确认）；如需: {BYTEDCLI_INSTALL}")

    # 3) 飞书授权：交互式登录无法自动化，仅在已装 bytedcli 但未授权时提示
    if shutil.which("bytedcli"):
        try:
            authed = bool(C.resolve_lark_user_id())
        except Exception:
            authed = False
        if not authed:
            out.append(f"  {WARN} 飞书未授权——SSO 登录无法自动化，请手动跑: bytedcli lark auth login")

    out.append("-" * 40)
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="distiller.doctor", description="环境自检；--fix 顺手装上能自动化的缺失项")
    ap.add_argument("--fix", action="store_true",
                    help="检测后自动安装可自动化的缺失项（建目录、npm 装 bytedcli）")
    ap.add_argument("-y", "--yes", action="store_true",
                    help="配合 --fix：跳过确认直接安装（非交互/CI）")
    args = ap.parse_args(argv if argv is not None else sys.argv[1:])

    # 先修复（若 --fix），随后的检测即反映修复后的真实状态
    fix_lines = _autofix(args.yes) if args.fix else None

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
    lines.append(f"观察源（启用 = {'配置指定' if isinstance(sel, list) and sel else '自动探测所有可用'}）：")
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
        lines.append(f"  {mark} {p.label}: {state}（{en}；Skill 目标 {p.skill_kind}）")
    if total_sessions == 0:
        lines.append(f"  {BAD} 所有启用的观察源均无可观察会话；请先在 Claude / Cursor / Codex 中产生会话记录")
        hard_fail = True
    meet = pathlib.Path(C.MEETING_STATE)
    lines.append(f"  {OK if meet.exists() else WARN} 会议摘要(可选): {meet}"
                 + ("" if meet.exists() else "（无，跳过会议旁路）"))

    # 4) 通知/输出渠道（可插拔：feishu / local / slack，至少一个可用）
    lines.append("")
    snk_sel = C.live_cfg("sinks", None)
    enabled_snk = {s.key for s in K.enabled_sinks()}
    lines.append(f"通知/输出渠道（启用 = {'配置指定' if isinstance(snk_sel, list) and snk_sel else '自动'}）：")
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
        lines.append(f"  {WARN} 无启用且可用的渠道；已自动回退至 local（写入 data/out/）")

    # 5) 飞书身份（可选：仅 feishu 渠道需要；缺失只降级，不再硬阻断）
    lines.append("")
    lines.append("飞书身份（仅 feishu 渠道需要，缺失时降级）：")
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
        lines.append(f"{OK} 核心功能就绪。{WARN} 项为按配置降级，可按需补齐。")
        lines.append("下一步：python3 -m distiller.pipeline  然后  python3 -m distiller.server")
    if not args.fix:
        lines.append("提示：python3 -m distiller.doctor --fix 可顺手装上能自动化的缺失项")
    # 把自动修复记录插在标题之后，让其下的检测结果体现修复后的状态
    if fix_lines:
        lines = lines[:2] + fix_lines + lines[2:]
    print("\n".join(lines))
    return 1 if hard_fail else 0


if __name__ == "__main__":
    sys.exit(main())
