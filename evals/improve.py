"""
Improvement Data Collector
==========================

Runs an entity via HTTP, captures the response and Docker logs,
reads the instruction file, and prints everything to stdout.
Claude Code reads this output and decides what to change.

Usage (called BY Claude Code):
    python -m evals improve --entity knowledge
    python -m evals improve --entity dash
    python -m evals improve --failures
"""

from __future__ import annotations

from pathlib import Path

from evals.client import AgentOSClient
from evals.docker import DockerLogCapture
from evals.smoke import run_smoke_tests

INSTRUCTION_FILES: dict[str, str] = {
    # Agents
    "knowledge": "agents/knowledge/instructions.py",
    "mcp": "agents/mcp/instructions.py",
    "helpdesk": "agents/helpdesk/instructions.py",
    "feedback": "agents/feedback/instructions.py",
    "approvals": "agents/approvals/instructions.py",
    "reasoner": "agents/reasoner/instructions.py",
    "reporter": "agents/reporter/instructions.py",
    "contacts": "agents/contacts/instructions.py",
    "studio": "agents/studio/instructions.py",
    "scheduler": "agents/scheduler/instructions.py",
    # Teams
    "pal": "agents/pal/instructions.py",
    "dash": "agents/dash/instructions.py",
    "coda": "agents/coda/instructions.py",
    "research-coordinate": "teams/research/instructions.py",
    "research-route": "teams/research/instructions.py",
    "research-broadcast": "teams/research/instructions.py",
    "research-tasks": "teams/research/instructions.py",
    "investment-coordinate": "teams/investment/instructions.py",
    "investment-route": "teams/investment/instructions.py",
    "investment-broadcast": "teams/investment/instructions.py",
    "investment-tasks": "teams/investment/instructions.py",
    # Workflows
    "morning-brief": "workflows/morning_brief/instructions.py",
    "ai-research": "workflows/ai_research/instructions.py",
    "content-pipeline": "workflows/content_pipeline/instructions.py",
    "repo-walkthrough": "workflows/repo_walkthrough/instructions.py",
}

AGENT_DEFINITION_FILES: dict[str, str] = {
    # Agents
    "knowledge": "agents/knowledge/agent.py",
    "mcp": "agents/mcp/agent.py",
    "helpdesk": "agents/helpdesk/agent.py",
    "feedback": "agents/feedback/agent.py",
    "approvals": "agents/approvals/agent.py",
    "reasoner": "agents/reasoner/agent.py",
    "reporter": "agents/reporter/agent.py",
    "contacts": "agents/contacts/agent.py",
    "studio": "agents/studio/agent.py",
    "scheduler": "agents/scheduler/agent.py",
    # Teams
    "pal": "agents/pal/team.py",
    "dash": "agents/dash/team.py",
    "coda": "agents/coda/team.py",
    "research-coordinate": "teams/research/team.py",
    "research-route": "teams/research/team.py",
    "research-broadcast": "teams/research/team.py",
    "research-tasks": "teams/research/team.py",
    "investment-coordinate": "teams/investment/team.py",
    "investment-route": "teams/investment/team.py",
    "investment-broadcast": "teams/investment/team.py",
    "investment-tasks": "teams/investment/team.py",
    # Workflows
    "morning-brief": "workflows/morning_brief/workflow.py",
    "ai-research": "workflows/ai_research/workflow.py",
    "content-pipeline": "workflows/content_pipeline/workflow.py",
    "repo-walkthrough": "workflows/repo_walkthrough/workflow.py",
}

# Map entity_id to entity_type
ENTITY_TYPES: dict[str, str] = {
    "knowledge": "agent",
    "mcp": "agent",
    "helpdesk": "agent",
    "feedback": "agent",
    "approvals": "agent",
    "reasoner": "agent",
    "reporter": "agent",
    "contacts": "agent",
    "studio": "agent",
    "scheduler": "agent",
    "pal": "team",
    "dash": "team",
    "coda": "team",
    "research-coordinate": "team",
    "research-route": "team",
    "research-broadcast": "team",
    "research-tasks": "team",
    "investment-coordinate": "team",
    "investment-route": "team",
    "investment-broadcast": "team",
    "investment-tasks": "team",
    "morning-brief": "workflow",
    "ai-research": "workflow",
    "content-pipeline": "workflow",
    "repo-walkthrough": "workflow",
}


def _read_file(path: str) -> str:
    """Read a file, returning its contents or an error message."""
    abs_path = Path(path).resolve()
    try:
        return abs_path.read_text()
    except FileNotFoundError:
        return f"[FILE NOT FOUND: {abs_path}]"


