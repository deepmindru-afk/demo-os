"""Smoke test cases for the 4 workflows."""

from evals.cases.smoke import SmokeTest

WORKFLOW_TESTS: list[SmokeTest] = [
    SmokeTest(
        id="w.1",
        name="morning-brief — daily briefing",
        entity_type="workflow",
        entity_id="morning-brief",
        group="workflows",
        prompt="Generate my morning briefing",
        response_matches=[r"(?i)(brief|calendar|email|news)"],
    ),
    SmokeTest(
        id="w.2",
        name="ai-research — AI today",
        entity_type="workflow",
        entity_id="ai-research",
        group="workflows",
        prompt="What's happening in AI today?",
        response_matches=[r"(?i)(ai|research|model)"],
        requires=["EXA_API_KEY"],
    ),
    SmokeTest(
        id="w.3",
        name="content-pipeline — AI agents post",
        entity_type="workflow",
        entity_id="content-pipeline",
        group="workflows",
        prompt="Write a short post about AI agents",
        response_matches=[r"(?i)(agent|content|ai)"],
        timeout=180.0,
    ),
    SmokeTest(
        id="w.4",
        name="repo-walkthrough — Pal codebase",
        entity_type="workflow",
        entity_id="repo-walkthrough",
        group="workflows",
        prompt="Walk me through the Pal codebase",
        response_matches=[r"(?i)(pal|code|agent|team)"],
    ),
]
