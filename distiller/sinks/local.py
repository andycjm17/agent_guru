#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
sinks/local.py — 本地渠道（零依赖，任何人可用）

不依赖飞书/任何账号。把 DM/报告写到 data/out/ 下的 markdown，并打印到控制台。
这是「解绑飞书」后人人可跑的兜底 sink：没装飞书、没配 Slack 也能看到全部产出。
"""
from __future__ import annotations

import re

from .. import config as C
from .base import Sink


def _slug(s: str, default: str) -> str:
    s = re.sub(r"[^a-zA-Z0-9_\-]+", "-", (s or "").strip()).strip("-")
    return s[:60] or default


class LocalSink(Sink):
    key = "local"
    label = "本地文件 (data/out)"

    def available(self) -> bool:
        return True   # 永远可用

    def send_dm(self, markdown: str, idempotency_key: str) -> dict:
        C.OUT_DIR.mkdir(parents=True, exist_ok=True)
        fn = C.OUT_DIR / f"dm-{_slug(idempotency_key, 'msg')}.md"
        try:
            fn.write_text(markdown or "", encoding="utf-8")
        except OSError as e:
            return {"ok": False, "error": str(e)}
        print(f"\n[local sink] DM 已写本地 → {fn}\n{'-'*48}\n{markdown}\n{'-'*48}")
        C.log(f"sink[local]: DM → {fn}")
        return {"ok": True, "path": str(fn), "channel": "local"}

    def publish_report(self, title: str, markdown: str,
                       doc_key: str = "", docx_xml: str = "") -> dict:
        C.OUT_DIR.mkdir(parents=True, exist_ok=True)
        fn = C.OUT_DIR / f"{_slug(doc_key or title, 'report')}.md"
        body = f"# {title}\n\n{markdown or ''}\n"
        try:
            fn.write_text(body, encoding="utf-8")
        except OSError as e:
            return {"ok": False, "error": str(e)}
        print(f"\n[local sink] 报告已写本地 → {fn}")
        C.log(f"sink[local]: 报告 [{doc_key or title}] → {fn}")
        return {"ok": True, "path": str(fn), "url": fn.as_uri(), "channel": "local"}
