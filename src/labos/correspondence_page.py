"""Validate an entire correspondence page before any durable ingestion."""
import re

MAX_SEQUENCE = 9223372036854775807
MAX_PAGE_MESSAGES = 100
IDENTIFIER = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,79}\Z")


class ProtocolUnavailable(RuntimeError):
    pass


def validate_page(response, agent_id, sender, after):
    try:
        page = response.json()
    except (ValueError, RecursionError):
        raise ProtocolUnavailable("protocol_unavailable") from None
    def sequence(value):
        return type(value) is int and 0 <= value <= MAX_SEQUENCE
    def identifier(value):
        return isinstance(value, str) and IDENTIFIER.fullmatch(value) is not None
    if (not isinstance(page, dict) or not isinstance(page.get("messages"), list)
            or len(page["messages"]) > MAX_PAGE_MESSAGES
            or not sequence(page.get("next_cursor"))):
        raise ProtocolUnavailable("protocol_unavailable")
    previous, identities = after, set()
    for message in page["messages"]:
        if (not isinstance(message, dict) or not identifier(message.get("id"))
                or message["id"] in identities or message.get("agent_id") != agent_id
                or message.get("sender") != sender or not sequence(message.get("sequence"))
                or message["sequence"] <= previous
                or not isinstance(message.get("kind"), str)
                or message["kind"] not in {"report", "reply", "note"}
                or not isinstance(message.get("body"), dict)
                or (message.get("in_reply_to") is not None and not identifier(message["in_reply_to"]))):
            raise ProtocolUnavailable("protocol_unavailable")
        previous = message["sequence"]
        identities.add(message["id"])
    if page["next_cursor"] != previous:
        raise ProtocolUnavailable("protocol_unavailable")
    return page
