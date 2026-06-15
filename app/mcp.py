"""
Owner-only MCP channel
======================

@context's read/write surface over the Model Context Protocol, so the owner can
talk to it from MCP clients. The **desktop apps** (Claude Desktop, ChatGPT
desktop) reach it on localhost with no tunnel and no setup; cloud clients reach a
deployed instance (see [`docs/MCP.md`](../docs/MCP.md)). This is the
lowest-friction way in — no Slack app, no bot tokens — and the client learns
about @context and uses it without the owner having to prompt it.

Two tools, both running the *real* ``context`` agent
([`agents/context.py`](context.py)) as the **owner**:

- ``ask_context(message, session_id?)`` — read from / act through your context
  (the CRM, knowledge base, workspace, web, and — when configured — Slack, Gmail,
  Calendar).
- ``update_context(message, session_id?)`` — file into / update your context
  (leave an update, save a contact / note / decision, set a reminder, record what
  happened).

Both reuse the same identity-conditioned toolset the rest of the product is built
on, reached over a different transport — nothing re-implemented. They differ only
in the description that tells the client *when* to call them; the owner agent
decides what to actually do.

**Always on, owner-only, fail-closed.** The channel mounts unconditionally — it's
not a setting the owner opts into. It is *not* a guest path: guests keep their
Slack ``submit_update`` write path and never reach this endpoint. Two gates
enforce that in code, before the model runs:

- In production (``RUNTIME_ENV == "prd"``) the *same* JWT middleware AgentOS uses
  validates the token and puts the verified ``sub`` on ``request.state.user_id``.
- ``OwnerOnlyMiddleware`` then resolves the caller and **401s anyone who is not
  the owner** — it never silently falls back to the capture-only guest surface.

In dev (no JWT) the gate binds to the canonical owner id — the same
keyless-local-as-owner convenience compose uses. Dev-only; prod always carries a
verified identity. Because an always-on local MCP server is a real DNS-rebinding
target, host/origin validation is on, anchored on localhost (so the desktop case
needs zero config) plus the deploy/tunnel host from ``AGENTOS_URL``.

Why not AgentOS's built-in ``enable_mcp_server``: it ships ~19 fixed, unscopeable
tools (run_agent + full session/memory CRUD), and its ``run_agent`` drops
identity (no ``user_id``), so a call would land on the capture-only guest surface
— the opposite of what we want. So we build our own server that threads the owner
identity through. See [`docs/MCP.md`](../docs/MCP.md) and
[`docs/SECURITY.md`](../docs/SECURITY.md).
"""

from collections.abc import Awaitable, Callable
from os import getenv
from urllib.parse import urlparse

from agno.os.config import AuthorizationConfig
from agno.utils.log import log_warning
from mcp.server.fastmcp import Context, FastMCP
from mcp.server.transport_security import TransportSecuritySettings
from starlette.applications import Starlette
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from agents.context import context
from app.identity import CANONICAL_OWNER_ID, OWNER_IDS
from app.settings import is_prd

# The MCP endpoint path. The sub-app is mounted at the app root, so this is also
# the public path (https://<host>/mcp).
MCP_PATH = "/mcp"

ASK_CONTEXT_DESCRIPTION = (
    "Read from or act through the owner's @context — their personal context "
    "agent. Use to answer a question or pull things together from the CRM / "
    "structured store, the knowledge base, the workspace, the web, and (when "
    "configured) Slack, Gmail, and Calendar. Examples: 'what's waiting on me?', "
    "'what do we know about Acme?', 'draft a reply to Sarah'. Optionally pass "
    "session_id to continue an earlier thread. Owner-only."
)

UPDATE_CONTEXT_DESCRIPTION = (
    "Add to or update the owner's @context — file something worth remembering or "
    "acting on. Use to leave an update, save a contact, note, or decision, set a "
    "reminder, or record what happened. Examples: 'met Sarah from Acme, follow "
    "up Friday', 'we decided to ship the MCP channel first', 'remind me to review "
    "the deck tomorrow'. Pass a natural-language statement (not a question). "
    "Optionally pass session_id to continue an earlier thread. Owner-only."
)


def _resolve_caller_id(request: Request | None) -> str | None:
    """The verified caller identity for this MCP request.

    Production: the JWT middleware on this sub-app has put the verified token
    ``sub`` on ``request.state.user_id`` — read it. Dev (no JWT): fall back to
    the canonical owner id, the same keyless-local-as-owner shortcut compose
    uses. DEV-ONLY — prod always carries a verified identity.
    """
    state_id = getattr(getattr(request, "state", None), "user_id", None)
    if isinstance(state_id, str) and state_id:
        return state_id
    if not is_prd():
        return CANONICAL_OWNER_ID  # dev shortcut — there is no auth locally
    return None


def _caller_is_owner(user_id: str | None) -> bool:
    """True iff this id is a configured owner identity. Fails closed.

    Stricter than ``app.identity.is_owner``: it does *not* honour the
    ``__scheduler__`` sentinel — the scheduler never calls this endpoint, and
    keeping the human read/act channel to real owner identities is one fewer
    thing to reason about.
    """
    if not user_id:
        return False
    return user_id.casefold() in OWNER_IDS


