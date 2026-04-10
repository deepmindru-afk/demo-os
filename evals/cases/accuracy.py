"""
Accuracy Eval Cases
===================

LLM-judged accuracy cases for entities with verifiable outputs.
Scored 1-10 by AccuracyEval, pass threshold >= 7.0.
"""

CASES = [
    {
        "entity_type": "agent",
        "entity_id": "knowledge",
        "input": "What model providers does Agno support?",
        "expected_output": "OpenAI, Anthropic, Google/Gemini among supported providers",
        "guidelines": "Must name at least 3 specific providers.",
    },
    {
        "entity_type": "team",
        "entity_id": "dash",
        "input": "What plans are available?",
        "expected_output": "Four plans: starter, professional, business, enterprise",
        "guidelines": "Must mention all four plan tiers by name.",
    },
    {
        "entity_type": "team",
        "entity_id": "dash",
        "input": "What's our current MRR?",
        "expected_output": "A numeric MRR value in dollars",
        "guidelines": "Must include a specific dollar amount.",
    },
    {
        "entity_type": "agent",
        "entity_id": "scheduler",
        "input": "List all active schedules",
        "expected_output": "List of scheduled tasks with their cron patterns and status",
        "guidelines": "Must show schedule names and timing info, or clearly state none exist.",
    },
]
