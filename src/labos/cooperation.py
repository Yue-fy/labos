"""Durable assistant correspondence, separate from instrument execution."""
from __future__ import annotations

import hashlib
import json
import ssl
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

import httpx

from .config import AgentConfig, CentralConfig, load_config
from .files import atomic_write, contains_credential, json_bytes
from .models import Identifier, Model

MAX_MESSAGE_BYTES = 65536


class Message(Model):
    id: Identifier
    kind: Literal["report", "reply", "note"] = "report"
    in_reply_to: Identifier | None = None
    body: dict


class Correspondence:
    def __init__(self, store):
        self.store = store
        with store.transaction() as db:
            db.execute("""CREATE TABLE IF NOT EXISTS correspondence (
                sequence INTEGER PRIMARY KEY AUTOINCREMENT,
                id TEXT NOT NULL, agent_id TEXT NOT NULL, sender TEXT NOT NULL,
                sha256 TEXT NOT NULL, created REAL NOT NULL, body TEXT NOT NULL,
                UNIQUE(agent_id,id))""")

    @staticmethod
    def decode(row):
        return {**json.loads(row["body"]), "sequence": row["sequence"],
                "agent_id": row["agent_id"], "sender": row["sender"],
                "sha256": row["sha256"],
                "created_at": datetime.fromtimestamp(row["created"], timezone.utc).isoformat()}

    def add(self, agent_id, sender, message: Message, credentials):
        content = json_bytes(message.model_dump())
        if len(content) > MAX_MESSAGE_BYTES:
            raise ValueError("message exceeds 64 KiB")
        sensitive_keys = {"token", "admin_token", "api_key", "authorization", "password"}

        def has_secret_field(value):
            if isinstance(value, dict):
                return any(str(k).lower().replace("-", "_") in sensitive_keys or
                           has_secret_field(v) for k, v in value.items())
            if isinstance(value, list):
                return any(has_secret_field(v) for v in value)
            return False

        if has_secret_field(message.body) or contains_credential(message.model_dump(), credentials):
            raise ValueError("credentials cannot be stored in correspondence")
        digest = hashlib.sha256(content).hexdigest()
        with self.store.transaction() as db:
            previous = db.execute("SELECT * FROM correspondence WHERE agent_id=? AND id=?",
                                  (agent_id, message.id)).fetchone()
            if previous:
                if previous["sender"] != sender or previous["sha256"] != digest:
                    raise ValueError("message ID already has different content or sender")
                return self.decode(previous)
            if message.kind == "reply" and not message.in_reply_to:
                raise ValueError("a reply requires in_reply_to")
            if message.in_reply_to:
                reference = db.execute("SELECT sender FROM correspondence WHERE agent_id=? AND id=?",
                                       (agent_id, message.in_reply_to)).fetchone()
                if not reference or (message.kind == "reply" and reference["sender"] == sender):
                    raise ValueError("reply target must exist in this PC conversation and belong to the peer")
            db.execute("INSERT INTO correspondence(id,agent_id,sender,sha256,created,body) VALUES(?,?,?,?,?,?)",
                       (message.id, agent_id, sender, digest, time.time(), content.decode()))
            self.store.event_db(db, "CORRESPONDENCE_STORED", {"agent_id": agent_id,
                                "message_id": message.id, "sender": sender, "sha256": digest})
            row = db.execute("SELECT * FROM correspondence WHERE agent_id=? AND id=?",
                             (agent_id, message.id)).fetchone()
            return self.decode(row)

    def list(self, agent_id, after=0, limit=100, sender=None):
        with self.store.transaction() as db:
            rows = db.execute("""SELECT * FROM correspondence WHERE agent_id=? AND sequence>?
                AND (? IS NULL OR sender=?) ORDER BY sequence LIMIT ?""",
                              (agent_id, after, sender, sender, limit)).fetchall()
        messages = [self.decode(row) for row in rows]
        return {"messages": messages, "next_cursor": messages[-1]["sequence"] if messages else after,
                "effect": "stored_only"}


def add_parser(sub):
    parser = sub.add_parser("cooperate", help="send or receive assistant reports; never executes instruments")
    parser.add_argument("action", choices=["send", "pull"])
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--role", choices=["pc", "central"], required=True)
    parser.add_argument("--agent", help="PC ID; required for the central role")
    parser.add_argument("--server-url")
    parser.add_argument("--input", type=Path, help="JSON object or UTF-8 Markdown/text report")
    parser.add_argument("--output", type=Path, help="save the received batch or send receipt")
    parser.add_argument("--kind", choices=["report", "reply", "note"], default="report")
    parser.add_argument("--in-reply-to")
    parser.add_argument("--message-id", help="optional ID; otherwise derived from PC, role and message content")
    parser.add_argument("--after", type=int, default=0, help="receive messages after this sequence")


def run(args, transport=None):
    central = args.role == "central"
    config = load_config(args.config, CentralConfig if central else AgentConfig)
    agent_id = args.agent if central else config.agent_id
    if central and agent_id not in config.agents:
        raise ValueError("--agent must name a registered PC")
    if not central and args.agent and args.agent != agent_id:
        raise ValueError("--agent does not match this PC configuration")
    if args.after < 0:
        raise ValueError("--after must be nonnegative")
    if not central and args.server_url and args.server_url.rstrip("/") != config.server_url:
        raise ValueError("the PC role must use its provisioned server URL")
    url = args.server_url or (f"http://127.0.0.1:{config.port}" if central else config.server_url)
    verify = ssl.create_default_context(cafile=str(config.ca_file)) if not central and config.ca_file else True
    credential = config.admin_token if central else config.token
    with httpx.Client(base_url=url, timeout=15, verify=verify, trust_env=False, transport=transport,
                      proxy=config.proxy_url if not central else None,
                      headers={"Authorization": "Bearer " + credential}) as client:
        path = f"/api/agents/{agent_id}/messages"
        if args.action == "send":
            if not args.input:
                raise ValueError("send requires --input")
            if args.input.stat().st_size > MAX_MESSAGE_BYTES:
                raise ValueError("input report exceeds 64 KiB; send a focused excerpt")
            source = args.input.read_text(encoding="utf-8-sig")
            body = json.loads(source) if args.input.suffix.lower() == ".json" else {
                "document_type": "text_report", "title": args.input.name, "content": source}
            if not isinstance(body, dict):
                raise ValueError("JSON input must be an object")
            fields = {"kind": args.kind, "in_reply_to": args.in_reply_to, "body": body}
            message_id = args.message_id or "msg_" + hashlib.sha256(json_bytes({
                "agent_id": agent_id, "sender": args.role, **fields})).hexdigest()[:40]
            payload = Message(id=message_id, **fields).model_dump()
            if len(json_bytes(payload)) > MAX_MESSAGE_BYTES:
                raise ValueError("encoded message exceeds 64 KiB; shorten the report")
            response = client.post(path, json=payload)
        else:
            response = client.get(path, params={"after": args.after,
                                  "sender": "pc" if central else "central"})
        response.raise_for_status()
        result = response.json()
    if args.output:
        atomic_write(args.output, json_bytes(result))
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0
