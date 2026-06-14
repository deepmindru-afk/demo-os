"""
Context Policy Hooks
=====================================
"""

from inspect import isawaitable
from typing import Any, Callable

from agno.exceptions import InputCheckError
from agno.run import RunContext

from agents.inbox import CAPTURE_ONLY_TOOLS
from app.identity import ANON_USER_ID, CANONICAL_OWNER_ID, is_owner
from app.settings import is_prd


def normalize_identity(run_context: RunContext, **kwargs: Any) -> None:
    """Collapse the owner's aliases and refuse unidentified prod runs.

    Run as a pre-hook to ensure that every run has a verified identity.
    """
    user_id = getattr(run_context, "user_id", None)

    # In production (auth on) every run must carry a verified identity. A run
    # arriving as the anon sentinel (or with no user_id at all) means
    # something bypassed the auth layer — refuse it.
    if is_prd() and user_id in (None, "", ANON_USER_ID):
        raise InputCheckError("No verified identity on this run; refusing in production.")

    # The owner's identities (Slack email, JWT sub) all collapse onto the
    # canonical id, so the structured store, knowledge base, and queue key
    # under one identity instead of fragmenting per channel.
    if CANONICAL_OWNER_ID is not None and is_owner(run_context):
        run_context.user_id = CANONICAL_OWNER_ID


async def enforce_capture_only(
    name: str,
    func: Callable,
    arguments: dict,
    run_context: RunContext | None = None,
    **kwargs: Any,
) -> Any:
    """Restrict guests to the capture-only allowlist; the owner may call anything.

    Run as a tool-hook: a guest caller may only invoke tools on the
    capture-only allowlist — every other tool is soft-blocked.
    """
    if not is_owner(run_context) and name not in CAPTURE_ONLY_TOOLS:
        # Soft block: return guidance *without* calling func, so the tool's
        # entrypoint never runs (no data is read or written) but the model can
        # still compose a graceful reply instead of the run halting mid-turn.
        # This gates everything outside the capture allowlist — including
        # agno's auto-added built-ins like get_chat_history — for guests.
        # (The per-user memory tool is deliberately *on* the allowlist; see
        # CAPTURE_ONLY_TOOLS in agents.inbox.)
        return (
            "Not permitted: as a guest you have no read access here. Don't "
            "try other tools — tell the caller you can only pass a message to "
            "the owner, and use submit_update if that's what they want."
        )
    result = func(**arguments)
    if isawaitable(result):
        result = await result
    return result
