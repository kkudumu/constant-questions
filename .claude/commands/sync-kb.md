# sync-kb

Pull the latest ClickUp docs down to the local `kb/` directory so `/triage` can grep them.

## What this command does

1. Runs `python scripts/sync_clickup_kb.py` from the project root.
2. The script reads `CLICKUP_TOKEN`, `CLICKUP_WORKSPACE_ID`, and `CLICKUP_DOC_FOLDER_IDS` from `.env`.
3. For each configured ClickUp doc folder it fetches all docs via the v3 API, retrieves their pages, and writes `kb/<slug>.md` with YAML frontmatter.
4. Incremental: docs whose local `date_updated` is already current are skipped — only changed or new docs are fetched.
5. Reports per-doc status (`[synced]`, `[skipped]`, `[error]`) and a summary line.

## Command to run

```bash
python scripts/sync_clickup_kb.py
```

Run this from the project root (`constantquestions/`). If your shell is already there, the above is sufficient. Claude Code users can also invoke it directly via this slash command.

## Note on `kb/`

`kb/` is **gitignored** — it is a local cache only. ClickUp remains the source of truth. Re-run `/sync-kb` any time you want to pull in doc changes before running `/triage`.
