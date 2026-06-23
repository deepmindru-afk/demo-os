#!/usr/bin/env python3
"""
@context Google token minter — connects your Gmail + Calendar.

The OAuth consent flow opens a browser, so it can't run in the container — you
mint the tokens once on your machine and the dev container picks them up through
the .:/app mount. This script is the one-command version of that: it loads your
env, checks the OAuth client is configured, mints a token file for Gmail and one
for Calendar with exactly the scopes @context's providers use, and writes the
tokens back as base64 so a Railway deploy can restore them.

Usage (from the repo root, with the venv active — ./scripts/venv_setup.sh):

    python scripts/google_mint_tokens.py            # mint what's missing
    python scripts/google_mint_tokens.py --force    # re-mint even if tokens exist

Prereqs (in .env or .env.production — see docs/GOOGLE.md):
    GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET, GOOGLE_PROJECT_ID

What it does:
    - Loads creds from .env and .env.production (real env > .env > .env.production).
    - Mints GMAIL_TOKEN_FILE / CALENDAR_TOKEN_FILE (repo root by default) — gitignored.
    - Prints which Google account each token authorized, so you can confirm it.
    - Upserts GMAIL_TOKEN_JSON_B64 / CALENDAR_TOKEN_JSON_B64 into .env.production
      for the entrypoint to restore on deploy (dev reads the token files directly,
      so .env never needs them).
    - Offers to run ./scripts/railway/env-sync.sh so the deploy picks them up.
"""

import argparse
import base64
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

# The env files we read creds from, in precedence order (earlier wins; real
# environment beats both) — so dev creds in .env beat deploy creds in .env.production.
# The base64 tokens are written back only to .env.production (see main()): they
# exist solely to survive a baked deploy image, and in dev the container reads the
# token files through the .:/app mount, so .env never needs them.
ENV_FILES = (".env", ".env.production")

# The scopes the Gmail + Calendar providers use. Minted as the union of read +
# write so the read and write sub-agents can share one token file per service.
# Kept in sync with docs/GOOGLE.md.
GMAIL_SCOPES = [
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.modify",
    "https://www.googleapis.com/auth/gmail.compose",
]
CALENDAR_SCOPES = [
    "https://www.googleapis.com/auth/calendar.readonly",
    "https://www.googleapis.com/auth/calendar",
]


def _load_dotenv() -> None:
    """Populate os.environ from .env and .env.production (without overriding real env).

    A tiny, dependency-free KEY=VALUE parser so you don't have to `set -a; source`
    first. Precedence: real environment > .env > .env.production — so dev creds in
    .env win over deploy creds in .env.production, and an exported value beats both.
    """
    from os import environ

    for name in ENV_FILES:
        env_file = REPO_ROOT / name
        if not env_file.exists():
            continue
        for raw in env_file.read_text().splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            if key and key not in environ:
                environ[key] = value


def _managed_key(line: str, keys: dict[str, str]) -> str | None:
    """The managed key a line sets — matching both `KEY=...` and a commented `# KEY=`.

    This lets the minter fill the placeholders that ship commented-out in
    example.env (e.g. `# GMAIL_TOKEN_JSON_B64=`) in place, rather than appending a
    duplicate beside them. Prose comments never match: the key has to sit
    immediately before the `=`, and only the keys we're writing are considered.
    """
    body = line.lstrip()
    if body.startswith("#"):
        body = body.lstrip("#").lstrip()
    if "=" not in body:
        return None
    candidate = body.split("=", 1)[0].strip()
    return candidate if candidate in keys else None


def _upsert_env(path: Path, updates: dict[str, str]) -> None:
    """Set KEY=VALUE lines in an env file, idempotently.

    Fills the first existing line for each key in place — whether it's already
    active (`KEY=old`) or a commented placeholder (`# KEY=`) — so re-runs and the
    commented placeholders shipped in example.env never leave duplicates. Any
    later line for an already-filled key is dropped; keys with no line at all are
    appended under a labeled comment.
    """
    lines = path.read_text().splitlines() if path.exists() else []
    pending = dict(updates)
    out: list[str] = []
    for line in lines:
        key = _managed_key(line, updates)
        if key is None:
            out.append(line)
        elif key in pending:
            out.append(f"{key}={pending.pop(key)}")  # fill the first slot we find
        # else: a later duplicate / placeholder for an already-filled key — drop it
    if pending:
        if out and out[-1].strip():
            out.append("")
        out.append("# Gmail/Calendar OAuth tokens (base64) — restored by scripts/entrypoint.sh on deploy")
        out.extend(f"{key}={value}" for key, value in pending.items())
    path.write_text("\n".join(out) + "\n")


