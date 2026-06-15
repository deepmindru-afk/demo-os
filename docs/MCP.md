# The owner-only MCP channel

`@context` can expose itself as an **MCP server with a single tool** —
`ask_context(message, session_id?)` — so you can read and act through your
context from MCP clients (Claude, ChatGPT) as a custom connector.

This is the **owner's private read/act channel**. It is not a guest path:
teammates keep their existing write path (Slack `submit_update` / the context
network — see [`NETWORK.md`](NETWORK.md)); they never reach this endpoint. The
asymmetry holds — *anyone can write to your context, only you can read it or act
through it* — and over MCP it's enforced the same way it is everywhere else:
**in code, from a verified identity, before the model runs**.

## What it is

One tool, mounted at `/mcp`:

```
ask_context(message: str, session_id: str | None = None) -> str
```

Its body runs the *real* `context` agent ([`agents/context.py`](../agents/context.py))
as the **owner** — `context.arun(message, user_id=<owner>, …)` — so a call gets
the full owner surface: the CRM, the knowledge base, the workspace, the web, and
(when configured) Slack, Gmail, and Calendar. It's the same agent and the same
identity-conditioned toolset the rest of the product uses, reached over a
different transport. Pass `session_id` to continue an earlier thread.

## Why not AgentOS's built-in MCP server

AgentOS ships `enable_mcp_server=True`, but we keep it **off** and build our own.
The built-in server registers ~19 fixed, unscopeable tools (`run_agent` +
`run_team` + `run_workflow` + full session and memory CRUD), and its `run_agent`
calls the agent with **no `user_id`** — it drops identity. Through it, a call
would resolve to `is_owner == False` and land on the **capture-only guest
surface**, the opposite of what we want, while the session/memory CRUD tools
would be a second door into the data that bypasses the owner/guest toolset
entirely. Our one-tool server threads the owner identity through instead, so the
owner acts *as* the owner and nothing else is exposed.

## Auth — fail closed, owner-only

The channel is gated in two layers, both in code, before the model runs (see
[`SECURITY.md`](SECURITY.md) L7):

- **Production (`RUNTIME_ENV=prd`).** The *same* JWT middleware AgentOS uses for
  the REST API runs on the MCP app (same `JWT_VERIFICATION_KEY`, same
  algorithm). It verifies the token and puts the verified `sub` on the request.
  Then `OwnerOnlyMiddleware` resolves the caller and **rejects anyone who is not
  in `OWNER_ID` with 401** — it never falls back to the guest surface. An
  unauthenticated call, a valid non-owner token, and the scheduler sentinel are
  all rejected.
- **Dev (no JWT).** There is no auth locally, so the gate binds to the canonical
  `OWNER_ID` — the same keyless-local-as-owner shortcut compose uses elsewhere.
  Dev-only; production always carries a verified identity.

With no `OWNER_ID` configured the gate 401s everyone (fail closed), so the
channel only mounts when an owner is set.

**Acting through it.** Reads and ungated actions (filing to the CRM/knowledge
base, drafting email, sending Slack messages) run to completion. The one
approval-gated act tool — `update_calendar`, which changes the real calendar —
still pauses for per-call approval (SECURITY.md L6), and there's no approval
affordance over MCP, so `ask_context` returns a note telling you to approve it in
the AgentOS chat UI and then ask it to continue. Reads, drafting, and messaging
are the unattended-safe path; mutating the calendar is deliberately not.

## Enabling it

Set the env var and (re)start:

```bash
ENABLE_CONTEXT_MCP=true
```

It's **off by default**. `compose.yaml` turns it on for local dev. In production,
set it in `.env.production` before deploying (see the deploy steps in the
[README](../README.md) / `CLAUDE.md`).

When it's on you'll see this on startup:

```
@context: owner-only MCP channel mounted at /mcp
```

## Wiring it into Claude

Claude takes a **custom connector** URL. Add it under Settings → Connectors (or
the connector picker in a chat):

| | |
|---|---|
| **URL** | `https://<your-deploy-domain>/mcp` (e.g. your Railway domain). Local: `http://localhost:8000/mcp`. |
| **Transport** | Streamable HTTP (the default for a URL connector). |
| **Auth header** | `Authorization: Bearer <JWT>` — the token os.agno.com mints for your AgentOS (the same token the REST API and the built-in MCP use). Local dev needs no token. |

Once connected, Claude sees one tool, `ask_context`. Ask it things like *"what's
waiting on me?"*, *"what do we know about Acme?"*, or *"draft a reply to Sarah"*.

ChatGPT's custom connectors work the same way — point them at the same `/mcp`
URL with the same bearer token.

## Verifying locally

With the stack up (`docker compose up -d`) and `ENABLE_CONTEXT_MCP=true`, point a
streamable-HTTP MCP client at `http://localhost:8000/mcp` (mirroring
`cookbook/05_agent_os/mcp_demo/test_client.py` in the Agno repo). `list_tools`
returns exactly `["ask_context"]`; calling it with a question that needs the
workspace (e.g. *"where is the owner/guest boundary enforced in this repo?"*)
comes back citing real files — proof the owner toolset was threaded through.
