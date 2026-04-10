"""
Run AgentOS evals.

Usage:
    # Agno evals — LLM-judged via AgentAsJudgeEval and AccuracyEval
    python -m evals                              # All categories
    python -m evals --category security           # Single category
    python -m evals --verbose                     # Show judge reasoning

    # Smoke tests — fast pattern matching, no LLM cost
    python -m evals smoke                         # All entities
    python -m evals smoke --group agents           # By group
    python -m evals smoke --entity knowledge       # Single entity
    python -m evals smoke --verbose

    # Auto-improvement data collector
    python -m evals improve --entity knowledge
    python -m evals improve --failures

    # Global flags
    python -m evals --url http://prod.example.com
    python -m evals --timeout 180
"""

import argparse
import sys

from evals.client import AgentOSClient


def main() -> None:
    parser = argparse.ArgumentParser(description="Run AgentOS evals")
    subparsers = parser.add_subparsers(dest="command")

    # --- smoke ---
    smoke_parser = subparsers.add_parser("smoke", help="Fast pattern-matching smoke tests (no LLM cost)")
    smoke_parser.add_argument(
        "--group",
        type=str,
        help="Filter: agents, teams, workflows, security, graceful",
    )
    smoke_parser.add_argument("--entity", type=str, help="Filter by entity ID")
    smoke_parser.add_argument("--verbose", action="store_true", help="Show full responses")
    smoke_parser.add_argument("--url", type=str, help="Override base URL")
    smoke_parser.add_argument("--timeout", type=float, default=120.0, help="Default timeout (seconds)")

    # --- improve ---
    improve_parser = subparsers.add_parser("improve", help="Collect improvement data for Claude Code")
    improve_parser.add_argument("--entity", type=str, help="Entity ID to collect data for")
    improve_parser.add_argument(
        "--failures",
        action="store_true",
        help="Collect data for all failing entities",
    )
    improve_parser.add_argument("--url", type=str, help="Override base URL")
    improve_parser.add_argument("--timeout", type=float, default=120.0, help="Default timeout (seconds)")
    improve_parser.add_argument(
        "--container",
        type=str,
        default="agno-demo-api",
        help="Docker container name",
    )

    # --- top-level flags (default: run Agno evals) ---
    parser.add_argument("--category", type=str, help="Run a single eval category")
    parser.add_argument("--verbose", action="store_true", help="Show detailed output")
    parser.add_argument("--url", type=str, help="Override base URL")
    parser.add_argument("--timeout", type=float, default=120.0, help="Default timeout (seconds)")

    args = parser.parse_args()

    if args.command == "smoke":
        from evals.smoke import run_smoke_tests

        client = AgentOSClient(base_url=args.url, timeout=args.timeout)
        results = run_smoke_tests(
            client,
            group=args.group,
            entity=args.entity,
            verbose=args.verbose,
        )
        has_failures = any(r["status"] in ("FAIL", "ERROR") for r in results)
        sys.exit(1 if has_failures else 0)

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
        # Default: run Agno evals (AgentAsJudgeEval, AccuracyEval)
        from evals.run import run_evals

        client = AgentOSClient(base_url=args.url, timeout=args.timeout)
        success = run_evals(
            client,
            category=args.category,
            verbose=args.verbose,
        )
        sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
