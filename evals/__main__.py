"""
Run evals.

Usage:
    # Smoke tests (fast, no LLM cost)
    python -m evals smoke
    python -m evals smoke --group agents
    python -m evals smoke --group security
    python -m evals smoke --entity knowledge
    python -m evals smoke --verbose

    # LLM-judged evals (deeper, costs money)
    python -m evals judge
    python -m evals judge --category security
    python -m evals judge --verbose

    # Backward compat
    python -m evals
    python -m evals --category security

    # Improvement data collector
    python -m evals improve --entity knowledge
    python -m evals improve --failures
"""

import argparse
import sys

from evals.client import AgentOSClient


def main() -> None:
    parser = argparse.ArgumentParser(description="Run AgentOS evals")
    subparsers = parser.add_subparsers(dest="command")

    # --- smoke ---
    smoke_parser = subparsers.add_parser("smoke", help="Pattern-matching smoke tests")
    smoke_parser.add_argument("--group", type=str, help="Filter by group: agents, teams, workflows, security, graceful")
    smoke_parser.add_argument("--entity", type=str, help="Filter by entity ID")
    smoke_parser.add_argument("--verbose", action="store_true", help="Show full responses")
    smoke_parser.add_argument("--url", type=str, help="Override base URL")
    smoke_parser.add_argument("--timeout", type=float, default=120.0, help="Default timeout in seconds")

    # --- judge ---
    judge_parser = subparsers.add_parser("judge", help="LLM-judged evals")
    judge_parser.add_argument("--category", type=str, help="Run a single eval category")
    judge_parser.add_argument("--verbose", action="store_true", help="Show detailed output")
    judge_parser.add_argument("--url", type=str, help="Override base URL")
    judge_parser.add_argument("--timeout", type=float, default=120.0, help="Default timeout in seconds")

    # --- improve ---
    improve_parser = subparsers.add_parser("improve", help="Collect improvement data for Claude Code")
    improve_parser.add_argument("--entity", type=str, help="Entity ID to collect data for")
    improve_parser.add_argument("--failures", action="store_true", help="Collect data for all failing entities")
    improve_parser.add_argument("--url", type=str, help="Override base URL")
    improve_parser.add_argument("--timeout", type=float, default=120.0, help="Default timeout in seconds")
    improve_parser.add_argument("--container", type=str, default="agno-demo-api", help="Docker container name")

    # --- backward compat flags at top level ---
    parser.add_argument("--category", type=str, help="(compat) Run a single eval category")
    parser.add_argument("--verbose", action="store_true", help="(compat) Show detailed output")

    args = parser.parse_args()

    if args.command == "smoke":
        client = AgentOSClient(base_url=args.url, timeout=args.timeout)
        from evals.smoke import run_smoke_tests

        results = run_smoke_tests(
            client,
            group=args.group,
            entity=args.entity,
            verbose=args.verbose,
        )
        has_failures = any(r["status"] in ("FAIL", "ERROR") for r in results)
        sys.exit(1 if has_failures else 0)

    elif args.command == "judge":
        from evals.judge import run_judge_evals

        client = AgentOSClient(base_url=args.url, timeout=args.timeout)
        success = run_judge_evals(
            client,
            category=args.category,
            verbose=args.verbose,
        )
        sys.exit(0 if success else 1)

    elif args.command == "improve":
        from evals.improve import run_improve

        client = AgentOSClient(base_url=args.url, timeout=args.timeout)
        run_improve(
            client,
            entity_id=args.entity,
            failures_only=args.failures,
            docker_container=args.container,
        )

    else:
        # Backward compat: no subcommand = judge
        from evals.judge import run_judge_evals

        client = AgentOSClient(timeout=120.0)
        success = run_judge_evals(
            client,
            category=args.category,
            verbose=args.verbose,
        )
        sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