def _get_smoke_results_for_entity(client: AgentOSClient, entity_id: str) -> list[dict]:
    """Run smoke tests for a specific entity and return results."""
    return run_smoke_tests(client, entity=entity_id)


def collect_improvement_data(
    client: AgentOSClient,
    entity_id: str,
    project_root: str = ".",
    docker_container: str = "agno-demo-api",
) -> str:
    """Collect all improvement data for a single entity. Returns formatted text."""
    entity_type = ENTITY_TYPES.get(entity_id)
    if not entity_type:
        return f"Unknown entity: {entity_id}"

    docker = DockerLogCapture(container=docker_container, project_root=project_root)

    # Run smoke tests for this entity
    smoke_results = _get_smoke_results_for_entity(client, entity_id)

    # Find a failing test to get the prompt, or use the first test
    failing = [r for r in smoke_results if r["status"] == "FAIL"]
    test_prompt = failing[0].get("prompt", "") if failing else None

    # If no specific failing prompt, use the smoke test prompt
    if not test_prompt:
        from evals.cases.smoke import all_smoke_tests

        entity_tests = [t for t in all_smoke_tests() if t.entity_id == entity_id and t.group != "security"]
        test_prompt = entity_tests[0].prompt if entity_tests else f"Hello, test for {entity_id}"

    # Run the entity and capture Docker logs
    mark = docker.mark()
    run_result = client.run(entity_type, entity_id, test_prompt)
    logs = docker.capture_since(mark)

    # Read instruction and agent definition files
    instruction_rel = INSTRUCTION_FILES.get(entity_id, "")
    definition_rel = AGENT_DEFINITION_FILES.get(entity_id, "")
    instruction_path = str(Path(project_root, instruction_rel).resolve()) if instruction_rel else ""
    definition_path = str(Path(project_root, definition_rel).resolve()) if definition_rel else ""

    # Format smoke results
    smoke_lines = []
    for r in smoke_results:
        line = f'{r["id"]}  {r["entity_id"]}  "{r.get("name", "")}"  {r["status"]}'
        if r.get("reason"):
            line += f"  {r['reason']}"
        smoke_lines.append(line)

    # Build output
    from datetime import datetime, timezone

    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    sections = [
        "=== IMPROVEMENT DATA ===",
        f"ENTITY_TYPE: {entity_type}",
        f"ENTITY_ID: {entity_id}",
        f"TIMESTAMP: {timestamp}",
        "",
        "=== SMOKE RESULTS ===",
        *smoke_lines,
        "",
        "=== RUN DETAIL ===",
        f"PROMPT: {test_prompt}",
        f"STATUS: {run_result.status_code}",
        f"DURATION: {run_result.duration}s",
        "",
        "--- RESPONSE ---",
        run_result.content or "[empty response]",
        "",
        "--- DOCKER LOGS ---",
        logs.stdout or "[no logs captured]",
    ]

    if logs.stderr:
        sections.extend(["", "--- DOCKER STDERR ---", logs.stderr])

    if instruction_path:
        sections.extend(
            [
                "",
                "=== INSTRUCTION FILE ===",
                f"PATH: {instruction_path}",
                "--- CONTENTS ---",
                _read_file(instruction_path),
            ]
        )

    if definition_path:
        sections.extend(
            [
                "",
                "=== AGENT DEFINITION ===",
                f"PATH: {definition_path}",
                "--- CONTENTS ---",
                _read_file(definition_path),
            ]
        )

    sections.append("\n=== END ===")

    return "\n".join(sections)


def run_improve(
    client: AgentOSClient,
    entity_id: str | None = None,
    failures_only: bool = False,
    project_root: str = ".",
    docker_container: str = "agno-demo-api",
) -> None:
    """Main entry point for the improvement data collector."""
    if failures_only:
        # Run full smoke suite, collect failures
        print("Running smoke tests to find failures...\n")
        results = run_smoke_tests(client)
        failed_ids = list({r["entity_id"] for r in results if r["status"] == "FAIL"})

        if not failed_ids:
            print("\nAll smoke tests passed — nothing to improve.")
            return

        print(f"\nFailing entities: {', '.join(sorted(failed_ids))}\n")
        print("=" * 60)

        for eid in sorted(failed_ids):
            output = collect_improvement_data(client, eid, project_root, docker_container)
            print(output)
            print("\n" + "=" * 60 + "\n")
    elif entity_id:
        output = collect_improvement_data(client, entity_id, project_root, docker_container)
        print(output)
    else:
        print("Usage: python -m evals improve --entity <id> | --failures")
