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
import threading
import datetime as dt

from . import config as C

MEETING_MIN = 30   # 1 个会的锚点时长
LUNCH_MIN = 60     # 1 顿午饭的锚点时长

# 自动记账估算口径（诚实估算，标 ~）：每场被自动速递 action 的会议，省去的手动提取/整理时长
MEETING_SAVED_MIN = float(C._cfg("meeting_saved_min", 15))     # 手动从转录里提 action+整理+发 ≈ 15min
MEETING_OVERHEAD_MIN = float(C._cfg("meeting_overhead_min", 1))  # 自动化开销 ≈ 扫一眼 DM 1min

_RECONCILE_LOCK = threading.Lock()   # 串行化 reconcile 的「读已有 key → 追加」，避免并发重复记账


def record(workflow: str, est_saved_min: float, est_overhead_min: float = 0.0,
           note: str = "", ts: str | None = None, src_key: str | None = None) -> dict:
    entry = {
        "ts": ts or C.now_utc().isoformat(),
        "workflow": workflow,
        "est_saved_min": round(float(est_saved_min), 1),
        "est_overhead_min": round(float(est_overhead_min), 1),
        "net_min": round(float(est_saved_min) - float(est_overhead_min), 1),
        "note": note,
    }
    if src_key:
        entry["src_key"] = src_key   # 幂等键：reconcile 据此防重复记账
    C.append_jsonl(C.SAVINGS_LEDGER, entry)
    sign = "+" if entry["net_min"] >= 0 else ""
    C.log(f"savings: {sign}{entry['net_min']}min 净 ({workflow}) {note}")
    return entry


def _recorded_src_keys() -> set:
    """账本里已有的幂等键集合（供 reconcile 防重）。"""
    return {r["src_key"] for r in C.read_jsonl(C.SAVINGS_LEDGER)
            if isinstance(r, dict) and r.get("src_key")}


def reconcile() -> dict:
    """把『真实跑过的自动化』幂等地补记进账本——让 banner 反映真实活动而非静态种子。

    当前源：meeting-actions 的 state/processed.json，每条 status=='sent' 的会议速递
    = 一次真实自动化（省去手动从转录提 action）。用会议自身时间戳记账，落进正确的时间窗。
    幂等键 meeting:<token>，已记过的跳过。源缺失/异常静默返回 added=0，绝不影响主流程。
    """
    added = 0
    by_source = {}
    with _RECONCILE_LOCK:
        existing = _recorded_src_keys()
        # —— 源 1：meeting-actions 会议速递 ——
        try:
            state = C.load_json(C.MEETING_STATE, default={}) or {}
            n = 0
            for token, v in state.items():
                if not isinstance(v, dict):
                    continue
                if v.get("status") != "sent":     # 只记真正发出的（排除 seed/skip/failed）
                    continue
                key = f"meeting:{token}"
                if key in existing:
                    continue
                record("会后Action速递", MEETING_SAVED_MIN, MEETING_OVERHEAD_MIN,
                       note=str(v.get("title", ""))[:60], ts=v.get("at"), src_key=key)
                existing.add(key)
                n += 1
            by_source["meeting_actions"] = n
            added += n
        except Exception as e:
            C.log(f"savings.reconcile: meeting-actions 源异常（忽略）: {e!r}")
    if added:
        C.log(f"savings.reconcile: 补记 {added} 条真实自动化 {by_source}")
    return {"added": added, "by_source": by_source}


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
    # 锚点不足 1 个会时四舍五入会塌成「≈ 0 个会 ≈ 0 顿午饭」，反而误导 —— 此时只报时长
    anchored = meetings >= 1
    if net_min >= 0:
        base = f"{window_label}净省 ~{_fmt_hours(net_min)}"
        return (base + f" ≈ {meetings:.0f} 个 {MEETING_MIN}min 会 ≈ {lunches:.0f} 顿午饭") if anchored else base
    base = f"{window_label}净亏 ~{_fmt_hours(abs(net_min))}（有返工/坏掉）"
    return (base + f" ≈ 倒贴 {meetings:.0f} 个 {MEETING_MIN}min 会") if anchored else base


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

    sub.add_parser("reconcile")   # 从真实自动化源补记账本（幂等）

    args = p.parse_args(argv)
    if args.cmd == "record":
        e = record(args.workflow, args.saved, args.overhead, args.note)
        print(e)
    elif args.cmd == "reconcile":
        r = reconcile()
        print(f"reconcile: 补记 {r['added']} 条 {r['by_source']}")
        s = summary(7)
        print(f"  → 本周 net=~{s['net_min']}min（{s['n_runs']} runs）")
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
