#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
sinks/base.py — 通知/输出渠道适配器基类

把「把东西送出去」从飞书解绑。两类操作：
  - send_dm(markdown, key)        短消息（retro 周复盘、通知）
  - publish_report(title, md, …)  长报告（Workflow Map / 周报）

每个 sink 自己决定如何呈现：feishu 走 DM/Lark 文档，local 写本地 markdown，slack 发 webhook。
返回统一 {ok, ...}；失败不抛栈，由上层 broadcast 汇总。
"""
from __future__ import annotations


class Sink:
    key = "base"
    label = "Base"

    def available(self) -> bool:
        return False

    def send_dm(self, markdown: str, idempotency_key: str) -> dict:
        return {"ok": False, "error": "not implemented"}

    def publish_report(self, title: str, markdown: str,
                       doc_key: str = "", docx_xml: str = "") -> dict:
        return {"ok": False, "error": "not implemented"}
