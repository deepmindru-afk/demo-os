"""
Shared Settings
---------------

Centralizes the model, database, and environment flags
so all agents share the same resources.
"""

from os import getenv

from agno.models.openai import OpenAIResponses

from db import get_postgres_db

# Database — single instance shared by all agents
agent_db = get_postgres_db()

# Model — change class + ID together when switching providers
MODEL = OpenAIResponses(id="gpt-5.4")

# Optional tool availability
PARALLEL_API_KEY = getenv("PARALLEL_API_KEY", "")

# Environment
RUNTIME_ENV = getenv("RUNTIME_ENV", "prd")
SLACK_TOKEN = getenv("SLACK_TOKEN", "")
SLACK_SIGNING_SECRET = getenv("SLACK_SIGNING_SECRET", "")


def get_parallel_tools(**kwargs) -> list:
    """Return ParallelTools if PARALLEL_API_KEY is set, else empty list."""
    if PARALLEL_API_KEY:
        from agno.tools.parallel import ParallelTools

        return [ParallelTools(**kwargs)]
    return []
