"""
AgentOS Settings
================

Shared runtime objects for the AgentOS.
"""

from os import getenv

from agno.models.openai import OpenAIResponses


def default_model() -> OpenAIResponses:
    """Fresh model instance per agent — avoids memory leaks."""
    return OpenAIResponses(id="gpt-5.5")


def runtime_env() -> str:
    """``RUNTIME_ENV`` with the production default."""
    return getenv("RUNTIME_ENV", "prd")


def is_prd() -> bool:
    """True unless explicitly running dev — auth and owner checks rely on this."""
    return runtime_env() == "prd"


def _float_env(name: str, default: float) -> float:
    """Read a float env var, falling back to ``default`` on unset/garbage."""
    try:
        return float(getenv(name, "") or default)
    except (TypeError, ValueError):
        return default


def ask_context_timeout() -> float:
    """Hard ceiling (seconds) for one ``ask_context`` run on the MCP path.

    Bounds a cross-source sweep so a slow source returns an "ask something narrower"
    message instead of hanging the client. Keep it under the client's own tool timeout
    (e.g. Claude Code's ``MCP_TOOL_TIMEOUT``) so our message wins, not a dead stream.
    """
    return _float_env("ASK_CONTEXT_TIMEOUT", 55.0)


def provider_query_timeout() -> float:
    """Per-source ceiling (seconds) for a single ``query_<id>`` sub-agent run.

    A slow source degrades to a one-line "skipped" and the rest of the brief still
    lands. Smaller than ``ask_context_timeout`` so several can skip within one budget.
    """
    return _float_env("PROVIDER_TIMEOUT", 20.0)
