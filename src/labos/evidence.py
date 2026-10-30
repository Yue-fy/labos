"""Immutable local reference documents. Text is evidence, never executable authority."""
from __future__ import annotations

import hashlib
import json
import re
import time
from typing import Annotated, Literal

from pydantic import Field, StrictBool

from .files import json_bytes
from .models import Model
from .store import Store


class EvidenceDocument(Model):
    title: str = Field(min_length=1, max_length=200)
    source: str = Field(min_length=1, max_length=1000)
    category: Literal["manual", "protocol", "code", "paper", "run"]
    content: str = Field(min_length=1, max_length=50000)
    tags: list[Annotated[str, Field(min_length=1, max_length=60)]] = Field(default_factory=list, max_length=20)
    reviewed: StrictBool = False


def tokens(value: str) -> set[str]:
    words = set(re.findall(r"[a-z0-9_]+", value.lower()))
    for phrase in re.findall(r"[\u3400-\u9fff]+", value):
        words.update(phrase if len(phrase) == 1 else (phrase[i:i+2] for i in range(len(phrase)-1)))
    return words


class EvidenceStore:
    def __init__(self, root):
        self.store = Store(root)
        with self.store.transaction() as db:
            db.execute("""CREATE TABLE IF NOT EXISTS evidence (
                id TEXT PRIMARY KEY, source TEXT NOT NULL, version INTEGER NOT NULL,
                sha256 TEXT NOT NULL, created REAL NOT NULL, body TEXT NOT NULL,
                UNIQUE(source,version))""")

    @staticmethod
    def decode(row):
        return {**json.loads(row["body"]), **{k: row[k] for k in ("id", "version", "sha256", "created")}}

    def add(self, document: EvidenceDocument) -> dict:
        if not document.content.strip() or not document.title.strip() or not document.source.strip():
            raise ValueError("document title, source and content must contain text")
        body = json_bytes(document.model_dump()).decode()
        record_id = "ev_" + hashlib.sha256(body.encode()).hexdigest()
        sha = hashlib.sha256(document.content.encode()).hexdigest()
        with self.store.transaction() as db:
            row = db.execute("SELECT * FROM evidence WHERE id=?", (record_id,)).fetchone()
            if not row:
                version = db.execute("SELECT COALESCE(MAX(version),0)+1 FROM evidence WHERE source=?",
                                     (document.source,)).fetchone()[0]
                db.execute("INSERT INTO evidence VALUES(?,?,?,?,?,?)",
                           (record_id, document.source, version, sha, time.time(), body))
                self.store.event_db(db, "EVIDENCE_ADDED", {"id": record_id, "sha256": sha,
                                                           "version": version, "reviewed": document.reviewed})
                row = db.execute("SELECT * FROM evidence WHERE id=?", (record_id,)).fetchone()
        return self.decode(row)

    def search(self, query: str, reviewed_only=True, limit=5) -> list[dict]:
        if len(query) > 500 or not 1 <= limit <= 5:
            raise ValueError("query too long or invalid retrieval limit")
        terms = tokens(query)
        with self.store.transaction() as db:
            rows = db.execute("""SELECT e.* FROM evidence e JOIN
                (SELECT source,MAX(version) AS version FROM evidence GROUP BY source) latest
                ON e.source=latest.source AND e.version=latest.version""").fetchall()
        hits = []
        for row in rows:
            doc = self.decode(row)
            if reviewed_only and not doc["reviewed"]:
                continue
            body = doc.pop("content")
            preferred = tokens(doc["title"] + " " + " ".join(doc["tags"]))
            score = len(terms & tokens(body + " " + doc["source"])) + 3 * len(terms & preferred)
            if terms and score == 0:
                continue
            offsets = [body.lower().find(term) for term in terms if term in body.lower()]
            start = max(0, min(offsets, default=0) - 200)
            hits.append({**doc, "excerpt": body[start:start+1200], "score": score})
        return sorted(hits, key=lambda d: (-d["score"], -d["created"], d["id"]))[:limit]
