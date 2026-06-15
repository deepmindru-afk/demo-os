"""
Owner-only MCP channel
======================

A second read/act surface for the **owner**, exposed over the Model Context
Protocol so the owner can talk to @context from MCP clients (Claude, ChatGPT)
as a custom connector.

One tool: ``ask_context(message, session_id?)``. Its body runs the *real*
``context`` agent ([`agents/context.py`](context.py)) as the **owner**, so the
owner gets the full read/act surface — the same identity-conditioned toolset the
rest of the product is built on, reused rather than re-implemented.

This endpoint is **owner-only and fail-closed**. It is *not* a guest path:
guests keep their existing write path (Slack ``submit_update`` / the context
network); they never reach this endpoint at all. Two gates enforce that in code,
before the model runs:

- In production (``RUNTIME_ENV == "prd"``) the *same* JWT middleware AgentOS
  uses validates the token and puts the verified ``sub`` on
  ``request.state.user_id``.
- ``OwnerOnlyMiddleware`` then resolves the caller and **401s anyone who is not
  the owner** — it never silently falls back to the capture-only guest surface.

In dev (no JWT) the gate binds to the canonical owner id — the same
keyless-local-as-owner convenience compose uses. Dev-only; prod always carries a
verified identity.

Why not AgentOS's built-in ``enable_mcp_server``: it ships ~19 fixed,
unscopeable tools (run_agent + full session/memory CRUD), and its ``run_agent``
drops identity (no ``user_id``), so a call would land on the capture-only guest
surface — the opposite of what we want. So we build our own one-tool server that
threads the owner identity through. See [`docs/MCP.md`](../docs/MCP.md) and
[`docs/SECURITY.md`](../docs/SECURITY.md).
"""

from collections.abc import Awaitable, Callable
from os import getenv

from agno.os.config import AuthorizationConfig
from agno.utils.log import log_warning
from mcp.server.fastmcp import Context, FastMCP
from mcp.server.transport_security import TransportSecuritySettings
from starlette.applications import Starlette
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from agents.context import context
from app.identity import CANONICAL_OWNER_ID, OWNER_IDS, owner_configured
from app.settings import is_prd

# The MCP endpoint path. The sub-app is mounted at the app root, so this is also
# the public path (https://<host>/mcp).
MCP_PATH = "/mcp"

ASK_CONTEXT_DESCRIPTION = (
    "Ask @context — the owner's personal context agent — to read from or act "
    "through their context: the CRM / structured store, the knowledge base, the "
    "workspace, the web, and (when configured) Slack, Gmail, and Calendar. Pass "
    "a natural-language request (e.g. 'what's waiting on me?', 'what do we know "
    "about Acme?', 'draft a reply to Sarah'). Optionally pass session_id to "
    "continue an earlier thread. Owner-only."
)


def context_mcp_enabled() -> bool:
    """Whether to mount the owner-only MCP channel.

    Opt-in via ``ENABLE_CONTEXT_MCP`` (truthy), default off. Also requires an
    owner to be configured — with no owner the gate would 401 everyone anyway,
    so there's nothing to serve.
    """
    enabled = (getenv("ENABLE_CONTEXT_MCP") or "").strip().lower() in {"1", "true", "yes", "on"}
    return enabled and owner_configured()


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


class OwnerOnlyMiddleware(BaseHTTPMiddleware):
    """Fail-closed owner gate — the structural reason this can't become a guest path.

    Runs after the JWT middleware (in prod) has resolved the verified identity
    onto ``request.state``. Resolves the caller; if it is not the owner it
    returns 401 *before* the MCP machinery and the model ever run. On success it
    stashes the resolved owner id on ``request.state`` for the tool to read.
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


def build_context_mcp_app(
    *, authorization: bool = False, authorization_config: AuthorizationConfig | None = None
) -> Starlette:
    """Build the owner-only MCP sub-app: one tool, owner-gated, fail-closed.

    ``authorization`` / ``authorization_config`` are the *same* values AgentOS
    is constructed with (passed in from [`app/main.py`](main.py)), so the JWT
    layer here is identical to the REST API's — same keys, same algorithm.
    """
    server = FastMCP(
        name="context",  # default streamable_http_path == MCP_PATH
        # FastMCP's default host (127.0.0.1) auto-enables DNS-rebinding
        # protection locked to localhost, which 421s any other Host. That guard
        # is for *unauthenticated* localhost servers; here the real gate is JWT +
        # the owner check, and the endpoint runs behind a reverse proxy where the
        # Host is the public domain. So we disable host/origin validation rather
        # than chase a brittle allowlist that would silently break the connector.
        transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False),
    )

    @server.tool(name="ask_context", description=ASK_CONTEXT_DESCRIPTION)
    async def ask_context(message: str, ctx: Context, session_id: str | None = None) -> str:
        request: Request | None = getattr(getattr(ctx, "request_context", None), "request", None)
        caller = _resolve_caller_id(request)
        # Defense in depth — the middleware already 401s non-owners. If we ever
        # reached here without an owner, refuse rather than run as anyone.
        if not _caller_is_owner(caller):
            raise ValueError("The @context MCP channel is owner-only.")
        # Run the real context agent as the owner. Keying under the canonical id
        # matches normalize_identity and keeps sessions / storage from
        # fragmenting across the owner's identities.
        result = await context.arun(input=message, user_id=CANONICAL_OWNER_ID, session_id=session_id)
        answer = result.content or ""
        if getattr(result, "is_paused", False):
            # A gated act tool (mail / calendar) is waiting on the owner. There's
            # no approval affordance over MCP, so point them at the chat UI.
            answer += (
                "\n\n[An action is waiting on your approval before it can run — approve it in the "
                "AgentOS chat UI, then ask me to continue.]"
            )
        return answer

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
