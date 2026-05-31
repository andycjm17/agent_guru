#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
sinks/ — 可插拔通知/输出渠道注册表

解绑飞书：通知发去哪、报告落到哪，由 config.local.json 的 sinks 驱动；缺省自动择优。
broadcast_* 把一条内容扇出给所有「启用且可用」的 sink，任一失败不连累其它；若一个都不可用，
兜底用 local（保证零配置也总能看到产出）。一律走 C.live_cfg，UI/setup 改完即时生效。
"""
from __future__ import annotations

from .. import config as C
from .base import Sink
from .feishu import FeishuSink
from .local import LocalSink
from .slack import SlackSink

# 顺序即默认偏好
_REGISTRY = [FeishuSink(), SlackSink(), LocalSink()]


def all_sinks() -> list:
    return list(_REGISTRY)


def by_key(key: str):
    for s in _REGISTRY:
        if s.key == key:
            return s
    return None


def available_sinks() -> list:
    out = []
    for s in _REGISTRY:
        try:
            if s.available():
                out.append(s)
        except Exception:
            pass
    return out


def enabled_sinks() -> list:
    """启用渠道：config sinks 显式列表 → 否则自动（可用的 feishu/slack；都不可用则 local）。
    最终再过一遍 available()，并保证至少有一个（兜底 local）。"""
    sel = C.live_cfg("sinks", None)
    if isinstance(sel, list) and sel:
        chosen = [s for s in _REGISTRY if s.key in sel]
    else:
        chosen = [s for s in _REGISTRY if s.key != "local" and _is_avail(s)]
    chosen = [s for s in chosen if _is_avail(s)]
    if not chosen:
        chosen = [by_key("local")]
    return chosen


def _is_avail(s) -> bool:
    try:
        return s.available()
    except Exception:
        return False


def broadcast_dm(markdown: str, idempotency_key: str) -> dict:
    """把短消息发给所有启用渠道。返回 {ok(任一成功即 True), results:{key:res}}。"""
    results = {}
    any_ok = False
    for s in enabled_sinks():
        res = {}
        try:
            res = s.send_dm(markdown, idempotency_key)
        except Exception as e:
            res = {"ok": False, "error": repr(e)}
        results[s.key] = res
        any_ok = any_ok or bool(res.get("ok"))
    return {"ok": any_ok, "results": results}


def broadcast_report(title: str, markdown: str,
                     doc_key: str = "", docx_xml: str = "") -> dict:
    """把长报告发给所有启用渠道。返回 {ok, url(首个有 url 的), results}。"""
    results = {}
    any_ok = False
    url = None
    for s in enabled_sinks():
        res = {}
        try:
            res = s.publish_report(title, markdown, doc_key=doc_key, docx_xml=docx_xml)
        except Exception as e:
            res = {"ok": False, "error": repr(e)}
        results[s.key] = res
        any_ok = any_ok or bool(res.get("ok"))
        url = url or res.get("url")
    return {"ok": any_ok, "url": url, "results": results}
