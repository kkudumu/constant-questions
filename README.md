# constantquestions

Auto-drafts private Freshservice ticket notes for IT routing questions ("where do I request X?"). Human reviews and sends — no auto-sending.

## How it works

- `/sync-kb` pulls docs from ClickUp into `kb/` as local Markdown files
- `/triage` fetches open Freshservice tickets, runs each through the classifier prompt, and drafts a private note for any ticket identified as a routing question
- Drafted notes are written to Freshservice with a `DRAFT` header and `cq-bot:v1` marker — they sit there until a human reviews and sends the reply
- Tickets that don't match the routing classifier, or whose requester is on the exclusion list, are skipped without modification

## Setup

```
pip install -r requirements.txt
```

Copy `.env.example` to `.env` and fill in:

```
CLICKUP_TOKEN=
CLICKUP_WORKSPACE_ID=
CLICKUP_DOC_FOLDER_IDS=   # comma-separated folder IDs to sync
```

**Freshservice MCP** must be configured in Claude Code (`mcp__freshservice-mcp` tools). If it is not connected, `/triage` will fail with MCP tool errors.

**Run `/sync-kb` before the first `/triage`** to populate `kb/`. The classifier has no KB to reference until this is done.

## Usage

```
/sync-kb                         # pull ClickUp docs to kb/
/triage                          # process open tickets (last 24h, up to 10)
/triage --limit 5 --since 48h    # custom time window and ticket cap
/triage --dry-run                # classify only, no Freshservice writes
```

## Safety rails

- Notes are drafted only — never sent automatically
- Every draft is prefixed with a `DRAFT` header so it is obvious in Freshservice
- All drafts are tagged `cq-bot:v1` for auditability and easy bulk-delete
- Requesters in `config/exclusions.yaml` (VIP emails, exclusion keywords) are skipped entirely
- The classifier prompt is strict: ambiguous tickets are not classified as routing questions
- If no matching KB doc is found, the ticket is skipped rather than guessing

## Customizing

**Add VIPs or exclusion keywords:** edit `config/exclusions.yaml`. Both email addresses and subject-line keywords are supported.

**Extend classifier scope:** edit `config/prompts/classifier.md`. The prompt defines what counts as a routing question — adjusting the examples or scope there changes what `/triage` will act on.

## Out of scope for v1

Auto-send, vector search over KB, and webhook-triggered triage.
