---
name: daily-rundown
description: The owner's morning brief — inbound updates awaiting acknowledgment (via the rundown tool), today's meetings and due-or-overdue reminders from the CRM and the real calendar, the emails worth seeing from Gmail, and the Slack threads that need their eyes — each source folded in when connected and stitched into one short digest. Use for "daily rundown", "what's on today", "morning brief", "catch me up".
metadata:
  version: "2.0.0"
  author: context
  tags: ["planning", "daily", "rundown", "crm", "queue", "gmail", "slack"]
---
# Daily Rundown

> _**Runtime skill** — a playbook the deployed @context agent runs for its owner, invoked in natural language. Not a coding-agent workflow; those live in [`.agents/skills/`](../../.agents/skills/)._

A focused **today** brief: one glanceable surface instead of five apps. It folds
in the inbound queue, the CRM, the real calendar, the inbox, and Slack — each
source only when it's connected — and stitches them into one short digest.
Read-only assembly: it pulls and formats, it never files or sends anything.

The whole value is *one* surface, so stay ruthless about signal. Surface what
needs the owner's eyes today, not a mirror of every inbox and channel.

## Procedure

**Keep it cheap.** Each source is a sub-agent call; the brief should be a handful
of them, not a sweep. **One tight retrieval per source, no exploratory follow-ups,
and never retry a source.** The two local sources below are the backbone and always
run; the external ones are best-effort and get skipped the moment they're slow or
unavailable (see the skip rule) — a complete-but-fast brief beats a perfect one that
hangs.

1. **Anchor on now.** Use the current datetime in your context; "today" is now →
   end of the local day.

**Backbone — always run these two (fast, local):**

2. **Inbound queue — call `rundown`.** It surfaces updates others marked done
   that the owner hasn't acknowledged, and the owner's own reminders the hourly
   sweep filed in once they fell due. (It marks what it shows as briefed — that
   is the point of a morning brief; un-acknowledged items still resurface
   tomorrow.) If it returns nothing, drop the section.
3. **Calendar + due work — call `query_crm`** (one retrieval, ask for both):
   - **Meetings** whose `starts_at` is today.
   - **Reminders** that are `pending` and due today, plus anything **overdue**
     (`due_at < now`, still pending).

**Best-effort add-ons — one call each, only if the source is connected; skip on any trouble:**

4. **Calendar** (`calendar` connected): `query_calendar` for today's events; merge
   with the CRM meetings (dedupe by title + start time; the calendar wins on times).
5. **Inbox** (`gmail` connected): `query_gmail` for the handful that actually need
   the owner — unread and important, or addressed to them and awaiting a reply, from
   today. Ask the sub-agent for that tight selection; never pull the whole inbox.
6. **Slack** (`slack` connected): `query_slack` for threads/DMs that mention the
   owner or look like they're waiting on a reply. "Needs your eyes," not an unread dump.
7. Order each list by its time column, ascending.

**Skip rule (add-ons only).** If an add-on source returns an error, a `skipped` /
`unavailable` note, or is plainly slow, **drop its section, note it in one line at
the end** (e.g. "_Slack skipped — slow_"), and move on. Do not retry it and never let
one source hold up the brief. The backbone (queue + CRM) always stands on its own.

**De-dup — one item, one line.** The queue and the other sources overlap; prefer
the queue copy and don't repeat:
- A **reminder** the sweep already filed into the queue (it shows under *Awaiting
  you*) is the same follow-up `query_crm` returns as due/overdue. Show it once,
  under *Awaiting you* — don't also list it under *Overdue* / *Today*.
- A **Slack @-mention** that a teammate already left via the queue shouldn't
  reappear under *Slack*. Prefer the queue copy.

## Format

Lead in this order, dropping any empty section:

1. **Awaiting you** — the `rundown` items, one line each (who / what).
2. **Overdue** — past-due pending reminders not already shown above, with how late.
3. **Today** — meetings (with start time) and reminders due today, time-ordered.
4. **Inbox** — the emails worth seeing (sender · subject · the one-line why), from
   `gmail` when connected.
5. **Slack** — threads/DMs needing a look (channel or DM · who · the ask), from
   `slack` when connected.

Close with a one-line tally, e.g. `2 awaiting · 1 overdue · 4 today · 3 inbox · 2 slack`.

## Edge cases

- **Quiet day:** if every section is empty, say so in one line ("Nothing waiting on
  you and nothing on the calendar today.") — don't pad it.
- **A disconnected source just vanishes.** No `gmail` / `slack` / `calendar` →
  drop its section silently; never error or apologize for it.
- Cite the sources you used (the queue via `rundown`, meetings/reminders via
  `crm`, events via `calendar`, mail via `gmail`, threads via `slack` — each when
  connected). Report empties honestly; never invent items.
