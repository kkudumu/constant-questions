# constantquestions — Freshservice "where to ask/request X" auto-drafter

## Context

You repeatedly answer the same routing-style questions in Freshservice tickets ("where do I request X?", "who do I ask about Y?"). The canonical answers live in **ClickUp docs**, not in your head and not in Freshservice's KB. You want a Claude Code-driven, on-demand workflow that drafts replies for you so you can review-and-send instead of re-typing.

Decisions locked in from discovery:
- **KB source:** ClickUp.
- **Send mode:** Draft as a **private note** on the ticket. You review and send. Never auto-send.
- **Trigger:** On-demand — you invoke a Claude Code slash command on your queue.
- **Scope:** Only "where do I request/ask about X" routing questions. Everything else is skipped, not drafted.

Research highlights backing this design (full briefs in conversation):
- The existing `freshservice_mcp` MCP server is already wired into your Claude Code (`mcp__freshservice-mcp__*` tools). Use it; don't re-implement the API client.
- Best-practice IT-desk auto-response stacks **draft for review** at first launch and only graduate to auto-send after a few weeks of measured agent-send-through rate.
- Always cite the source doc in the draft. Drafts that can't cite a KB article are the #1 hallucination source — skip those tickets instead of inventing an answer.

## Approach

Build a small local project at `C:\Users\kkudu\Documents\Code\constantquestions`. It has three moving parts:

1. **ClickUp KB mirror** — a Python sync script pulls relevant ClickUp docs to local markdown in `kb/`. Cheap, greppable, no vector DB needed for v1 since "where to request X" answers are short and keyword-y.
2. **`/triage` slash command** — orchestrates: pull tickets via Freshservice MCP → classify each as in-scope or not → search local KB → draft a private note via MCP. Idempotent; never re-drafts on a ticket already touched.
3. **Hard safety rails** — exclusion list (VIPs, security keywords), required KB citation, "DRAFT — review before sending" header on every note, hidden marker (`<!-- cq-bot:v1 -->`) for idempotency.

## Project layout

```
constantquestions/
├── .claude/
│   └── commands/
│       ├── triage.md          # /triage slash command
│       └── sync-kb.md         # /sync-kb slash command
├── config/
│   ├── exclusions.yaml        # VIP emails, exclusion keyword regex
│   └── prompts/
│       ├── classifier.md      # "is this a routing question?" prompt
│       └── draft_reply.md     # reply template
├── scripts/
│   └── sync_clickup_kb.py     # ClickUp API → kb/*.md
├── kb/                        # local cache, gitignored
│   └── .gitkeep
├── .env.example
├── .gitignore
├── requirements.txt
└── README.md
```

## Component 1 — ClickUp KB sync (`scripts/sync_clickup_kb.py`)

