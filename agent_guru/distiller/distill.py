#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
distill.py — 蒸馏层

把 data/digests.json 的紧凑摘要喂给 claude -p，聚类成**复发工作流**，每条工作流
列步骤并打四桶标签（eliminate / automate / skill / human）+ confidence，估频率与
单次耗时，给「先 skill 化 / 自动化哪一步」的 next_action。输出严格 JSON → data/map.json。

会话量大时自动分批喂（每批 BATCH 个 session），再合并。

用法:
  python -m distiller.distill           # 读 digests.json → 写 map.json
  python -m distiller.distill --dry     # 只打印将要发送的 prompt，不调用 claude
"""
from __future__ import annotations

import sys

from . import config as C

BATCH = 40   # 单批 session 上限（控 claude -p 上下文；紧凑摘要小，单批可容数十条以保聚类完整）

SCHEMA_HINT = """{
  "headline": "一句话总览：观察到哪些复发工作流、最该先动手的是什么",
  "workflows": [
    {
      "name": "工作流名（动词短语，如『会后 Action 速递』）",
      "summary": "1-2 句这条工作流在做什么",
      "frequency": "复发频率（如 每个会议后 / 每周 / 高频 / 偶发）",
      "est_minutes_per_run": 人工单次耗时的诚实估算(整数, 分钟),
      "n_observed": 在样本里观察到的实例数(整数),
      "instances": ["对应的 session/会议标题", "..."],
      "primary_bucket": "eliminate|automate|skill|human",
      "steps": [
        {
          "desc": "这一步在做什么",
          "bucket": "eliminate|automate|skill|human",
          "confidence": 0.0-1.0,
          "next_action": "把这一步推进到下一档的具体动作（如『写成 launchd 脚本』『蒸馏成 SKILL.md』『保留给人拍板』）"
        }
      ],
      "recommendation": "整条工作流下一步最该做什么（单句、可执行）"
    }
  ]
}"""

PROMPT_TMPL = """你是「工作流蒸馏器」。下面是{who}用 AI（Claude Code）干活留下的 session 摘要 + 会议清单。
你的任务：把这些**实例**聚类成**复发的工作流**，并对每条工作流的每个步骤判断它属于四个桶里的哪个，给出把它「向下流动」的下一步动作。

四个桶（判据）：
- eliminate(消除): 没人看 / 历史包袱 / 重复劳动本身就不该存在 → 建议停掉
- automate(自动化): 确定性、规则化、同输入同输出 → 可写成脚本/launchd 定时任务
- skill(Skill): 需要判断但判断可被蒸馏复用 → 可沉淀成一份 SKILL.md
- human(人): 人际 / 信任 / 问责 / 拍板 → 显式留给人，不要自动化

要求：
1. 聚类成 5-9 条**复发**工作流（把同类的多个 session 合并成一条；一次性探索/调试可合并为「工具搭建与调试」一类）。
2. 每条给 frequency、est_minutes_per_run（诚实估算，宁可保守）、n_observed、instances（引用真实标题）。
3. 每条列 2-5 个 step，逐个打 bucket + confidence(0-1) + next_action。
4. primary_bucket 取这条工作流的主导桶。
5. recommendation 给出**单条最该先做**的动作。
6. 已经在自动化运行的（如会后 Action 速递管线）要识别出来、primary_bucket=automate、recommendation 写「已自动化，维持/扩展」。
7. 严格只输出 JSON，不要 markdown 代码块、不要解释。结构如下：

{schema}

=== 观察到的 session 摘要（{n_sessions} 条）===
{sessions}

