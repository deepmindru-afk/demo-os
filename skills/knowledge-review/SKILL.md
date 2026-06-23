---
name: knowledge-review
description: Sweep the knowledge base for what needs attention — stubs with no real content, specs whose status is stale, decisions that were made but never written down, and pages missing from the index — and return a short "what needs attention" list. Read-only, so it reports rather than fixing anything itself. Use for "what in my knowledge base needs attention", "review my knowledge base", "what's stale or unfiled", "knowledge base health check", "tidy up my knowledge".
metadata:
  version: "1.0.0"
  author: context
  tags: ["knowledge", "review", "health", "curation", "maintenance"]
---
# Knowledge Review

> _**Runtime skill** — a playbook the deployed @context agent runs for its owner, invoked in natural language. Not a coding-agent workflow; those live in [`.agents/skills/`](../../.agents/skills/)._

Sweep the knowledge base and report what needs attention so nothing rots. This is
**read-only**: it surfaces issues and suggests the fix, it never edits, files, or
deletes anything itself. The owner decides what to act on.

The knowledge base searches by keyword and the index (no search-by-meaning), so
this sweep works the same way: list the tree, read the index, and reconcile the
two.

## Procedure

1. **Get the lay of the land.** Two `query_knowledge` reads up front:
   - Ask it to **list every file and folder, recursively** — the raw tree, not a
     summary.
   - Ask it for the **root `README.md` index table, verbatim** — every spec and
     page it lists.
   Hold both so you can reconcile what's on disk against what the index claims.
2. **Reconcile disk against the index.**
   - **Orphaned** — a folder or page on disk that the index never lists. It's
     unfindable through the front door.
   - **Index drift** — a row in the index pointing at a folder or page that
     doesn't exist on disk. A dead link.
3. **Spot-check the suspect pages** with targeted `query_knowledge` reads:
   - **Stubs** — a page that's a heading and a line or two of placeholder ("stub
     page", "no details yet", a single sentence) with no real substance.
   - **Stale specs** — a spec whose status table still says draft / in progress /
     for review, or whose own "last updated" line is well in the past, with no
     sign it has moved. Flag it as worth a look, don't assume it's dead.
   - **Missing decision log** — a spec with a design or implementation but no
     `decisions.md` (or an empty one). Decisions got made; they were never
     written down.
   - **Dead cross-links** (when you notice them) — a link from one page to another
     path that isn't there.
4. **Write the "what needs attention" list.** Group the findings, most actionable
   first. Each line: the path, one sentence on why it needs attention, and the
   suggested next step (add it to the index, flesh out the stub, write the ADR,
   fix the index row). Suggest only; don't do it.

## Format

A short report, grouped, only the groups with findings:

- **Orphaned (not in the index)** — `path` — add a row to the index.
- **Index drift (listed but missing)** — `path` — fix or drop the index row.
- **Stubs (no real content)** — `path` — flesh out or fold in.
- **Stale specs** — `path` — status says *X*, last moved *when*; confirm or update.
- **Missing decisions** — `path` — design exists, no decision log; capture the ADRs.

End with a one-line tally ("6 things to look at: 4 orphaned, 2 stubs"). Cite every
path. A healthy base is a one-line report ("Nothing needs attention — index and
tree are in sync.") — don't invent issues to fill the list.

## Edge cases

- **Read-only.** Report and suggest; never edit, file, or delete. If the owner
  wants something fixed, that's a separate `update_knowledge` ask (or the
  `research` skill for a fresh write-up).
- **Cite paths, don't guess.** Every finding names a real path from the tree. If a
  read comes back empty, say the base is empty rather than inventing findings.
- **Judgement over nitpicks.** A deliberately short loose page isn't a stub, and a
  spec that's genuinely done shouldn't read as stale. Flag what a person would
  actually want to fix, not every imperfection.
