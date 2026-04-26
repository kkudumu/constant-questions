# INTENT — constantquestions

## Vision

Auto-draft private Freshservice ticket notes for routing questions ("where do I request X?") using a local ClickUp KB mirror. Human reviews and sends; system never auto-sends.

## Architecture Decisions

| Decision | Choice | Why |
|---|---|---|
| KB source | ClickUp docs | Canonical answers already live there |
| Send mode | Private note draft only | Safety — human reviews before sending |
| Trigger | On-demand `/triage` slash command | No webhook/scheduler complexity in v1 |
| Search | Grep on local markdown | Routing queries are keyword-y; no vector DB needed |
| Idempotency | Hidden marker `<!-- cq-bot:v1 -->` | Survives re-runs; auditable via Freshservice search |
| ClickUp API | v3 Docs API | v2 doesn't expose doc content; v3 does |

## Module Map

| Module | Path | Does |
|---|---|---|
| KB sync script | `scripts/sync_clickup_kb.py` | Pulls ClickUp docs to `kb/*.md` with YAML frontmatter |
| Triage command | `.claude/commands/triage.md` | Orchestrates ticket fetch → classify → KB search → draft note |
| Sync command | `.claude/commands/sync-kb.md` | Thin wrapper that runs the KB sync script |
| Exclusions config | `config/exclusions.yaml` | VIP emails and keyword regex for hard-exclude |
| Classifier prompt | `config/prompts/classifier.md` | Strict yes/no routing question classifier |
| Draft reply prompt | `config/prompts/draft_reply.md` | Reply structure template for drafted notes |
