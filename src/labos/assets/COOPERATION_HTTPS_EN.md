# Assistant reports over LabOS HTTPS (0.2.2)

The central service now has a durable, authenticated correspondence channel. Both assistants can use it through terminal tools. Reports travel over the same central HTTPS origin as the PC Agent, with each PC's own credential. No SSH, GitHub relay or operator file copying is required once the package and credentials are provisioned.

This channel stores correspondence only. It never runs a report's code, applies settings, starts an experiment or clears a device fault. It does not automatically wake a chat session or invoke an LLM: the assistant must call the tools, or a separately configured worker must do so.

LabOS 0.2.3 supplies that optional background report worker. See [AUTOMATIC_COOPERATION_EN.md](AUTOMATIC_COOPERATION_EN.md) for one-time setup and the explicit task protocol. Ordinary correspondence keeps its existing behavior.

## PC: read central messages

Run from the root of the **0.2.2** PC package:

```powershell
.\python\python.exe -m labos cooperate pull --role pc --config config.yaml --output handoff\inbox-001.json
```

Read `handoff\inbox-001.json`. The response includes `messages` and `next_cursor`. For subsequent reads, pass `--after` with the last processed cursor and use a new output filename. Keep that cursor and the last processed message ID in `handoff/STATUS_EN.md`; pulling does not delete messages.

## PC: send a report

Prepare a sanitized UTF-8 Markdown/text report or JSON object, then run:

```powershell
.\python\python.exe -m labos cooperate send --role pc --config config.yaml --input handoff\pc-intake.json --kind report --output handoff\send-receipt.json
```

The CLI uses the configured PC identity and token without printing the token. A successful receipt has `effect: stored_only` and an immutable message ID. Retry the same command with the same input after an ambiguous network response: its default content-derived ID is stable, so identical content is stored once. A different report should carry a new report revision/observation time; an optional `--message-id` can identify a deliberately new message.

To answer a specific central message, use `--kind reply --in-reply-to MESSAGE_ID`. Use the received envelope's `id`, not the document's internal report ID. Replies must target the peer in the same PC conversation.

## Central: read and answer

Use the central configuration on the server. Replace example PC/configuration paths with the actual registered deployment:

```bash
.venv/bin/python -m labos cooperate pull --role central \
  --config deployments/lab-01/central/config.yaml --agent cryostat-pc \
  --output deployments/lab-01/central/handoff/inbox-001.json

.venv/bin/python -m labos cooperate send --role central \
  --config deployments/lab-01/central/config.yaml --agent cryostat-pc \
  --input path/to/central-reply.md --kind reply --in-reply-to MESSAGE_ID
```

Use `--kind note` for an initial central message that does not answer an inbox message. Central tools default to the server's local HTTP listener; the laboratory PC uses its provisioned HTTPS URL. Keep the central operator credential on the central server.

## HTTP contract

| Operation | Endpoint |
| --- | --- |
| Store a message | `POST /api/agents/{agent_id}/messages` |
| Read messages | `GET /api/agents/{agent_id}/messages?after=0&limit=100` |
| Read peer messages only | Add `sender=central` or `sender=pc`; the CLI selects the peer automatically |

The POST envelope has `id`, `kind` (`report`, `reply`, `note`), optional `in_reply_to`, and an object `body`. The CLI wraps the input document into this envelope. The server derives sender identity from authentication, limits each request to 64 KiB, rejects credential fields/known credential values, and stores immutable records with sequence, timestamp and hash. The operator can access registered PC conversations; a PC credential can access only its own conversation.

Messages do not require registering another execution Agent or taking its instrument session. Sending a report does not refresh a PC heartbeat or prove instrument readiness. Messages remain in central SQLite across service restarts; a cursor and immutable IDs support orderly consumption. The client validates TLS and uses only the PC's provisioned origin.

## First cryostat task

1. Use the personalized cryostat connection package. The generic package alone has no credential.
2. Run Install, then Doctor, and pull the initial central note.
3. Send the local network/runtime result and the intake report. Do not rerun instrument initialization.
4. Record actual output and message receipt IDs. Wait for or retrieve the central response through the same tools.

The connectivity package has an empty instrument list. Cryostat's existing application, vendor environment, station lease and shutdown semantics are unchanged. Real integration remains a separate reviewed step.
