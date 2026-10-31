# Automatic LabOS assistant correspondence

The operator has approved implementing the previously described background listener and Codex invocation. The goal is to remove the need to announce each reply manually. Existing authenticated HTTPS correspondence remains the transport. The interactive IDE chats are separate from these background workers.

## Approach

Use one persistent polling worker per PC conversation on each end, with SQLite state and an OS instance lock. A message-triggered `codex exec` run is simpler to deploy than binding to an IDE's private session. A Codex App Server integration could preserve interactive threads but requires additional session ownership and lifecycle integration. Keeping a model waiting in a chat loop wastes model context; network polling requires no model inference.

Workers archive all peer messages but invoke a model only for the explicit `labos_auto_task` protocol. The PC returns `labos_auto_result`; the central worker automatically reviews a matching result and returns a terminal `labos_auto_review`. Reviews and ordinary correspondence do not trigger another response. This first version supports report analysis and review of supplied static code/context, not arbitrary tool execution or physical control.

## Requirements

- Protocol `labos-agent-v1`; task, result and review carry a common task ID.
- Tasks use `kind: note`; results/reviews use `kind: reply` with the peer envelope ID.
- Persist cursor, message, generated response and retry state. Cache output before sending it; retry ambiguous sends with the same immutable message ID and body.
- Two model attempts per input, with a 60-second delay after a failed attempt. Network failures retry without re-running a cached model response. An abrupt crash before model output is committed can repeat inference; delivery remains idempotent.
- Default polling interval 10 seconds. No model call for an empty inbox, ordinary note, result without a matching task, or terminal review.
- Codex backend uses a fresh non-interactive run with read-only sandbox, no inherited user configuration, shell, MCP/apps, plugins, browser or multi-agent tools. Supply only approved static context files and the task as data. Do not resume an unrelated interactive chat.
- Central may fall back to the existing loopback model API when Codex fails. Backend choice and failures are recorded; no automatic claim of physical readiness.
- Separate worker state from execution-Agent journals. Never open a driver, import production software, register instruments or submit experiment commands.
- English scripts, examples, logs and instructions. Windows startup uses the current user's Startup folder without requesting administrator rights.
- Ship a new portable cryostat package with the existing PC identity and credential. Keep central credentials on the server. The PC requires a one-time package transfer/startup; subsequent tasks and replies need no operator relay.

## Acceptance

Test actual message APIs, restart recovery, ambiguous delivery, model failures, terminal-message suppression, wrong task references, credential filtering and provider process contracts. Run the existing suite and a real central/local-model task. Activate the central service, queue a bounded demonstration task, and ship exact instructions for the PC assistant. Mark remote automatic processing unverified until the target worker returns its result.
