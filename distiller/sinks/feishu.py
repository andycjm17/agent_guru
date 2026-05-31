#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
sinks/feishu.py — 飞书渠道（DM + Lark 文档）

send_dm        → C.lark_dm（bytedcli lark im messages-send --as bot，幂等键防重）
publish_report → lark-cli docs +create/+update overwrite（DocxXML 富文本；token 按 doc_key 复用）

这是把原先散在 config.lark_dm / render.push_to_lark 的飞书耦合收敛到一个 sink。
docx_xml 由 render 层提供（飞书要 DocxXML）；没有 docx_xml 时降级为纯文本 markdown 推送。
"""
from __future__ import annotations

import re
import pathlib

from .. import config as C
from .base import Sink

_URL_RE = re.compile(r"https?://[^\s\"'<>]*larkoffice\.com/[^\s\"'<>]+")


def _extract_doc_ref(obj):
    """从 lark-cli 返回 JSON 里递归找 (url, token)。"""
    url = token = None

    def walk(o):
        nonlocal url, token
        if isinstance(o, dict):
            for k, v in o.items():
                kl = k.lower()
                if isinstance(v, str):
                    if "url" in kl and "larkoffice.com" in v and not url:
                        url = v
                    elif kl in ("document_id", "doc_token", "token", "obj_token", "objtoken") and not token:
                        token = v
                walk(v)
        elif isinstance(o, list):
            for x in o:
                walk(x)

    walk(obj)
    return url, token


def _token_file(doc_key: str) -> pathlib.Path:
    return C.LARK_DOC_FILE if (doc_key in ("", "map")) else C.DATA_DIR / f"lark_doc_{doc_key}.json"


class FeishuSink(Sink):
    key = "feishu"
    label = "飞书 (Feishu/Lark)"

    def available(self) -> bool:
        try:
            return bool(C.resolve_lark_user_id())
        except Exception:
            return False

    def send_dm(self, markdown: str, idempotency_key: str) -> dict:
        ok = C.lark_dm(markdown, idempotency_key=idempotency_key)
        return {"ok": bool(ok), "channel": "feishu-dm"}

    def publish_report(self, title: str, markdown: str,
                       doc_key: str = "", docx_xml: str = "") -> dict:
        # 飞书要 DocxXML；没有就用一个最简 XML 包裹 markdown（标题 + 段落）
        xml = docx_xml or ""
        if not xml:
            safe = (markdown or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            paras = "".join(f"<p>{ln}</p>" for ln in safe.splitlines() if ln.strip())
            esc_title = (title or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            xml = f"<title>{esc_title}</title>{paras}"

        rel = f"data/_sink_feishu_{doc_key or 'doc'}.xml"
        (C.PROJECT_ROOT / rel).parent.mkdir(parents=True, exist_ok=True)
        (C.PROJECT_ROOT / rel).write_text(xml, encoding="utf-8")

        tf = _token_file(doc_key)
        stored = C.load_json(tf, default={}) or {}
        doc_ref = stored.get("url") or stored.get("token")
        if doc_ref:
            cmd = [C.LARK_CLI, "docs", "+update", "--api-version", "v2",
                   "--doc", doc_ref, "--command", "overwrite",
                   "--content", f"@{rel}", "--doc-format", "xml"]
            action = "update"
        else:
            cmd = [C.LARK_CLI, "docs", "+create", "--api-version", "v2",
                   "--content", f"@{rel}", "--doc-format", "xml"]
            action = "create"

        C.log(f"sink[feishu]: lark {action} ({doc_key or 'doc'})")
        r = C.run(cmd, timeout=180, cwd=str(C.PROJECT_ROOT))
        obj = C.extract_json(r.stdout or "")
        url, token = _extract_doc_ref(obj) if obj else (None, None)
        if not url:
            m = _URL_RE.search(r.stdout or "")
            url = m.group(0) if m else None
        if action == "create" and (url or token):
            C.save_json(tf, {"url": url, "token": token, "created_at": C.now_utc().isoformat()})
            try:
                tf.chmod(0o600)
            except OSError:
                pass
        if isinstance(obj, dict) and "ok" in obj:
            ok = bool(obj.get("ok"))
        else:
            ok = bool(url or token) or (r.returncode == 0)
        return {"ok": ok, "action": action, "url": url or doc_ref, "channel": "feishu-doc"}
