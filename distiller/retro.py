#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
retro.py — 每周复盘 + 飞书 DM 速递

照搬 ~/.meeting-actions 范式（state 幂等、--idempotency-key 防重、launchd 调度），
改为每周触发：
  1. 快照当前 map（旧工作流名集合）
  2. 重跑 observe + distill → 新 map
  3. diff 出本周新认出的复发工作流 / 新蒸馏候选
  4. 算本周省时（savings.summary）
  5. bytedcli -j lark im messages-send DM 速递给本人（幂等键=retro-<week>）

用法:
  python -m distiller.retro                 # 完整复盘 + 发 DM
  python -m distiller.retro --dry-run       # 全流程但不发 DM（打印 DM 内容）
  python -m distiller.retro --skip-distill  # 复用现有 map（省 claude，diff 为空，仅看省时）
  python -m distiller.retro --force         # 忽略本周已发的幂等记录，重发
"""
from __future__ import annotations

import sys
import argparse
import datetime as dt

from . import config as C
from . import observe as O
from . import distill as D
from . import savings as S


def _week_key(end: dt.date | None = None) -> str:
    end = end or dt.date.today()
    iso = end.isocalendar()   # ISO 年(iso[0])，避免跨年周号年份错配
    return f"{iso[0]}-W{iso[1]:02d}"


def _names(m: dict) -> set:
    return {w.get("name", "") for w in (m or {}).get("workflows", [])}


def _top_candidates(m: dict, k: int = 3) -> list[dict]:
    """挑最该先做的蒸馏/自动化候选：primary_bucket ∈ {automate, skill}，按 est×n 排序。"""
    cands = [w for w in (m or {}).get("workflows", [])
             if w.get("primary_bucket") in ("automate", "skill")]
    cands.sort(key=lambda w: -(C.as_num(w.get("est_minutes_per_run")) * C.as_num(w.get("n_observed"), 1.0)))
    return cands[:k]


def build_dm(week: str, new_names: set, new_map: dict, sv: dict) -> str:
    lines = [f"**🛠 工作流蒸馏 · 本周复盘速递｜{week}**", ""]
    lines.append(sv["punchline"])
    lines.append("")

    if new_names:
        lines.append("**本周新认出的复发工作流**")
        for n in sorted(new_names):
            lines.append(f"- {n}")
        lines.append("")

    cands = _top_candidates(new_map)
    if cands:
        lines.append("**最该先做（蒸馏/自动化候选）**")
        for w in cands:
            lines.append(f"- [{C.BUCKET_ZH.get(w.get('primary_bucket'),'?')}] {w.get('name')} → {w.get('recommendation')}")
        lines.append("")

    # 省时账本明细
    if sv.get("by_workflow"):
        lines.append("**省时账本（净分钟，含负值）**")
        for wf, net in list(sv["by_workflow"].items())[:6]:
            lines.append(f"- {wf}: ~{net}min")
        lines.append("")

    lines.append(f"_口径：观察 {new_map.get('n_sessions','?')} session + {new_map.get('n_meetings','?')} 会议；"
                 f"省时为诚实估算（~），含负值。UI: localhost:8787_")
    return "\n".join(lines)


def run_retro(dry_run: bool = False, skip_distill: bool = False, force: bool = False) -> dict:
    C.ensure_dirs()
    week = _week_key()
    state = C.load_json(C.PROCESSED_FILE, default={}) or {}
    rk = f"retro-{week}"
    if rk in state and not force and not dry_run:
        C.log(f"retro: {week} 已发过（{state[rk].get('at')}），跳过。--force 可重发")
        return {"skipped": True}

    old_map = C.load_json(C.MAP_FILE, default={}) or {}
    old_names = _names(old_map)

    # 重跑 observe（廉价）
    digests = O.build_digests()
    C.save_json(C.DIGESTS_FILE, digests)
    C.log(f"retro: observe {digests['n_sessions']} session + {digests['n_meetings']} 会议")

    if skip_distill:
        new_map = old_map
        C.log("retro: --skip-distill，复用现有 map（diff 为空）")
    else:
        new_map = D.distill(digests) or old_map
        C.save_json(C.MAP_FILE, new_map)
        C.log(f"retro: distill {len(new_map.get('workflows', []))} 工作流")

    new_names = _names(new_map) - old_names
    sv = S.summary(7)
    dm = build_dm(week, new_names, new_map, sv)

    if dry_run:
        print("\n========== DM 预览（--dry-run，未发送）==========\n")
        print(dm)
        return {"dm": dm, "new_names": sorted(new_names), "savings": sv}

    from . import sinks
    bres = sinks.broadcast_dm(dm, idempotency_key=rk)
    ok = bres["ok"]
    chans = "、".join(k for k, v in bres["results"].items() if v.get("ok")) or "(无)"
    state[rk] = {"at": C.now_utc().isoformat(), "status": "sent" if ok else "failed",
                 "channels": chans, "new_workflows": sorted(new_names), "net_min": sv["net_min"]}
    C.save_json(C.PROCESSED_FILE, state)
    if ok:
        C.log(f"retro: {week} 复盘已发送 → {chans}")
        print(f"已发送本周复盘（{week}）→ {chans}")
    else:
        C.log(f"retro: {week} 复盘发送失败：{bres['results']}")
    return {"ok": ok, "dm": dm, "savings": sv, "channels": bres["results"]}


def main(argv=None):
    argv = argv if argv is not None else sys.argv[1:]
    p = argparse.ArgumentParser(prog="distiller.retro")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--skip-distill", action="store_true")
    p.add_argument("--force", action="store_true")
    args = p.parse_args(argv)
    try:
        run_retro(dry_run=args.dry_run, skip_distill=args.skip_distill, force=args.force)
    except Exception as e:
        C.log(f"retro FATAL: {e!r}")
        sys.exit(1)


if __name__ == "__main__":
    main()