def _gmail_account(token_path: Path) -> str | None:
    """The Google address this Gmail token authorized (None if it can't be read)."""
    try:
        from google.oauth2.credentials import Credentials
        from googleapiclient.discovery import build

        creds = Credentials.from_authorized_user_file(str(token_path), GMAIL_SCOPES)
        service = build("gmail", "v1", credentials=creds, cache_discovery=False)
        return service.users().getProfile(userId="me").execute().get("emailAddress")
    except Exception:
        return None


def _calendar_account(token_path: Path) -> str | None:
    """The Google address this Calendar token authorized (the primary calendar id)."""
    try:
        from google.oauth2.credentials import Credentials
        from googleapiclient.discovery import build

        creds = Credentials.from_authorized_user_file(str(token_path), CALENDAR_SCOPES)
        service = build("calendar", "v3", credentials=creds, cache_discovery=False)
        return service.calendarList().get(calendarId="primary").execute().get("id")
    except Exception:
        return None


def _mint(label: str, token_path: Path, trigger, account, force: bool) -> bool:
    """Mint one service's token (or reuse an existing one). Returns True on success.

    `trigger()` runs the OAuth flow (opens the browser on first use and writes the
    token file); `account(path)` reads back which Google account it authorized.
    """
    if token_path.exists() and not force:
        print(f"→ {label}: token already at {token_path} (skipping; --force to re-mint).")
    else:
        if force and token_path.exists():
            token_path.unlink()
        print(f"→ {label}: opening browser for consent...")
        trigger()
        if not token_path.exists():
            print(f"  {label} token was not written to {token_path} — check the client credentials.")
            return False
        print(f"  wrote {token_path}")

    who = account(token_path)
    print(
        f"  connected account: {who}" if who else "  (couldn't read the connected account — token may need a re-mint)"
    )
    return True


def main() -> int:
    from os import getenv

    parser = argparse.ArgumentParser(description="Mint @context's Gmail + Calendar OAuth tokens.")
    parser.add_argument("--force", action="store_true", help="re-mint even if a token file already exists")
    args = parser.parse_args()

    _load_dotenv()

    missing = [k for k in ("GOOGLE_CLIENT_ID", "GOOGLE_CLIENT_SECRET") if not getenv(k)]
    if missing:
        print(f"Missing required env: {', '.join(missing)}.")
        print(f"Set the OAuth client in {' or '.join(ENV_FILES)} — see docs/GOOGLE.md.")
        return 1

    from agents.sources import calendar_token_path, gmail_token_path

    gmail_token = Path(gmail_token_path())
    calendar_token = Path(calendar_token_path())

    print("Minting Google tokens. Your browser opens for each one that isn't already minted.\n")

    # Importing here keeps the missing-env message fast and dependency-light.
    from agno.tools.google.calendar import GoogleCalendarTools
    from agno.tools.google.gmail import GmailTools

    ok = _mint(
        "Gmail",
        gmail_token,
        lambda: GmailTools(token_path=str(gmail_token), scopes=GMAIL_SCOPES).get_latest_emails(1),
        _gmail_account,
        args.force,
    )
    if not ok:
        return 1

    ok = _mint(
        "Calendar",
        calendar_token,
        lambda: GoogleCalendarTools(token_path=str(calendar_token), scopes=CALENDAR_SCOPES).list_events(limit=1),
        _calendar_account,
        args.force,
    )
    if not ok:
        return 1

    # Write the tokens back as base64 so a Railway deploy can restore them (the
    # token files are gitignored + .dockerignore'd and don't survive a redeploy).
    # This is deploy-only: in dev the container reads the token files through the
    # .:/app mount, so .env never needs these — we only touch .env.production.
    b64 = {
        "GMAIL_TOKEN_JSON_B64": base64.b64encode(gmail_token.read_bytes()).decode(),
        "CALENDAR_TOKEN_JSON_B64": base64.b64encode(calendar_token.read_bytes()).decode(),
    }
    prod = REPO_ROOT / ".env.production"

    print()
    if prod.exists():
        _upsert_env(prod, b64)
        print("Wrote GMAIL_TOKEN_JSON_B64 + CALENDAR_TOKEN_JSON_B64 to .env.production.")
    else:
        print("Dev needs nothing more — the container reads the token files via the .:/app mount.")
        print("base64 is only for a Railway deploy. Create .env.production and re-run, or add:")
        for key, value in b64.items():
            print(f"  {key}={value}")

    print("\nDone. Restart to pick up the tokens: docker compose up -d")

    # Offer the Railway sync when we wrote the deploy file and the script is there.
    sync = REPO_ROOT / "scripts" / "railway" / "env-sync.sh"
    if prod.exists() and sync.exists():
        try:
            answer = input("\nPush to Railway now with ./scripts/railway/env-sync.sh? [y/N] ")
        except EOFError:
            answer = ""
        if answer.strip().lower().startswith("y"):
            return subprocess.run(["bash", str(sync)], cwd=str(REPO_ROOT)).returncode
        print("Skipped. Run ./scripts/railway/env-sync.sh yourself when you're ready to deploy.")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
