#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
savings.py — 省时账本 + punchline

每次自动化/Skill 跑完，往 data/savings_ledger.jsonl 追加一条：
  {ts, workflow, est_saved_min, est_overhead_min, net_min, note}
净值 = saved − overhead。**坏掉/返工记负值**（overhead > saved），估算一律标 ~。

punchline 锚点（像 Claude app 的 token 对比那样有记忆点）：
  本周净省 ~Xh ≈ N 个 30min 会 ≈ M 顿午饭
含负值时如实说「净亏」，避免变虚荣指标。

用法:
  python -m distiller.savings record --workflow "会后Action速递" --saved 15 --overhead 1 --note "1场会议"
  python -m distiller.savings summary [--days 7]
"""
from __future__ import annotations

import sys
import argparse
import datetime as dt

from . import config as C

MEETING_MIN = 30   # 1 个会的锚点时长
LUNCH_MIN = 60     # 1 顿午饭的锚点时长


def record(workflow: str, est_saved_min: float, est_overhead_min: float = 0.0,
           note: str = "", ts: str | None = None) -> dict:
    entry = {
        "ts": ts or C.now_utc().isoformat(),
        "workflow": workflow,
        "est_saved_min": round(float(est_saved_min), 1),
        "est_overhead_min": round(float(est_overhead_min), 1),
        "net_min": round(float(est_saved_min) - float(est_overhead_min), 1),
        "note": note,
    }
    C.append_jsonl(C.SAVINGS_LEDGER, entry)
    sign = "+" if entry["net_min"] >= 0 else ""
    C.log(f"savings: {sign}{entry['net_min']}min 净 ({workflow}) {note}")
    return entry


def _entries_in_window(days: int) -> list[dict]:
    rows = C.read_jsonl(C.SAVINGS_LEDGER)
    if days <= 0:
        return rows
    days = min(days, 36500)   # 防 timedelta OverflowError（CLI --days 也走这条）
    cutoff = C.now_utc() - dt.timedelta(days=days)
    out = []
    for r in rows:
        t = C.parse_ts(r.get("ts"))   # 统一解析 + naive 补 UTC
        if t is None:
            continue
        if t >= cutoff:
            out.append(r)
    return out


def _fmt_hours(minutes: float) -> str:
    sign = "-" if minutes < 0 else ""
    h = abs(minutes) / 60.0
    return f"{sign}{h:.1f}h"


def punchline(net_min: float, window_label: str = "本周") -> str:
    """生成有记忆点的省时口径，含负值。"""
    if abs(net_min) < 1:
        return f"{window_label}净省 ~0（自动化与开销基本抵消）"
    meetings = abs(net_min) / MEETING_MIN
    lunches = abs(net_min) / LUNCH_MIN
    if net_min >= 0:
        return (f"{window_label}净省 ~{_fmt_hours(net_min)} "
                f"≈ {meetings:.0f} 个 {MEETING_MIN}min 会 ≈ {lunches:.0f} 顿午饭")
    return (f"{window_label}净亏 ~{_fmt_hours(abs(net_min))}（有返工/坏掉）"
            f"≈ 倒贴 {meetings:.0f} 个 {MEETING_MIN}min 会")


def summary(days: int = 7) -> dict:
    rows = _entries_in_window(days)
    saved = sum(C.as_num(r.get("est_saved_min")) for r in rows)
    overhead = sum(C.as_num(r.get("est_overhead_min")) for r in rows)
    net = saved - overhead
    # 按工作流聚合（脏值安全：as_num 把非数字降级为 0）
    by_wf: dict[str, float] = {}
    for r in rows:
        wf = r.get("workflow", "?")
        by_wf[wf] = by_wf.get(wf, 0.0) + C.as_num(r.get("net_min"))
    label = "本周" if days == 7 else (f"近 {days} 天" if days > 0 else "累计")
    return {
        "window_days": days,
        "window_label": label,
        "n_runs": len(rows),
        "saved_min": round(saved, 1),
        "overhead_min": round(overhead, 1),
        "net_min": round(net, 1),
        "by_workflow": {k: round(v, 1) for k, v in sorted(by_wf.items(), key=lambda kv: -kv[1])},
        "punchline": punchline(net, label),
    }


def main(argv=None):
    argv = argv if argv is not None else sys.argv[1:]
    C.ensure_dirs()
    p = argparse.ArgumentParser(prog="distiller.savings")
    sub = p.add_subparsers(dest="cmd")

    pr = sub.add_parser("record")
    pr.add_argument("--workflow", required=True)
    pr.add_argument("--saved", type=float, required=True)
    pr.add_argument("--overhead", type=float, default=0.0)
    pr.add_argument("--note", default="")

    ps = sub.add_parser("summary")
    ps.add_argument("--days", type=int, default=7)

    args = p.parse_args(argv)
    if args.cmd == "record":
        e = record(args.workflow, args.saved, args.overhead, args.note)
        print(e)
    elif args.cmd == "summary":
        s = summary(args.days)
        print(s["punchline"])
        print(f"  runs={s['n_runs']} saved=~{s['saved_min']}min overhead=~{s['overhead_min']}min net=~{s['net_min']}min")
        for wf, net in s["by_workflow"].items():
            print(f"    · {wf}: ~{net}min")
    else:
        p.print_help()


if __name__ == "__main__":
    main()
