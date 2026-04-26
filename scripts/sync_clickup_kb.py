"""Sync ClickUp v3 docs to local kb/*.md files.

Env vars (loaded from .env):
  CLICKUP_TOKEN           — ClickUp personal API token
  CLICKUP_WORKSPACE_ID    — numeric workspace / team ID
  CLICKUP_DOC_FOLDER_IDS  — comma-separated parent_id values to filter docs by
"""

import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

import requests
import yaml
from dotenv import load_dotenv

load_dotenv()

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

TOKEN = os.environ.get("CLICKUP_TOKEN", "")
WORKSPACE_ID = os.environ.get("CLICKUP_WORKSPACE_ID", "")
FOLDER_IDS_RAW = os.environ.get("CLICKUP_DOC_FOLDER_IDS", "")
FOLDER_IDS = [f.strip() for f in FOLDER_IDS_RAW.split(",") if f.strip()]

KB_DIR = Path(__file__).parent.parent / "kb"

BASE_URL = "https://api.clickup.com/api/v3"

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def headers() -> dict:
    return {"Authorization": TOKEN, "Content-Type": "application/json"}


def slugify(title: str) -> str:
    return re.sub(r"[^\w-]", "-", title.lower()).strip("-")


def parse_iso(dt_str: str) -> datetime:
    """Parse an ISO-8601 string (with or without trailing Z) to a UTC datetime."""
    dt_str = dt_str.rstrip("Z").split("+")[0]
    return datetime.fromisoformat(dt_str).replace(tzinfo=timezone.utc)


def read_local_date_updated(path: Path):
    """Return the date_updated from existing frontmatter, or None."""
    if not path.exists():
        return None
    try:
        text = path.read_text(encoding="utf-8")
        if not text.startswith("---"):
            return None
        end = text.index("---", 3)
        fm = yaml.safe_load(text[3:end])
        raw = fm.get("date_updated")
        if raw is None:
            return None
        if isinstance(raw, datetime):
            return raw.replace(tzinfo=timezone.utc) if raw.tzinfo is None else raw
        return parse_iso(str(raw))
    except Exception:
        return None


def build_frontmatter(doc_id: str, title: str, date_updated: str) -> str:
    url = f"https://app.clickup.com/v/dc/{WORKSPACE_ID}/{doc_id}"
    fm = {
        "clickup_doc_id": doc_id,
        "title": title,
        "url": url,
        "date_updated": date_updated,
    }
    return "---\n" + yaml.dump(fm, default_flow_style=False, allow_unicode=True) + "---\n\n"


# ---------------------------------------------------------------------------
# API calls
# ---------------------------------------------------------------------------


def list_docs(parent_id: str | None = None) -> list[dict]:
    """Fetch all docs from the v3 endpoint, optionally filtered by parent_id."""
    url = f"{BASE_URL}/workspaces/{WORKSPACE_ID}/docs"
    params: dict = {"limit": 100}
    if parent_id:
        params["parent_id"] = parent_id
    docs: list[dict] = []
    while True:
        resp = requests.get(url, headers=headers(), params=params, timeout=30)
        if resp.status_code != 200:
            print(f"[error] listing docs (parent_id={parent_id}): HTTP {resp.status_code} — {resp.text[:200]}")
            break
        data = resp.json()
        batch = data.get("docs", [])
        docs.extend(batch)
        # ClickUp v3 pagination via cursor
        next_cursor = data.get("next_cursor") or data.get("nextCursor")
        if not next_cursor or not batch:
            break
        params["cursor"] = next_cursor
    return docs


def get_pages(doc_id: str) -> list[dict]:
    """Fetch all pages for a doc."""
    url = f"{BASE_URL}/workspaces/{WORKSPACE_ID}/docs/{doc_id}/pages"
    resp = requests.get(url, headers=headers(), timeout=30)
    if resp.status_code != 200:
        raise RuntimeError(f"HTTP {resp.status_code} — {resp.text[:200]}")
    data = resp.json()
    # Response may be {"pages": [...]} or a bare list
    if isinstance(data, list):
        return data
    return data.get("pages", [])


def extract_page_content(page: dict) -> str:
    """Pull plain text from a page object; fall back gracefully."""
    # v3 pages may use 'content' (markdown) or 'text' keys
    return page.get("content") or page.get("text") or ""


# ---------------------------------------------------------------------------
# Sync logic
# ---------------------------------------------------------------------------


def sync_doc(doc: dict) -> str:
    """Sync one doc. Returns 'synced', 'skipped', or 'error:<msg>'."""
    doc_id = doc.get("id", "")
    title = doc.get("name") or doc.get("title") or doc_id
    # date_updated may be epoch ms (int) or ISO string
    raw_updated = doc.get("date_updated") or doc.get("updated_at") or ""
    if isinstance(raw_updated, (int, float)):
        remote_dt = datetime.fromtimestamp(raw_updated / 1000, tz=timezone.utc)
        remote_iso = remote_dt.isoformat()
    else:
        remote_iso = str(raw_updated)
        try:
            remote_dt = parse_iso(remote_iso)
        except Exception:
            remote_dt = None

    slug = slugify(title)
    out_path = KB_DIR / f"{slug}.md"

    # Incremental check
    if remote_dt is not None:
        local_dt = read_local_date_updated(out_path)
        if local_dt is not None and local_dt >= remote_dt:
            return "skipped"

    # Fetch pages
    try:
        pages = get_pages(doc_id)
    except Exception as exc:
        return f"error:{exc}"

    # Concatenate content
    content_parts = []
    for page in pages:
        page_title = page.get("name") or page.get("title") or ""
        page_body = extract_page_content(page)
        if page_title:
            content_parts.append(f"## {page_title}\n\n{page_body}")
        elif page_body:
            content_parts.append(page_body)
    body = "\n\n".join(content_parts)

    fm = build_frontmatter(doc_id, title, remote_iso)
    out_path.write_text(fm + body, encoding="utf-8")
    return "synced"


def main() -> None:
    if not TOKEN:
        print("[error] CLICKUP_TOKEN not set. Add it to .env and retry.")
        sys.exit(1)
    if not WORKSPACE_ID:
        print("[error] CLICKUP_WORKSPACE_ID not set. Add it to .env and retry.")
        sys.exit(1)

    KB_DIR.mkdir(parents=True, exist_ok=True)

    # Collect docs — one pass per folder ID (or one global pass if none configured)
    seen_ids: set[str] = set()
    all_docs: list[dict] = []
    if FOLDER_IDS:
        for fid in FOLDER_IDS:
            for doc in list_docs(parent_id=fid):
                if doc.get("id") not in seen_ids:
                    seen_ids.add(doc["id"])
                    all_docs.append(doc)
    else:
        all_docs = list_docs()

    if not all_docs:
        print("No docs found. Check CLICKUP_WORKSPACE_ID and CLICKUP_DOC_FOLDER_IDS.")
        return

    synced = skipped = errors = 0

    for doc in all_docs:
        title = doc.get("name") or doc.get("title") or doc.get("id", "unknown")
        result = sync_doc(doc)
        if result == "synced":
            print(f"[synced]  {title}")
            synced += 1
        elif result == "skipped":
            print(f"[skipped] {title} (up to date)")
            skipped += 1
        else:
            msg = result.removeprefix("error:")
            print(f"[error]   {title}: {msg}")
            errors += 1

    print(f"\nSynced {synced} docs, skipped {skipped}, errors {errors}")


if __name__ == "__main__":
    main()