=== 观察到的会议（{n_meetings} 条，旁路语料）===
{meetings}
"""


def _fmt_session(s: dict) -> str:
    tools = ", ".join(f"{k}×{v}" for k, v in (s.get("tools") or {}).items()) or "无工具调用"
    act = s.get("active_min")
    act_s = f"{act}min" if act is not None else "?"
    return (
        f"- 标题: {s.get('title')}\n"
        f"  项目: {s.get('project')} | 活跃时长: ~{act_s} | user轮次: {s.get('n_user_turns')} | 工具: {tools}\n"
        f"  意图: {s.get('intent') or '(无)'}"
    )


def _fmt_meeting(m: dict) -> str:
    return f"- {m.get('title')}（状态 {m.get('status')}）"


def build_prompt(digests: dict, sessions: list[dict]) -> str:
    sess_txt = "\n".join(_fmt_session(s) for s in sessions) or "(无)"
    meet_txt = "\n".join(_fmt_meeting(m) for m in digests.get("meetings", [])) or "(无)"
    name = C.resolve_user_name()
    who = f" {name} " if name else "用户"   # 自动读取的用户名；探测不到用中性「用户」
    return PROMPT_TMPL.format(
        who=who,
        schema=SCHEMA_HINT,
        n_sessions=len(sessions),
        n_meetings=len(digests.get("meetings", [])),
        sessions=sess_txt,
        meetings=meet_txt,
    )


def _merge_maps(maps: list[dict]) -> dict:
    """多批结果合并：**按工作流名去重**。claude 对每批独立聚类，跨批可能把同一工作流
    各报一次；这里把同名的合并（instances 取并集、steps 按 desc 去重保高置信、
    n_observed 取并集实例数），避免重复条目污染下游（render 表 / retro 排序 / UI）。"""
    by_name: dict = {}
    order: list = []
    headline = ""
    for m in maps:
        if not m:
            continue
        headline = headline or m.get("headline", "")
        for w in (m.get("workflows", []) or []):
            name = w.get("name", "")
            if not name:
                continue
            if name not in by_name:
                by_name[name] = dict(w)
                by_name[name]["instances"] = list(w.get("instances", []) or [])
                order.append(name)
                continue
            cur = by_name[name]
            # instances 并集（保序去重）
            seen = set(cur.get("instances", []))
            for inst in (w.get("instances", []) or []):
                if inst not in seen:
                    cur["instances"].append(inst)
                    seen.add(inst)
            # steps 按 desc 去重保高置信；缺 desc 的步骤无法可靠去重 → 原样保留，不折叠
            deduped: dict = {}
            extra: list = []
            for st in list(cur.get("steps", []) or []) + list(w.get("steps", []) or []):
                d = st.get("desc")
                if not d:
                    extra.append(st)
                elif d not in deduped or C.as_num(st.get("confidence")) > C.as_num(deduped[d].get("confidence")):
                    deduped[d] = st
            cur["steps"] = list(deduped.values()) + extra
            # n_observed 取「并集实例数」与「两批之和」的较大者（更接近全局真值；as_num 防 LLM 返回 "5次" 之类脏值）
            cur["n_observed"] = max(len(cur["instances"]),
                                    int(C.as_num(cur.get("n_observed"))) + int(C.as_num(w.get("n_observed"))))
    return {"headline": headline or "", "workflows": [by_name[n] for n in order]}


def distill(digests: dict, dry: bool = False) -> dict | None:
    sessions = digests.get("sessions", [])
    batches = [sessions[i:i + BATCH] for i in range(0, len(sessions), BATCH)] or [[]]
    C.log(f"distill: {len(sessions)} sessions → {len(batches)} 批")

    if dry:
        print(build_prompt(digests, batches[0]))
        return None

    results = []
    for i, batch in enumerate(batches, 1):
        prompt = build_prompt(digests, batch)
        C.log(f"distill: 第 {i}/{len(batches)} 批 → LLM[{C.active_provider()}] ({len(prompt)} 字符)")
        obj = C.llm(prompt, timeout=420, expect_json=True)
        if obj is None:
            C.log(f"distill: 第 {i} 批失败")
            continue
        results.append(obj)

    if not results:
        return None
    merged = _merge_maps(results)
    merged["generated_at"] = C.now_utc().isoformat()
    merged["n_sessions"] = len(sessions)
    merged["n_meetings"] = len(digests.get("meetings", []))
    return merged


def main(argv=None):
    argv = argv or sys.argv[1:]
    C.ensure_dirs()
    digests = C.load_json(C.DIGESTS_FILE)
    if not digests:
        C.log("distill: 缺 digests.json，请先跑 observe")
        return None
    dry = "--dry" in argv
    result = distill(digests, dry=dry)
    if dry:
        return None
    if not result:
        C.log("distill: 无结果")
        return None
    C.save_json(C.MAP_FILE, result)
    wf = result.get("workflows", [])
    C.log(f"distill: {len(wf)} 条工作流 → {C.MAP_FILE}")
    print(f"\nHEADLINE: {result.get('headline','')}\n")
    for w in wf:
        buckets = {}
        for st in w.get("steps", []):
            b = st.get("bucket")
            buckets[b] = buckets.get(b, 0) + 1
        bk = ", ".join(f"{C.BUCKET_ZH.get(k,k)}×{v}" for k, v in buckets.items())
        print(f"  ▸ {w.get('name')}  [{C.BUCKET_ZH.get(w.get('primary_bucket'),'?')}] "
              f"freq={w.get('frequency')} ~{w.get('est_minutes_per_run')}min×{w.get('n_observed')}")
        print(f"      steps: {bk}")
        print(f"      → {w.get('recommendation')}")
    return result


if __name__ == "__main__":
    main()
