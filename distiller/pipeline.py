#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
pipeline.py — 串行整体流程（认知三段：观察 → 蒸馏 → 交付）

observe → distill → render，末尾打印省时 summary。这是 Phase 1 的端到端入口。
（weekly_update / retro 是 Phase 2 的闭环，各自独立触发，不在此串。）

用法:
  python -m distiller.pipeline            # 跑 observe+distill+render（render 推/更新 Lark）
  python -m distiller.pipeline --no-lark  # 只 observe+distill，render 仅生成 XML 不推 Lark
"""
from __future__ import annotations

import sys

from . import config as C
from . import observe as O
from . import distill as D
from . import render as R
from . import savings as S


def main(argv=None):
    argv = argv if argv is not None else sys.argv[1:]
    C.ensure_dirs()
    no_lark = "--no-lark" in argv

    print("\n===== workflow-distiller · 主流程 =====\n")

    # 1) 观察
    print("[1/3] 观察 — 采集会话与会议摘要")
    digests = O.build_digests()
    C.save_json(C.DIGESTS_FILE, digests)
    print(f"      ✓ {digests['n_sessions']} 个会话 + {digests['n_meetings']} 场会议\n")

    # 2) 蒸馏
    print("[2/3] 蒸馏 — 聚类复发工作流并分类（LLM，约 2–4 分钟）")
    m = D.distill(digests)
    if not m:
        print("      ✗ 蒸馏失败，已中止")
        return None
    C.save_json(C.MAP_FILE, m)
    print(f"      ✓ {len(m.get('workflows', []))} 条工作流")
    print(f"      概述：{(m.get('headline') or '')[:90]}…\n")

    # 3) 交付（render 隔离：map 结构异常不应让整条流程抛栈，结果已在 map.json 落盘）
    print("[3/3] 交付 — 发送至启用的渠道")
    try:
        res = R.deliver(m, no_external=no_lark)
        if no_lark:
            print(f"      ✓ 已生成 {res.get('xml_len', 0)} 字符（--no-lark，未对外发送）\n")
        else:
            oks = "、".join(k for k, v in (res.get("results") or {}).items() if v.get("ok")) or "无"
            tail = f"；链接 / 路径 {res['url']}" if res.get("url") else ""
            print(f"      ✓ 已交付至 {oks}{tail}\n")
    except Exception as e:
        C.log(f"pipeline: render 失败但 map.json 已落盘，可单独重跑 render：{e!r}")
        print(f"      ⚠ 交付异常（map.json 已保存，可运行 python -m distiller.render 重试）：{e!r}\n")

    # 使用概览（先从真实自动化源补记账本，使计数保持实时）
    S.reconcile()
    sv = S.summary(7)
    print("----- 使用概览（近 7 天）-----")
    print(f"  {sv['punchline']}")
    print(f"  自动化运行 {sv['n_runs']} 次 · 估算净省 ~{sv['net_min']}min（省 ~{sv['saved_min']} − 开销 ~{sv['overhead_min']}，仅供参考）")
    print("\n===== 完成 =====")
    print("  · 查看 Map / 配置自主度：python -m distiller.server")
    print("  · 生成本周周报草稿：python -m distiller.weekly_update")
    print("  · 每周复盘：python -m distiller.retro（或通过 launchd 定时）")
    return {"digests": digests, "map": m, "savings": sv}


if __name__ == "__main__":
    main()
