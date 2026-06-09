#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""tests/util.py — 测试共享底座。

TmpDataCase 把 distiller.config 里所有会落盘的路径整体指到一个临时目录，
保证测试绝不读写真实的 data/ logs/ ~/.claude 等位置，跑完自动清理。
"""
from __future__ import annotations

import pathlib
import shutil
import tempfile
import unittest
from unittest import mock

from distiller import config as C


class TmpDataCase(unittest.TestCase):
    def setUp(self):
        self.tmp = pathlib.Path(tempfile.mkdtemp(prefix="wd-test-"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        data = self.tmp / "data"
        for attr, value in {
            "DATA_DIR": data,
            "STATE_DIR": data / "state",
            "LOG_DIR": self.tmp / "logs",
            "BACKUP_DIR": data / "backups",
            "OUT_DIR": data / "out",
            "DIGESTS_FILE": data / "digests.json",
            "MAP_FILE": data / "map.json",
            "SAVINGS_LEDGER": data / "savings_ledger.jsonl",
            "SKILLS_CONFIG": data / "skills_config.json",
            "IDENTITY_CACHE": data / "identity.json",
            "PROCESSED_FILE": data / "state" / "processed.json",
            "MEETING_STATE": self.tmp / "meeting" / "processed.json",
            "CLAUDE_PROJECTS": self.tmp / "claude_projects",
        }.items():
            patcher = mock.patch.object(C, attr, value)
            patcher.start()
            self.addCleanup(patcher.stop)
