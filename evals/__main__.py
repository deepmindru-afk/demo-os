"""
Run Evals
=========

python -m evals                # run all cases (concise UI)
python -m evals --case <name>  # run one case
python -m evals -v             # stream the agent's run with full panels

Each case runs the agent once (or, for the structural gate, runs a deterministic
check with no model) and applies its checks:

- **structural** — a deterministic toolset assertion. No agent run, no tokens.
- **reliability** — `ReliabilityEval`, asserts the expected tools fired.
- **capture-only** — for guest runs, asserts no read/act tool fired (trace level).
- **judge** — `AgentAsJudgeEval`, an LLM rubric (binary pass/fail).

The judge logs to Postgres through `eval_db`; connect your AgentOS at
os.agno.com to see history. (The structural gate has no Agno eval primitive, so
it shows in the CLI summary, not the platform.)

Exit 0 on all-pass, non-zero on any failure or error.
"""

# Hydrate os.environ from .env before any module that reads env at import time
# (db_url, model factories, etc.). Pre-existing shell vars take precedence.
from evals.dotenv import load_dotenv

load_dotenv()

# Pin a deterministic owner identity for the eval run. Owner-path cases use
# user_id="eval-owner" (full toolset); guest cases use a different id. Must be
# set before importing evals.cases (→ agents.context → app.identity reads
# OWNER_ID at import time). Process-local — never touches the container.
from os import environ  # noqa: E402

environ["OWNER_ID"] = "eval-owner"

import asyncio  # noqa: E402
from contextlib import suppress  # noqa: E402
from dataclasses import dataclass  # noqa: E402
from uuid import uuid4  # noqa: E402

import typer  # noqa: E402
from agno.eval import AgentAsJudgeEval, ReliabilityEval  # noqa: E402
from agno.run.agent import RunOutput  # noqa: E402
from rich.console import Console  # noqa: E402
from rich.live import Live  # noqa: E402
from rich.status import Status  # noqa: E402
from rich.table import Table  # noqa: E402

from agents.inbox import CAPTURE_ONLY_TOOLS  # noqa: E402
from agents.sources import close_context_providers  # noqa: E402
from evals.cases import CASES, Case, eval_db  # noqa: E402

app = typer.Typer(add_completion=False, no_args_is_help=False, pretty_exceptions_show_locals=False)
console = Console()


@dataclass
class CaseOutcome:
    name: str
    structural_passed: bool | None = None
    judge_passed: bool | None = None
    reliability_passed: bool | None = None
    capture_passed: bool | None = None
    error: str | None = None

    @property
    def passed(self) -> bool:
        if self.error:
            return False
        checks = [
            c
            for c in (self.structural_passed, self.judge_passed, self.reliability_passed, self.capture_passed)
            if c is not None
        ]
        return bool(checks) and all(checks)


