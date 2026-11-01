"""Private, size-bounded local pilot event storage; no acquisition authority."""
from __future__ import annotations

import os
import threading
from pathlib import Path

from .files import json_bytes

MAX_EVENT_BYTES = 4096
MAX_JOURNAL_BYTES = 1024 * 1024


class EventJournal:
    """Keep at most one active MiB and one previous MiB of JSON records.

    Callers supply only public structural metadata and isolate write failures.
    Raw reports, exception messages, configuration and instrument data do not
    belong in this journal.
    """

    def __init__(self, directory: Path):
        self.path = directory / "events.jsonl"
        self._lock = threading.Lock()

    def append(self, record):
        content = json_bytes(record) + b"\n"
        if len(content) > MAX_EVENT_BYTES:
            raise ValueError("pilot event exceeds bounded record size")
        with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            if self.path.exists() and self.path.stat().st_size + len(content) > MAX_JOURNAL_BYTES:
                self.path.replace(self.path.with_name("events.jsonl.1"))
            descriptor = os.open(self.path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
            try:
                if os.name != "nt":
                    os.fchmod(descriptor, 0o600)
                with os.fdopen(descriptor, "ab") as handle:
                    descriptor = None
                    handle.write(content)
            finally:
                if descriptor is not None:
                    os.close(descriptor)
