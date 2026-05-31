#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
sinks/slack.py — Slack 渠道（Incoming Webhook）

填了 slack_webhook（https://hooks.slack.com/services/...）即启用：
  send_dm        → POST {"text": mrkdwn}（markdown 粗转 Slack mrkdwn）
  publish_report → POST 一段摘要 + 同时把全文写到本地（webhook 不适合贴超长文档）

不填 webhook 则 available()=False，broadcast 自动跳过。纯 urllib，无第三方依赖。
"""
from __future__ import annotations

import json
import urllib.request

from .. import config as C
from .base import Sink
from .local import LocalSink


class SlackSink(Sink):
    key = "slack"
    label = "Slack (Incoming Webhook)"

    def _webhook(self) -> str:
        return C.live_cfg("slack_webhook", "") or C.SLACK_WEBHOOK or ""

    def available(self) -> bool:
        return self._webhook().startswith("https://hooks.slack.com/")

    def _post(self, payload: dict, timeout: int = 20) -> dict:
        url = self._webhook()
        if not url:
            return {"ok": False, "error": "未配置 slack_webhook"}
        try:
            data = json.dumps(payload).encode("utf-8")
            req = urllib.request.Request(url, data=data, method="POST",
                                         headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                body = resp.read().decode("utf-8", "replace").strip()
                ok = (resp.status == 200) and (body.lower() == "ok")
                return {"ok": ok, "status": resp.status, "body": body[:120]}
        except Exception as e:
            C.log(f"sink[slack]: webhook 失败 {e!r}")
            return {"ok": False, "error": repr(e)}

    def send_dm(self, markdown: str, idempotency_key: str) -> dict:
        r = self._post({"text": C.to_slack_mrkdwn(markdown)})
        r["channel"] = "slack"
        return r

    def publish_report(self, title: str, markdown: str,
                       doc_key: str = "", docx_xml: str = "") -> dict:
        # 同时落本地全文，webhook 只发摘要 + 指向本地文件
        local = LocalSink().publish_report(title, markdown, doc_key=doc_key)
        head = "\n".join((markdown or "").splitlines()[:12])
        text = (f"*{title}*\n{C.to_slack_mrkdwn(head)}\n"
                f"_（全文 {len(markdown or '')} 字，已存本地 {local.get('path','')}）_")
        r = self._post({"text": text})
        r["channel"] = "slack"
        r["local_path"] = local.get("path")
        return r