async def _run_case_async(case: Case, *, verbose: bool) -> CaseOutcome:
    # Deterministic structural gate — no agent run, no LLM, no tokens.
    if case.structural is not None:
        return _run_structural(case)

    judge_passed: bool | None = None
    rel_passed: bool | None = None
    capture_passed: bool | None = None
    judge_err: str | None = None
    rel_err: str | None = None
    capture_err: str | None = None

    # Dedicated session_id per case so eval traffic doesn't bleed into agent
    # history, and so verbose mode can fetch the run back via aget_last_run_output.
    session_id = f"eval-{case.name}-{uuid4().hex[:8]}"

    response: RunOutput | None
    try:
        if verbose:
            # Stream the agent run with rich panels (Message → Tool Calls →
            # Response), same UI as os.agno.com. aprint_response returns None,
            # so fetch the RunOutput from storage afterward for the eval checks.
            await case.agent.aprint_response(
                input=case.input,
                stream=True,
                session_id=session_id,
                user_id=case.user_id,
                markdown=True,
            )
            response = await case.agent.aget_last_run_output(session_id=session_id)
        else:
            response = await _run_with_live_spinner(case, session_id)
        if response is None:
            return CaseOutcome(name=case.name, error="agent: no run output recorded")
    except Exception as exc:
        return CaseOutcome(name=case.name, error=f"agent.arun: {type(exc).__name__}: {exc}")

    output_str = str(response.content) if response.content else ""

    if not verbose:
        _print_response_concise(response, output_str)

    # Capture-only (deterministic): for a guest run, every tool that fired must
    # be on the capture-only allowlist — proof at the trace level that the agent
    # called no read/act tool, whatever it was asked to do.
    if case.capture_only:
        fired = [t.tool_name for t in (response.tools or []) if t.tool_name]
        leaked = sorted({n for n in fired if n not in CAPTURE_ONLY_TOOLS})
        capture_passed = not leaked
        if leaked:
            capture_err = f"capture-only: guest fired non-allowlisted tool(s): {leaked}"
        if not verbose:
            _print_capture_verdict(capture_passed, leaked)

    if case.expected_tool_calls is not None:
        try:
            rel = ReliabilityEval(
                name=case.name,
                agent_response=response,
                expected_tool_calls=list(case.expected_tool_calls),
                allow_additional_tool_calls=case.allow_additional_tool_calls,
                db=eval_db,
            ).run(print_results=verbose)
        except Exception as exc:
            rel_err = f"reliability: {type(exc).__name__}: {exc}"
        else:
            if rel is None:
                rel_err = "reliability: returned no result"
            else:
                rel_passed = rel.eval_status == "PASSED"
                if not verbose:
                    _print_reliability_verdict(rel, case.expected_tool_calls)

    if case.criteria is not None:
        try:
            judge = await AgentAsJudgeEval(
                name=case.name,
                criteria=case.criteria,
                additional_guidelines=list(case.judge_guidelines) if case.judge_guidelines else None,
                scoring_strategy="binary",
                db=eval_db,
            ).arun(input=case.input, output=output_str, print_results=verbose)
        except Exception as exc:
            judge_err = f"judge: {type(exc).__name__}: {exc}"
        else:
            if judge and judge.results:
                judge_passed = judge.results[0].passed
                if not verbose:
                    _print_judge_verdict(judge.results[0])
            else:
                judge_err = "judge: returned no result"

    return CaseOutcome(
        name=case.name,
        judge_passed=judge_passed,
        reliability_passed=rel_passed,
        capture_passed=capture_passed,
        error="; ".join(e for e in (capture_err, rel_err, judge_err) if e) or None,
    )


def _run_structural(case: Case) -> CaseOutcome:
    """Run a deterministic structural gate (no agent, no LLM)."""
    assert case.structural is not None
    try:
        passed, detail = case.structural()
    except Exception as exc:
        return CaseOutcome(name=case.name, error=f"structural: {type(exc).__name__}: {exc}")
    style = "green" if passed else "red"
    tag = "PASS" if passed else "FAIL"
    console.print(f"\n[bold]Structural gate:[/bold] [{style}]{tag}[/{style}]")
    console.print(f"[dim]  {detail}[/dim]")
    return CaseOutcome(
        name=case.name,
        structural_passed=passed,
        error=None if passed else f"structural: {detail}",
    )


async def _run_with_live_spinner(case: Case, session_id: str) -> RunOutput | None:
    """Stream the agent's run with a single-line spinner that updates per tool call.

    Avoids freezing the screen during long agent calls without spamming the user
    with the full streaming UI. Captures the final RunOutput via yield_run_output.
    """
    base_label = f"[bold]running[/bold] {case.agent.id}…"
    spinner = Status(base_label, spinner="dots")

    response: RunOutput | None = None
    with Live(spinner, console=console, transient=True, refresh_per_second=10):
        async for event in case.agent.arun(
            input=case.input,
            stream=True,
            stream_events=True,
            yield_run_output=True,
            session_id=session_id,
            user_id=case.user_id,
        ):
            if isinstance(event, RunOutput):
                response = event
                continue
            event_type = getattr(event, "event", None)
            if event_type == "ToolCallStarted":
                tool = getattr(event, "tool", None)
                tool_name = getattr(tool, "tool_name", None)
                if tool_name:
                    spinner.update(f"[bold]running[/bold] {case.agent.id} → [cyan]{tool_name}[/cyan]…")
            elif event_type == "ToolCallCompleted":
                spinner.update(base_label)

    return response


def _print_response_concise(response: RunOutput, output_str: str) -> None:
    """Plain-text response + one-line tool summary. Used in default (non-verbose) mode."""
    console.print()
    console.print("[bold]Response[/bold]")
    console.print(output_str or "[dim](empty)[/dim]")

    tools = response.tools or []
    if tools:
        names = ", ".join(t.tool_name or "?" for t in tools)
        console.print(f"\n[dim]tools fired:[/dim] {names}")


