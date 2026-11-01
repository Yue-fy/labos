from __future__ import annotations

import ssl
import httpx

from labos.config import AgentConfig
from labos.files import contains_credential, json_bytes

from .records import digest


class Channel:
    def __init__(self, config, agent_id=None, transport=None):
        self.pc = isinstance(config, AgentConfig)
        self.agent_id = config.agent_id if self.pc else agent_id
        if self.agent_id != "cryostat-pc":
            raise ValueError("field channel requires the commissioned PC")
        self.secret = config.token if self.pc else config.admin_token
        verify = ssl.create_default_context(cafile=str(config.ca_file)) if self.pc and config.ca_file else True
        self.client = httpx.Client(
            base_url=config.server_url if self.pc else f"http://127.0.0.1:{config.port}",
            headers={"Authorization": "Bearer " + self.secret}, timeout=15, verify=verify,
            trust_env=False, proxy=config.proxy_url if self.pc else None, transport=transport)
        self.path = f"/api/agents/{self.agent_id}/messages"

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.client.close()

    def messages(self):
        after = 0
        for _ in range(1000):
            r = self.client.get(self.path, params={"after": after, "limit": 100,
                                                  "sender": "central" if self.pc else "pc"})
            r.raise_for_status()
            batch = r.json()
            values = batch['messages']
            if not values:
                return
            for message in values:
                yield message
            cursor = batch['next_cursor']
            if type(cursor) is not int or cursor <= after:
                raise ValueError("correspondence cursor did not advance")
            after = cursor
        raise ValueError("correspondence scan bound exceeded")

    def fetch(self, message_id):
        for message in self.messages():
            if message.get('id') == message_id:
                content = {k: message.get(k) for k in ('id', 'kind', 'in_reply_to', 'body')}
                if digest(content) != message.get('sha256'):
                    raise ValueError("correspondence envelope hash mismatch")
                return message
        return None

    def send(self, message):
        if contains_credential(message, [self.secret]) or len(json_bytes(message)) > 65536:
            raise ValueError("message exceeds privacy or size boundary")
        r = self.client.post(self.path, json=message)
        r.raise_for_status()
        receipt = r.json()['message']
        if receipt.get('sha256') != digest(message) or receipt.get('id') != message['id']:
            raise ValueError("central correspondence receipt mismatch")
        return receipt