- Uses ClickUp v2 API (`https://api.clickup.com/api/v2/`). Auth: `Authorization: <personal token>` from `.env`.
- Walks configured `CLICKUP_DOC_FOLDER_IDS` (a comma-separated list — you'll seed this with the folders that hold your routing docs).
- For each doc: writes `kb/<slug>.md` with YAML frontmatter:
  ```yaml
  ---
  clickup_doc_id: <id>
  title: <title>
  url: https://app.clickup.com/<...>
  date_updated: <iso8601>
  ---
  ```
- Incremental: skips fetching if local `date_updated` ≥ remote.
- Stdlib + `requests` + `pyyaml` + `python-dotenv`. No heavy deps.
- Run via `/sync-kb` slash command (or `python scripts/sync_clickup_kb.py` directly).

## Component 2 — `/triage` slash command (`.claude/commands/triage.md`)

The command file gives Claude an explicit playbook. Each step uses MCP tools you already have.

Args:
- `--limit N` (default 10) — max tickets to process per run
- `--since <duration>` (default 24h)
- `--dry-run` — classify and search KB but skip the `create_ticket_note` write

Workflow:
1. **List candidates:** `mcp__freshservice-mcp__filter_tickets` with status=Open, created within window, assigned to you or unassigned. Cap at `--limit`.
2. **Idempotency check:** for each ticket, `list_all_ticket_conversation` and skip if any prior note body contains `<!-- cq-bot:v1 -->`.
3. **Pull ticket detail:** `get_ticket_by_id` for subject + description.
4. **Hard-exclude:**
   - Subject/body regex match against `config/exclusions.yaml` keywords (security, breach, incident, exec, urgent escalation, PII patterns).
   - Requester email matches VIP list (resolve via `get_requester_id` then check email).
   - Has attachments → skip (avoid OCR/PII rabbit hole in v1).
5. **Classify (LLM, strict):** apply `config/prompts/classifier.md` — yes/no whether this is purely a "where do I request/ask about X" routing question. Skip on no.
6. **Search KB:** Grep `kb/*.md` for keywords from the ticket subject/body. Read top 1–3 candidate files. If no candidate confidently maps to the requested resource, **skip** (do not invent an answer) and log "no_kb_match".
7. **Draft reply:** apply `config/prompts/draft_reply.md`. Required structure: short greeting → 2-4 sentence answer with the routing target → ClickUp doc link → canned sign-off. Header line: `**DRAFT — review before sending**`. Footer marker: `<!-- cq-bot:v1 -->`.
8. **Post private note:** `create_ticket_note` with `private: true`.
9. **Report:** print per-ticket table — `id | subject | action (drafted/skipped:reason/excluded:reason) | kb_source`.

## Component 3 — safety rails

- `config/exclusions.yaml` is the single source of truth for who/what is off-limits. Cheap to extend.
- The classifier prompt is **strict by design**: the ticket must be asking *where* to go, not *how* to do it or *what is broken*. Anything ambiguous → skip.
- Every drafted note carries the DRAFT header and the bot marker comment. You can search Freshservice for `cq-bot:v1` to audit.
- `.env` is gitignored; `kb/` is gitignored (it's a cache; ClickUp is the source of truth).

## Critical file references

- New: `.claude/commands/triage.md`, `.claude/commands/sync-kb.md`, `scripts/sync_clickup_kb.py`, `config/exclusions.yaml`, `config/prompts/classifier.md`, `config/prompts/draft_reply.md`, `.env.example`, `.gitignore`, `requirements.txt`, `README.md`.
- Reused: existing Freshservice MCP server tools (`mcp__freshservice-mcp__filter_tickets`, `get_ticket_by_id`, `list_all_ticket_conversation`, `create_ticket_note`, `get_requester_id`). No code to write here — the MCP is already authenticated in your Claude Code.

## Verification

End-to-end checks before declaring v1 done:

1. **KB sync works:** Drop a real ClickUp folder ID in `.env`, run `/sync-kb`. Confirm `kb/` populates with markdown matching docs; spot-check 2–3 files for content fidelity and frontmatter.
2. **Dry run:** `/triage --dry-run --limit 5`. Verify report shows accurate classification per ticket and zero Freshservice writes (check no new notes appeared on those tickets).
3. **Real draft:** Pick one in-scope ticket, run `/triage --limit 1`. Verify a private note appears with the DRAFT header, contains a real ClickUp doc link, and is not visible to the requester.
4. **Idempotent re-run:** Re-run `/triage` immediately. The same ticket must be skipped with reason `already_drafted`.
5. **Exclusion path:** Add your own email to `exclusions.yaml` VIPs temporarily, file a test ticket, run `/triage`. Confirm `excluded:vip`. Revert the config.
6. **No-KB-match skip:** File a fake "where do I request X" ticket for an X that has no doc in `kb/`. Confirm the bot skips with `no_kb_match` rather than hallucinating.

## Out of scope for v1 (deliberate)

- Auto-send. Stays in draft mode until you've measured ≥70% send-through over a few weeks.
- Embedding/vector search. Markdown grep handles routing-style queries fine; revisit only if you hit recall problems.
- Webhook listener / scheduled poll. Pure on-demand.
- Coverage of how-to questions, password resets, software-install requests. Easy to add later by relaxing the classifier — keep v1 narrow.
- ClickUp write-back, KB authoring, analytics dashboard.
