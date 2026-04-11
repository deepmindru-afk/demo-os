"""
Accuracy Eval Cases — Teams
============================

LLM-judged accuracy cases for teams with verifiable outputs.
Scored 1-10 by AccuracyEval, pass threshold >= 7.0.
"""

CASES: list[dict] = [
    # -------------------------------------------------------------------------
    # Dash — SQL accuracy
    # -------------------------------------------------------------------------
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
        "entity_type": "team",
        "entity_id": "dash",
        "input": "How many customers signed up last month?",
        "expected_output": "A specific count of new customers from the previous month",
        "guidelines": "Must include a concrete number. Should reference the data source.",
    },
    # -------------------------------------------------------------------------
    # Research — analysis quality
    # -------------------------------------------------------------------------
    {
        "entity_type": "team",
        "entity_id": "research-coordinate",
        "input": "Research the current state of AI agent frameworks",
        "expected_output": "Comprehensive overview naming specific frameworks with market analysis",
        "guidelines": "Must name at least 3 specific frameworks. Must include market context.",
    },
    # -------------------------------------------------------------------------
    # Investment — financial accuracy
    # -------------------------------------------------------------------------
    {
        "entity_type": "team",
        "entity_id": "investment-coordinate",
        "input": "Analyze AAPL as an investment",
        "expected_output": "Investment analysis with fundamentals, technicals, and risk assessment",
        "guidelines": "Must include a valuation metric. Must discuss risk. Must give a recommendation.",
    },
]
