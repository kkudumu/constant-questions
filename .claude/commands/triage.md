# triage

Auto-draft private Freshservice routing-answer notes for open tickets by classifying them, searching the KB, and posting a vetted reply — all without human copy-paste.

## Arguments

Parse these from `$ARGUMENTS` before starting any work:

| Argument | Default | Meaning |
|---|---|---|
| `--limit N` | `10` | Maximum number of tickets to process in one run |
| `--since <duration>` | `24h` | Only consider tickets created within this window. Strip the trailing `h`, subtract that many hours from now, and use the resulting UTC timestamp as the `created_since` filter value. Example: `--since 48h` → look back 48 hours. |
| `--dry-run` | off | When present, classify and search the KB but **never** call `mcp__freshservice-mcp__create_ticket_note`. Print drafts to screen instead. |

## Workflow

Follow these 9 steps in order for every run. Do not skip or reorder steps.

---

### Step 1 — List candidate tickets

Call `mcp__freshservice-mcp__filter_tickets` with:
- Open tickets only (status = Open)
- `created_since` set to the UTC timestamp derived from `--since`
- A page size / result cap equal to `--limit`

If the tool returns zero tickets, print:

```
No open tickets found in the window. Done.
```

Then stop — do not proceed to any further steps.

Otherwise, collect the list of ticket IDs and proceed to Step 2.

---

### Step 2 — Idempotency check

For **each** candidate ticket, call:

```
mcp__freshservice-mcp__list_all_ticket_conversation
  ticket_id: <ticket_id>
```

Scan every conversation item's `body` field for the exact string:

```
<!-- cq-bot:v1 -->
```

If that string is found in **any** conversation item, this ticket has already been processed. Mark it as `skipped:already_drafted` and move on to the next ticket. Do not process it further.

---

### Step 3 — Pull ticket detail

For every ticket **not** marked skipped in Step 2, call:

```
mcp__freshservice-mcp__get_ticket_by_id
  ticket_id: <ticket_id>
```

Extract and store these fields for use in later steps:
- `subject` — the ticket subject line
- `description` — keep only the **first 500 characters**
- `requester_id` — numeric ID of the person who filed the ticket
- `attachments` — list of any file attachments on the ticket
- Requester first name (from `requester` sub-object if present in the response, or leave blank if absent)

---

### Step 4 — Hard-exclude

Read `config/exclusions.yaml` from the project root using the Read tool. Load `exclusion_keywords` (list of regex patterns) and `vip_emails` (list of email addresses).

Apply the following checks **in order**. The first match that triggers skips the ticket — do not continue checking.

**a. Keyword match**

Concatenate `subject` + `" "` + `description` (first 500 chars). Test against every pattern in `exclusion_keywords` using case-insensitive, DOTALL regex matching. A partial match anywhere in the text is sufficient — no anchors are needed.

If any pattern matches → skip with reason `excluded:keyword`.

**b. VIP requester**

If `requester_id` is set, call:

```
mcp__freshservice-mcp__get_requester_id
  requester_id: <requester_id>
```

Extract the requester's email address. Compare it (case-insensitive) against every entry in `vip_emails`.

If the email matches any entry → skip with reason `excluded:vip`.

**c. Attachments**

If the ticket's `attachments` list is non-empty → skip with reason `excluded:has_attachments`.

If none of the three checks triggered, continue to Step 5.

---

### Step 5 — Classify

Read `config/prompts/classifier.md` from the project root using the Read tool. Use its full content as the system prompt for the classification call below.

Pass the ticket data in this exact format as the user message:

```
Subject: {subject}

Description (first 500 chars):
{description[:500]}
```

Parse the JSON response. The response has the shape:
```json
{"is_routing_question": true, "confidence": "high", "reason": "..."}
```

If `is_routing_question` is `false` → skip with reason `skipped:not_routing`.

If `is_routing_question` is `true`, continue to Step 6.

---

### Step 6 — Search KB

Search `kb/*.md` for content relevant to this ticket. Follow this strategy:

1. **Extract keywords**: Identify 2–5 meaningful nouns or noun phrases from the subject and description. Skip stopwords (the, a, an, is, are, for, to, how, do, I, my, can, you, etc.).
2. **List KB files**: Use the Glob tool with the pattern `kb/*.md` to enumerate all knowledge-base files.
3. **Search**: Use the Grep tool to search for each keyword across the matched files. Use case-insensitive matching.
4. **Rank and read**: Count keyword hits per file. Read the full content of the top 1–3 files with the most hits, using the Read tool. Include the complete YAML frontmatter (the `---` block at the top) — the `url:` field inside it is required for drafting.
5. **No match**: If no KB file matched any keyword → skip with reason `skipped:no_kb_match`.

