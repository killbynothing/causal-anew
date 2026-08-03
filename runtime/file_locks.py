# -*- coding: utf-8 -*-
"""Shared process-local locks for console/runtime file writes."""
from __future__ import annotations

from threading import RLock

CONFIG_LOCK = RLock()
SESSION_FILE_LOCK = RLock()
SCENE_LOG_LOCK = RLock()
STATE_LOCK = RLock()
DELTA_LEDGER_LOCK = RLock()