def _print_judge_verdict(eval_result: object) -> None:
    passed: bool = bool(getattr(eval_result, "passed", False))
    reason: str = str(getattr(eval_result, "reason", "") or "")
    style = "green" if passed else "red"
    tag = "PASS" if passed else "FAIL"
    console.print(f"\n[bold]Judge:[/bold] [{style}]{tag}[/{style}]")
    if reason:
        console.print(f"[dim]  {reason}[/dim]")


def _print_reliability_verdict(rel_result: object, expected_tools: tuple[str, ...]) -> None:
    passed = getattr(rel_result, "eval_status", "") == "PASSED"
    style = "green" if passed else "red"
    tag = "PASS" if passed else "FAIL"
    expected = ", ".join(expected_tools)
    console.print(f"\n[bold]Reliability:[/bold] [{style}]{tag}[/{style}]  [dim]expected: {expected}[/dim]")


def _print_capture_verdict(passed: bool, leaked: list[str]) -> None:
    style = "green" if passed else "red"
    tag = "PASS" if passed else "FAIL"
    detail = "no read/act tool fired" if passed else f"leaked: {', '.join(leaked)}"
    console.print(f"\n[bold]Capture-only:[/bold] [{style}]{tag}[/{style}]  [dim]{detail}[/dim]")


def _checks_cell(o: CaseOutcome) -> str:
    """Compact per-case check summary for the recap table."""
    parts: list[str] = []
    for label, value in (
        ("gate", o.structural_passed),
        ("tools", o.reliability_passed),
        ("capture", o.capture_passed),
        ("judge", o.judge_passed),
    ):
        if value is None:
            continue
        style = "green" if value else "red"
        mark = "✓" if value else "✗"
        parts.append(f"[{style}]{label} {mark}[/{style}]")
    return "  ".join(parts) if parts else "[dim]—[/dim]"


async def _run_suite(cases: list[Case], *, verbose: bool) -> list[CaseOutcome]:
    """Run every case in a single event loop, then release provider resources.

    One loop (rather than asyncio.run per case) lets us close the providers'
    async clients (MCP/httpx) inside the loop in a finally — without it their
    teardown lands after the loop is gone and prints 'Event loop is closed'.
    """
    outcomes: list[CaseOutcome] = []
    try:
        for i, c in enumerate(cases, 1):
            console.rule(f"[bold]{c.name}[/bold]  [dim]{c.agent.id} · {i}/{len(cases)}[/dim]")
            outcomes.append(await _run_case_async(c, verbose=verbose))
    finally:
        with suppress(Exception):
            await close_context_providers()
    return outcomes


@app.callback(invoke_without_command=True)
def main(
    ctx: typer.Context,
    case: str = typer.Option(None, "--case", help="Run only this case by name"),
    verbose: bool = typer.Option(
        False,
        "--verbose",
        "-v",
        help="Stream the full agent run with rich panels (Message → Tool Calls → Response), plus full eval tables.",
    ),
) -> None:
    """Run the eval suite, or one case with --case <name>."""
    if ctx.invoked_subcommand is not None:
        return

    cases = list(CASES)
    if case:
        cases = [c for c in cases if c.name == case]
        if not cases:
            console.print(f"[red]no case named[/red] {case!r}")
            console.print(f"  [dim]available:[/dim] {', '.join(c.name for c in CASES)}")
            raise typer.Exit(2)

    outcomes = asyncio.run(_run_suite(cases, verbose=verbose))

    table = Table(title="Eval Summary", title_style="bold sky_blue1", show_header=True, header_style="bold")
    table.add_column("Case", overflow="fold")
    table.add_column("Checks", overflow="fold")
    table.add_column("Status")
    for o in outcomes:
        status = "[green]PASS[/green]" if o.passed else "[red]FAIL[/red]"
        table.add_row(o.name, _checks_cell(o), status)

    console.print()
    console.print(table)

    passed = sum(1 for o in outcomes if o.passed)
    failed = len(outcomes) - passed
    summary = f"[green]{passed}/{len(outcomes)} passed[/green]"
    if failed:
        summary += f", [red]{failed} failed[/red]"
    console.print(f"\n{summary}")

    for o in outcomes:
        if o.error:
            console.print(f"  [dim]{o.name}:[/dim] [red]{o.error}[/red]")

    raise typer.Exit(0 if failed == 0 else 1)


if __name__ == "__main__":
    app()