Store the file name(s) and their content for Step 7.

---

### Step 7 — Draft reply

Read `config/prompts/draft_reply.md` from the project root using the Read tool. Use its full content as the system prompt for the drafting call below.

Pass this context as the user message:

```
Ticket subject: {subject}

Ticket description (first 500 chars):
{description[:500]}

Requester name: {first_name or "unknown"}

KB snippet:
{full content of top KB file(s), including YAML frontmatter}
```

The draft prompt returns one of two things:

- A note body starting with `**DRAFT — review before sending**` — this is the draft to post.
- A single-line JSON sentinel: `{"draft": null, "reason": "no_kb_match"}` — the KB did not clearly answer the routing question.

If the sentinel is returned → skip with reason `skipped:no_kb_match`.

Otherwise, store the note body (it already contains `<!-- cq-bot:v1 -->` at the end, as required by the draft prompt).

---

### Step 8 — Post private note

**If `--dry-run` is active:**

Print the full draft that would be posted, labeled with the ticket ID:

```
[DRY RUN] Ticket {ticket_id}: {subject}
---
{draft note body}
---
```

Do NOT call `mcp__freshservice-mcp__create_ticket_note`. Record the action as `dry-run:drafted` for the report.

**If `--dry-run` is NOT active:**

Call:

```
mcp__freshservice-mcp__create_ticket_note
  ticket_id: <ticket_id>
  body: <draft note body>
  private: true
```

Record the action as `drafted` and note which KB file(s) were cited.

---

### Step 9 — Report

After all tickets have been processed, print a formatted summary table:

```
| Ticket ID | Subject | Action | KB Source |
|---|---|---|---|
| 12345 | Where do I request a new laptop? | drafted | laptop-requests.md |
| 12346 | My email is broken | skipped:not_routing | — |
| 12347 | CEO inquiry | excluded:vip | — |
| 12348 | Security breach report | excluded:keyword | — |
| 12349 | New monitor request | skipped:no_kb_match | — |
```

Rules for the table:
- Truncate subject to 40 characters if it is longer; add `…` at the end.
- `Action` is one of: `drafted`, `dry-run:drafted`, `skipped:already_drafted`, `skipped:not_routing`, `skipped:no_kb_match`, `excluded:keyword`, `excluded:vip`, `excluded:has_attachments`.
- `KB Source` is the filename (not full path) of the KB file used. Use `—` if no KB file was used.

If `--dry-run` was active, prepend this line before the table:

```
DRY RUN — no notes were posted to Freshservice.
```

---

## Safety rules

These rules are non-negotiable and override any other consideration:

1. **Idempotency first.** Always check for `<!-- cq-bot:v1 -->` in existing conversations (Step 2) before doing any other work on a ticket. Never post a second note to a ticket that already has the marker.

2. **Classifier gate.** Never draft or post a note unless the classifier explicitly returns `"is_routing_question": true`. A `false` result or any parse error → skip, no exceptions.

3. **KB citation required.** Never post a note without a KB file citation that contains a `url:` field in its frontmatter. If the draft prompt returns the `{"draft": null, "reason": "no_kb_match"}` sentinel, skip the ticket — do not improvise or invent an answer.

4. **`--dry-run` never writes.** When `--dry-run` is set, `mcp__freshservice-mcp__create_ticket_note` must not be called under any circumstances. Printing is the only allowed output action.

5. **Hard exclusions are final.** A ticket matching any exclusion rule (keyword, VIP, attachment) is permanently skipped for this run. Do not attempt to override or re-classify excluded tickets.

6. **Private notes only.** All notes posted by this command must have `private: true`. Never post a public reply.

7. **No invented content.** Do not add team names, email addresses, form links, Slack channels, or any routing target that does not appear verbatim in the KB snippet.

---

## Output

### Per-ticket dry-run output (when `--dry-run` is set)

```
[DRY RUN] Ticket 12345: Where do I request a new laptop?
---
**DRAFT — review before sending**

Hi Alex,

To request a new laptop, submit a request through the IT Service Portal ...

You can find more details and submit your request here: https://...

Let me know if you have any questions.

<!-- cq-bot:v1 -->
---
```

### Final summary table

Printed after all tickets are processed. Format as shown in Step 9 above.

Columns:
- **Ticket ID** — numeric Freshservice ticket ID
- **Subject** — first 40 characters of the ticket subject, followed by `…` if truncated
- **Action** — outcome for this ticket (see Step 9 for valid values)
- **KB Source** — filename of the KB article used, or `—`

If no tickets were processed (e.g., all skipped), still print the table with the skipped rows — do not omit it.
