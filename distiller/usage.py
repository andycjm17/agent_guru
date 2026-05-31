#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
usage.py — 实测计数（非估算）

省时是反事实、只能估；但「你调用了几次 skill / 跑了几次自动化」是**实测**的。
本模块只数事实，给 banner 一个不靠拍脑袋的口径：
  - skill 调用次数：扫 Claude Code session jsonl 里 tool_use name=="Skill"，按 input.skill 归类
  - 自动化运行次数：savings 账本在窗内的真实条目数（reconcile 后 = 真发出的会议速递等）

只读会话历史；缺失/异常静默降级。用法：python -m distiller.usage [--days 7]
"""
from __future__ import annotations

import sys
import argparse
import datetime as dt

from . import config as C

# 子会话/工作流不是用户的直接调用，排除
_EXCLUDE_PARTS = ("subagents", "workflows")


def skill_usage(days: int = 7) -> dict:
    """实测 skill 调用次数（Claude Code）。返回 {total, by_skill}。窗口按事件时间戳。"""
    root = C.CLAUDE_PROJECTS
    out = {"total": 0, "by_skill": {}}
    if not root.exists():
        return out
    now = C.now_utc()
    cutoff = now - dt.timedelta(days=min(days, 36500)) if days > 0 else None
    cutoff_epoch = cutoff.timestamp() if cutoff else 0.0
    total = 0
    by: dict = {}
    try:
        files = sorted(root.rglob("*.jsonl"))
    except OSError:
        return out
    for p in files:
        if _EXCLUDE_PARTS[0] in p.parts or _EXCLUDE_PARTS[1] in p.parts:
            continue
        try:
            if cutoff and p.stat().st_mtime < cutoff_epoch:
                continue   # 文件最后写入早于窗口 → 窗内无事件，跳过（提速）
        except OSError:
            continue
        try:
            events = C.read_jsonl(p)
        except Exception:
            continue
        for o in events:
            if not isinstance(o, dict):
                continue
            ts = C.parse_ts(o.get("timestamp"))
            if cutoff and (ts is None or ts < cutoff):
                continue
            msg = o.get("message") if isinstance(o.get("message"), dict) else {}
            content = msg.get("content")
            if not isinstance(content, list):
                continue
            for b in content:
                if isinstance(b, dict) and b.get("type") == "tool_use" and b.get("name") == "Skill":
                    sk = (b.get("input") or {}).get("skill") or "?"
                    by[sk] = by.get(sk, 0) + 1
                    total += 1
    return {"total": total, "by_skill": dict(sorted(by.items(), key=lambda kv: -kv[1]))}


def summary(days: int = 7) -> dict:
    """banner 用的实测计数口径（+ 保留估算净省作次要参考）。"""
    from . import savings as S
    su = skill_usage(days)
    sv = S.summary(days)   # n_runs = 真实自动化运行数（reconcile 后）；net_min 仅作次要估算
    label = "本周" if days == 7 else (f"近 {days} 天" if days > 0 else "累计")
    headline = f"{label} skill 调用 {su['total']} 次 · 自动化运行 {sv['n_runs']} 次"
    return {
        "window_days": days,
        "window_label": label,
        "skill_total": su["total"],
        "by_skill": su["by_skill"],
        "automation_runs": sv["n_runs"],
        "automation_by_workflow": sv.get("by_workflow", {}),
        "est_net_min": sv["net_min"],      # 估算，次要展示，明确标注
        "headline": headline,
    }


def main(argv=None):
    argv = argv if argv is not None else sys.argv[1:]
    p = argparse.ArgumentParser(prog="distiller.usage")
    p.add_argument("--days", type=int, default=7)
    args = p.parse_args(argv)
    s = summary(args.days)
    print(s["headline"])
    if s["by_skill"]:
        print("  按 skill：" + "  ".join(f"{k}×{v}" for k, v in s["by_skill"].items()))
    print(f"  （另：估算净省 ~{s['est_net_min']}min，反事实估算、仅参考、非实测）")


if __name__ == "__main__":
    main()
