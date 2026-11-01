from __future__ import annotations

import base64
import gzip
import hashlib
import json
from pathlib import Path
import sqlite3
import zlib

from labos.files import atomic_write, json_bytes

MAX_RAW = 64 * 1024 * 1024
MAX_WIRE = 8 * 1024 * 1024
CHUNK = 32768


def digest(value):
    return hashlib.sha256(json_bytes(value)).hexdigest()


class Journal:
    def __init__(self, directory):
        self.root = Path(directory)
        self.root.mkdir(parents=True, exist_ok=True)
        self.path = self.root / "field-intents.sqlite"
        with self.db() as db:
            db.execute(
                "CREATE TABLE IF NOT EXISTS executions (task_id TEXT PRIMARY KEY, message_sha TEXT, config_sha TEXT, state TEXT, result TEXT)"
            )

    def db(self):
        db = sqlite3.connect(self.path, timeout=10)
        db.execute("PRAGMA synchronous=FULL")
        return db

    def begin(self, task_id, message_sha, config_sha):
        with self.db() as db:
            db.execute("BEGIN IMMEDIATE")
            if db.execute(
                "SELECT 1 FROM executions WHERE state IN ('intent','unresolved')"
            ).fetchone():
                raise ValueError("unresolved magnetic campaign requires local reconciliation")
            if db.execute("SELECT 1 FROM executions WHERE task_id=?", (task_id,)).fetchone():
                raise ValueError("campaign task ID has already been used; no replay")
            db.execute(
                "INSERT INTO executions VALUES(?,?,?,?,NULL)",
                (task_id, message_sha, config_sha, "intent"),
            )

    def require_resolved(self):
        with self.db() as db:
            if db.execute(
                "SELECT 1 FROM executions WHERE state IN ('intent','unresolved')"
            ).fetchone():
                raise ValueError(
                    "unresolved magnetic campaign requires local reconciliation before any device access"
                )

    def finish(self, task_id, result):
        raw = json_bytes(result)
        atomic_write(self.root / (task_id + ".json"), raw)
        with self.db() as db:
            updated = db.execute(
                "UPDATE executions SET state=?,result=? WHERE task_id=? AND state='intent'",
                (
                    "unresolved" if result["status"] == "UNKNOWN" else "finished",
                    raw.decode(),
                    task_id,
                ),
            ).rowcount
            if updated != 1:
                raise ValueError("campaign has no matching unfinished intent")

    def result(self, task_id):
        with self.db() as db:
            row = db.execute("SELECT result FROM executions WHERE task_id=?", (task_id,)).fetchone()
        if not row or row[0] is None:
            raise ValueError("no completed immutable result; never replay acquisition")
        return json.loads(row[0])


def reject_secrets(value):
    if isinstance(value, dict):
        for k, v in value.items():
            if k.lower().replace("-", "_") in {
                "token",
                "admin_token",
                "api_key",
                "authorization",
                "password",
            }:
                raise ValueError("secret field cannot be encoded into an artifact")
            reject_secrets(v)
    elif isinstance(value, list):
        for v in value:
            reject_secrets(v)


def artifact_messages(task_id, result):
    from labos.models import Identifier
    from pydantic import TypeAdapter

    TypeAdapter(Identifier).validate_python(task_id)
    reject_secrets(result)
    raw = json_bytes(result)
    if len(raw) > MAX_RAW:
        raise ValueError("raw artifact exceeds delivery bound; retain it locally")
    wire = gzip.compress(raw, mtime=0)
    if len(wire) > MAX_WIRE:
        raise ValueError("compressed artifact exceeds delivery bound; retain it locally")
    identity = hashlib.sha256(raw).hexdigest()
    pieces = [wire[i : i + CHUNK] for i in range(0, len(wire), CHUNK)]
    common = {"protocol": "labos-magnetic-v1", "task_id": task_id, "artifact_sha256": identity}
    bodies = [
        {
            **common,
            "document_type": "labos_field_artifact_chunk",
            "index": i,
            "count": len(pieces),
            "chunk_sha256": hashlib.sha256(piece).hexdigest(),
            "data_b64": base64.b64encode(piece).decode("ascii"),
        }
        for i, piece in enumerate(pieces)
    ]
    bodies.append(
        {
            **common,
            "document_type": "labos_field_artifact_manifest",
            "encoding": "gzip-canonical-json",
            "raw_bytes": len(raw),
            "wire_bytes": len(wire),
            "wire_sha256": hashlib.sha256(wire).hexdigest(),
            "count": len(pieces),
        }
    )
    return [
        {"id": "field_" + digest(body)[:50], "kind": "report", "in_reply_to": None, "body": body}
        for body in bodies
    ]


def reassemble(messages):
    manifests = [
        m["body"]
        for m in messages
        if m["body"].get("document_type") == "labos_field_artifact_manifest"
    ]
    if len(manifests) != 1:
        raise ValueError("exactly one artifact manifest required")
    meta = manifests[0]
    if (
        meta.get("encoding") != "gzip-canonical-json"
        or type(meta.get("count")) is not int
        or not 1 <= meta["count"] <= MAX_WIRE // CHUNK
        or type(meta.get("raw_bytes")) is not int
        or not 0 < meta["raw_bytes"] <= MAX_RAW
        or type(meta.get("wire_bytes")) is not int
        or not 0 < meta["wire_bytes"] <= MAX_WIRE
    ):
        raise ValueError("invalid bounded artifact manifest")
    pieces = {}
    for m in messages:
        c = m["body"]
        if (
            c.get("task_id") != meta["task_id"]
            or c.get("artifact_sha256") != meta["artifact_sha256"]
        ):
            raise ValueError("mixed artifact identities")
        if c.get("document_type") == "labos_field_artifact_manifest":
            continue
        if (
            c.get("document_type") != "labos_field_artifact_chunk"
            or c.get("count") != meta["count"]
        ):
            raise ValueError("unexpected artifact part")
        i = c.get("index")
        if type(i) is not int or not 0 <= i < meta["count"] or i in pieces:
            raise ValueError("duplicate or invalid artifact index")
        try:
            data = base64.b64decode(c["data_b64"], validate=True)
        except (ValueError, KeyError) as exc:
            raise ValueError("invalid artifact encoding") from exc
        if len(data) > CHUNK or hashlib.sha256(data).hexdigest() != c["chunk_sha256"]:
            raise ValueError("artifact chunk hash mismatch")
        pieces[i] = data
    if len(pieces) != meta["count"]:
        raise ValueError("artifact is incomplete")
    wire = b"".join(pieces[i] for i in range(meta["count"]))
    if len(wire) != meta["wire_bytes"] or hashlib.sha256(wire).hexdigest() != meta["wire_sha256"]:
        raise ValueError("compressed artifact hash mismatch")
    decoder = zlib.decompressobj(31)
    try:
        raw = decoder.decompress(wire, MAX_RAW + 1)
    except zlib.error as exc:
        raise ValueError("invalid compressed artifact") from exc
    if (
        len(raw) != meta["raw_bytes"]
        or not decoder.eof
        or decoder.unused_data
        or decoder.unconsumed_tail
        or hashlib.sha256(raw).hexdigest() != meta["artifact_sha256"]
    ):
        raise ValueError("raw artifact hash/size mismatch")
    result = json.loads(raw)
    if json_bytes(result) != raw:
        raise ValueError("artifact is not canonical finite JSON")
    return result