def _mcp_transport_security() -> TransportSecuritySettings:
    """DNS-rebinding protection for the MCP endpoint.

    An always-on local MCP server is exactly what this guard is for: it stops a
    malicious web page from driving the endpoint via a rebound DNS name (with no
    JWT in dev, that would otherwise reach the owner surface). We mirror the SDK's
    localhost defaults — so the desktop case works with zero config — and add the
    deploy/tunnel host from ``AGENTOS_URL`` so it also works behind a reverse
    proxy (Railway) or an ngrok tunnel (point ``AGENTOS_URL`` at that domain).
    """
    hosts = ["127.0.0.1:*", "localhost:*", "[::1]:*"]
    origins = ["http://127.0.0.1:*", "http://localhost:*", "http://[::1]:*"]
    deploy_host = urlparse(getenv("AGENTOS_URL", "")).hostname
    if deploy_host and deploy_host not in ("127.0.0.1", "localhost", "::1"):
        hosts += [deploy_host, f"{deploy_host}:*"]
        origins += [
            f"https://{deploy_host}",
            f"https://{deploy_host}:*",
            f"http://{deploy_host}",
            f"http://{deploy_host}:*",
        ]
    return TransportSecuritySettings(
        enable_dns_rebinding_protection=True,
        allowed_hosts=hosts,
        allowed_origins=origins,
    )


class OwnerOnlyMiddleware(BaseHTTPMiddleware):
    """Fail-closed owner gate — the structural reason this can't become a guest path.

    Runs after the JWT middleware (in prod) has resolved the verified identity
    onto ``request.state``. Resolves the caller; if it is not the owner it
    returns 401 *before* the MCP machinery and the model ever run. On success it
    stashes the resolved owner id on ``request.state`` for the tools to read.
    """

    async def dispatch(self, request: Request, call_next: Callable[[Request], Awaitable[Response]]) -> Response:
        caller = _resolve_caller_id(request)
        if not _caller_is_owner(caller):
            return JSONResponse(
                {"error": "unauthorized", "detail": "The @context MCP channel is owner-only."},
                status_code=401,
            )
        request.state.context_owner_id = caller
        return await call_next(request)


async def _run_as_owner(ctx: Context, message: str, session_id: str | None) -> str:
    """Run the real context agent as the owner and return its reply.

    Shared body for both MCP tools — they get the owner's full read/write surface;
    the agent decides what to do with the message.
    """
    request: Request | None = getattr(getattr(ctx, "request_context", None), "request", None)
    caller = _resolve_caller_id(request)
    # Defense in depth — the middleware already 401s non-owners. If we ever
    # reached here without an owner, refuse rather than run as anyone.
    if not _caller_is_owner(caller):
        raise ValueError("The @context MCP channel is owner-only.")
    # Key under the canonical id — matches normalize_identity and keeps sessions /
    # storage from fragmenting across the owner's identities.
    result = await context.arun(input=message, user_id=CANONICAL_OWNER_ID, session_id=session_id)
    answer = result.content or ""
    if getattr(result, "is_paused", False):
        # A gated act tool (calendar) is waiting on the owner. There's no approval
        # affordance over MCP, so point them at the chat UI.
        answer += (
            "\n\n[An action is waiting on your approval before it can run — approve it in the "
            "AgentOS chat UI, then ask me to continue.]"
        )
    return answer


def build_context_mcp_app(
    *, authorization: bool = False, authorization_config: AuthorizationConfig | None = None
) -> Starlette:
    """Build the owner-only MCP sub-app: two tools, owner-gated, fail-closed.

    ``authorization`` / ``authorization_config`` are the *same* values AgentOS
    is constructed with (passed in from [`app/main.py`](main.py)), so the JWT
    layer here is identical to the REST API's — same keys, same algorithm.
    """
    server = FastMCP(name="context", transport_security=_mcp_transport_security())

    @server.tool(name="ask_context", description=ASK_CONTEXT_DESCRIPTION)
    async def ask_context(message: str, ctx: Context, session_id: str | None = None) -> str:
        return await _run_as_owner(ctx, message, session_id)

    @server.tool(name="update_context", description=UPDATE_CONTEXT_DESCRIPTION)
    async def update_context(message: str, ctx: Context, session_id: str | None = None) -> str:
        return await _run_as_owner(ctx, message, session_id)

    mcp_app = server.streamable_http_app()

    # Owner gate added first (innermost); JWT added last (outermost) so it
    # populates request.state.user_id before the gate reads it. Starlette runs
    # the last-added middleware first.
    mcp_app.add_middleware(OwnerOnlyMiddleware)
    if authorization and authorization_config is not None:
        from agno.os.middleware.jwt import JWTMiddleware

        # Mirror agno/os/mcp.py: keys come from the config (or, when None, the
        # JWT_VERIFICATION_KEY env var the validator reads on its own).
        mcp_app.add_middleware(
            JWTMiddleware,
            verification_keys=authorization_config.verification_keys,
            jwks_file=authorization_config.jwks_file,
            algorithm=authorization_config.algorithm or "RS256",
            authorization=authorization,
            verify_audience=authorization_config.verify_audience or False,
            user_isolation=authorization_config.user_isolation,
        )
    elif is_prd():
        # No JWT layer in prd means the dev shortcut is the only thing standing
        # in for auth — which would reject every call (no verified identity).
        log_warning(
            "Context MCP channel mounted in prd without JWT authorization — the owner gate will "
            "reject every call. Configure authorization (RUNTIME_ENV=prd implies it)."
        )
    return mcp_app
