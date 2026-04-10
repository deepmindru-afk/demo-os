"""
Registry for the Demo AgentOS.

Provides shared tools, models, and database connections for AgentOS.
"""

from agno.models.openai import OpenAIResponses
from agno.registry import Registry

from app.settings import MODEL, agent_db, get_parallel_tools

registry = Registry(
    tools=[*get_parallel_tools()],
    models=[MODEL, OpenAIResponses(id="gpt-5.4-mini")],
    dbs=[agent_db],
)
