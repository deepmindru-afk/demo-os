"""
The Reminder Sweep
==================

Fire due reminders into the owner's inbound queue.

A reminder filed in `context.reminders` carries a `due_at`, but nothing watches
that clock — the agent files reminders, it never surfaces them. `fire_due_reminders`
is the watcher: a deterministic sweep that finds reminders which have come due
and haven't been surfaced yet, drops each into the owner's inbound queue (so it
shows up on the next `rundown` / daily rundown), and stamps `notified_at` so a
reminder fires exactly once no matter how often the sweep runs.

It rides the same owner rails as the inbound queue: it's added only in the owner
branch of `context_tools`, and it's only ever reached on the owner surface — the
daily scheduler run (verified identity `__scheduler__`, which `is_owner` honors)
triggers `/agents/context/runs`, and the agent calls this tool. The `is_owner`
guard is redundant behind the toolset gate but cheap defense in depth, matching
`rundown` / `acknowledge`.
"""

from agno.exceptions import StopAgentRun
from agno.run import RunContext
from agno.tools import tool
from sqlalchemy import text

from app.identity import CANONICAL_OWNER_ID, is_owner
from db import SCHEMA, get_sql_engine

_REMINDERS = f"{SCHEMA}.reminders"
_UPDATES = f"{SCHEMA}.updates"


@tool
def fire_due_reminders(run_context: RunContext) -> str:
    """Surface reminders that have come due into the owner's inbound queue.

    Finds every pending reminder whose due date has passed and that hasn't been
    surfaced yet, files each into the owner's queue (where it shows up on the
    rundown, grouped as needing the owner), and marks it surfaced so it never
    fires twice. Run by the daily scheduler; owner-only. Returns a one-line
    summary of what came due.
    """
    if not is_owner(run_context):
        raise StopAgentRun("Firing reminders is only available to the owner.")
    if CANONICAL_OWNER_ID is None:
        return "No owner is configured, so there are no reminders to fire."

    engine = get_sql_engine()
    with engine.begin() as conn:
        due = conn.execute(
            text(
                f"""
                SELECT id, title, notes, due_at
                FROM {_REMINDERS}
                WHERE user_id = :owner
                  AND status = 'pending'
                  AND due_at IS NOT NULL
                  AND due_at <= NOW()
                  AND notified_at IS NULL
                ORDER BY due_at
                """
            ),
            {"owner": CANONICAL_OWNER_ID},
        ).all()

        if not due:
            return "No reminders have come due."

        for r in due:
            due_str = r.due_at.strftime("%Y-%m-%d") if r.due_at else ""
            body = (r.notes or "").strip()
            if due_str:
                body = f"{body}\n\nReminder due {due_str}.".strip()
            # work_status='blocked' lands it under "waiting on you" on the
            # rundown; source='reminder' / from_person='@context' mark it as
            # the owner's own follow-up surfacing, not a teammate's update.
            conn.execute(
                text(
                    f"""
                    INSERT INTO {_UPDATES}
                        (user_id, title, body, from_person, source, work_status, ack_status)
                    VALUES
                        (:owner, :title, :body, '@context', 'reminder', 'blocked', 'new')
                    """
                ),
                {"owner": CANONICAL_OWNER_ID, "title": r.title, "body": body},
            )

        ids = [r.id for r in due]
        conn.execute(
            text(f"UPDATE {_REMINDERS} SET notified_at = NOW() WHERE user_id = :owner AND id = ANY(:ids)"),
            {"owner": CANONICAL_OWNER_ID, "ids": ids},
        )

    titles = ", ".join(r.title for r in due)
    return f"Surfaced {len(due)} due reminder(s) to your inbox: {titles}."
