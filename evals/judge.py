"""
HTTP-Based LLM Judge Runner
============================

Runs LLM-judged evals via the AgentOS HTTP API (no Python imports).

Usage:
    from evals.judge import run_judge_evals
    from evals.client import AgentOSClient

    client = AgentOSClient()
    success = run_judge_evals(client, category="security", verbose=True)
"""

from __future__ import annotations

import time
from typing import Callable

from agno.eval.accuracy import AccuracyEval
from agno.eval.agent_as_judge import AgentAsJudgeEval

from evals import JUDGE_MODEL
from evals.client import AgentOSClient


def _run_security(client: AgentOSClient, verbose: bool = False) -> list[dict]:
    """Run security eval across all entities via HTTP."""
    from evals.cases.security import CASES, CRITERIA, ENTITIES

    judge = AgentAsJudgeEval(
        name="Security",
        criteria=CRITERIA,
        scoring_strategy="binary",
        model=JUDGE_MODEL,
    )

    total = len(ENTITIES) * len(CASES)
    results: list[dict] = []
    counter = 0

    for entity_type, entity_id in ENTITIES:
        for question in CASES:
            counter += 1
            print(f"  [{counter}/{total}] {entity_id}: {question[:50]}...")
            start = time.time()

            try:
                run_result = client.run(entity_type, entity_id, question)
                duration = round(time.time() - start, 2)

                if run_result.error:
                    result = {
                        "entity_id": entity_id,
                        "question": question,
                        "category": "security",
                        "status": "ERROR",
                        "duration": duration,
                        "reason": run_result.error,
                    }
                else:
                    eval_result = judge.run(input=question, output=run_result.content)
                    passed = eval_result is not None and eval_result.pass_rate == 100.0
                    result = {
                        "entity_id": entity_id,
                        "question": question,
                        "category": "security",
                        "status": "PASS" if passed else "FAIL",
                        "duration": duration,
                    }
                    if not passed and eval_result and eval_result.results:
                        result["reason"] = eval_result.results[0].reason

            except Exception as e:
                result = {
                    "entity_id": entity_id,
                    "question": question,
                    "category": "security",
                    "status": "ERROR",
                    "duration": round(time.time() - start, 2),
                    "reason": str(e),
                }

            results.append(result)
            _print_status(result, verbose)

    return results


def _run_accuracy(client: AgentOSClient, verbose: bool = False) -> list[dict]:
    """Run accuracy eval for select entities via HTTP."""
    from evals.cases.accuracy import CASES

    results: list[dict] = []

    for i, case in enumerate(CASES, 1):
        entity_type = case["entity_type"]
        entity_id = case["entity_id"]
        question = case["input"]
        expected = case["expected_output"]
        guidelines = case.get("guidelines")

        print(f"  [{i}/{len(CASES)}] {entity_id}: {question[:50]}...")
        start = time.time()

        try:
            run_result = client.run(entity_type, entity_id, question)
            duration = round(time.time() - start, 2)

            if run_result.error:
                result = {
                    "entity_id": entity_id,
                    "question": question,
                    "category": "accuracy",
                    "status": "ERROR",
                    "duration": duration,
                    "reason": run_result.error,
                }
            else:
                eval_obj = AccuracyEval(
                    name=f"Accuracy: {question[:40]}",
                    input=question,
                    expected_output=expected,
                    model=JUDGE_MODEL,
                    additional_guidelines=guidelines,
                )
                eval_result = eval_obj.run_with_output(output=run_result.content)

                passed = eval_result is not None and eval_result.avg_score >= 7.0
                result = {
                    "entity_id": entity_id,
                    "question": question,
                    "category": "accuracy",
                    "status": "PASS" if passed else "FAIL",
                    "duration": duration,
                }
                if eval_result and eval_result.results:
                    result["score"] = eval_result.results[0].score
                    if not passed:
                        result["reason"] = eval_result.results[0].reason

        except Exception as e:
            result = {
                "entity_id": entity_id,
                "question": question,
                "category": "accuracy",
                "status": "ERROR",
                "duration": round(time.time() - start, 2),
                "reason": str(e),
            }

        results.append(result)
        _print_status(result, verbose)

    return results


JUDGE_RUNNERS: dict[str, Callable[..., list[dict]]] = {
    "security": _run_security,
    "accuracy": _run_accuracy,
}


def _print_status(result: dict, verbose: bool) -> None:
    icon = {"PASS": "PASS", "FAIL": "FAIL", "ERROR": "ERR "}.get(result["status"], "??? ")
    score = f" (score: {result['score']})" if "score" in result else ""
    print(f"         {icon} ({result['duration']}s){score}")
    if verbose and result.get("reason"):
        print(f"         Reason: {result['reason']}")


def run_judge_evals(
    client: AgentOSClient,
    category: str | None = None,
    verbose: bool = False,
) -> bool:
    """Run LLM-judged eval categories via HTTP.

    Returns True if all cases passed, False otherwise.
    """
    all_results: list[dict] = []
    total_start = time.time()

    categories = JUDGE_RUNNERS
    if category:
        if category not in categories:
            print(f"Unknown category: {category}. Available: {', '.join(categories)}")
            return False
        categories = {category: categories[category]}

    for name, runner in categories.items():
        print(f"\n--- {name} ---\n")
        all_results.extend(runner(client, verbose))

    if not all_results:
        print("No judge cases found.")
        return False

    total_duration = round(time.time() - total_start, 2)
    passed = sum(1 for r in all_results if r["status"] == "PASS")
    failed = sum(1 for r in all_results if r["status"] == "FAIL")
    errors = sum(1 for r in all_results if r["status"] == "ERROR")

    print(f"\n{'=' * 50}")
    print(f"Results: {passed} passed, {failed} failed, {errors} errors ({total_duration}s)")
    print(f"{'=' * 50}\n")

    return failed + errors == 0
