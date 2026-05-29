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

    print("\n========== workflow-distiller · 串行整体流程 ==========\n")

    # 1) 观察
    print("[1/3] observe — 扫 session + 会议 → digests")
    digests = O.build_digests()
    C.save_json(C.DIGESTS_FILE, digests)
    print(f"      ✓ {digests['n_sessions']} session + {digests['n_meetings']} 会议\n")

    # 2) 蒸馏
    print("[2/3] distill — 聚类复发工作流 + 四桶分拣（claude -p，约 2-4 分钟）")
    m = D.distill(digests)
    if not m:
        print("      ✗ distill 失败，中止")
        return None
    C.save_json(C.MAP_FILE, m)
    print(f"      ✓ {len(m.get('workflows', []))} 条工作流")
    print(f"      headline: {(m.get('headline') or '')[:90]}…\n")

    # 3) 交付（render 隔离：map 结构异常不应让整条流程抛栈，认知成果已在 map.json 落盘）
    print("[3/3] render — DocxXML → Lark 文档")
    try:
        xml = R.build_xml(m)
        (C.PROJECT_ROOT / R.XML_REL).write_text(xml, encoding="utf-8")
        if no_lark:
            print(f"      ✓ 生成 {len(xml)} 字符 XML（--no-lark，未推 Lark）\n")
        else:
            res = R.push_to_lark(xml)
            if res.get("url"):
                print(f"      ✓ Lark [{res['action']}] → {res['url']}\n")
            else:
                print(f"      ⚠ 未取到 URL：{res.get('raw', '')[:160]}\n")
    except Exception as e:
        C.log(f"pipeline: render 失败但 map.json 已落盘，可单独重跑 render：{e!r}")
        print(f"      ⚠ render 异常（map.json 已保存，可 python -m distiller.render 重试）：{e!r}\n")

    # 省时 summary
    sv = S.summary(7)
    print("---------- 省时 punchline ----------")
    print(f"  {sv['punchline']}")
    print(f"  runs={sv['n_runs']} 净=~{sv['net_min']}min（省 ~{sv['saved_min']} − 开销 ~{sv['overhead_min']}）")
    print("\n========== 流程完成 ==========")
    print("  · 看 Map / 切自主度：python -m distiller.server")
    print("  · 出本周周报草稿：python -m distiller.weekly_update")
    print("  · 每周复盘 DM：python -m distiller.retro（或 launchctl 加载 plist 定时）")
    return {"digests": digests, "map": m, "savings": sv}


if __name__ == "__main__":
    main()
