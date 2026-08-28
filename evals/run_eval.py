#!/usr/bin/env python3
"""Scores the Crux gate against the golden set.

Two numbers matter and they pull against each other:

  recall       of the known-bad debates, what fraction did the gate block?
  false block  of the known-good debates, what fraction did the gate block anyway?

A gate with 100% recall and a 30% false-block rate is a gate nobody keeps
switched on. Reporting only recall is how that ships.

Offline mode (default) exercises the deterministic layer alone — no API key,
runs in well under a second, and is the right thing to put in CI. It reports
the model-only cases as ESCAPED, because from code's point of view they did.

Live mode additionally runs the mediator on every case the deterministic
layer let through, and applies crux_report_checks — the same recomputed
quality gate the orchestrator uses. Whether the mediator actually catches the
four model-only failure shapes is the open question live mode would answer.
It has not been run — this project makes no API calls.

    python run_eval.py                 # deterministic layer only
    python run_eval.py --live          # adds real mediator calls (costs money)
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "orchestrator"))

from run import (  # noqa: E402
    deterministic_checks, crux_report_checks, reading_order,
    build_mediator_prompt, validate_schema, MODELS, MAX_TOKENS, load_skill,
)
from jsonio import extract_json  # noqa: E402


def load_cases(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def mediate_live(pack: dict, optimist: dict, pessimist: dict) -> dict:
    import anthropic
    client = anthropic.Anthropic()
    first, _ = reading_order(0)
    schema_text = (ROOT / "contracts" / "crux_report.schema.json").read_text(encoding="utf-8")
    resp = client.messages.create(
        model=MODELS["mediator"],
        max_tokens=MAX_TOKENS["mediator"],
        system=load_skill("mediator") + f"\n\n## Output schema\n```json\n{schema_text}\n```",
        messages=[{"role": "user", "content": build_mediator_prompt(pack, optimist, pessimist, first)}],
    )
    return extract_json(resp)


def evaluate(cases: list[dict], live: bool) -> list[dict]:
    rows = []
    failures: list[tuple[str, str]] = []
    for c in cases:
        code_ok, problems = deterministic_checks(c["pack"], c["optimist"], c["pessimist"])
        blocked_by = None if code_ok else "code"

        if live and code_ok:
            try:
                report = mediate_live(c["pack"], c["optimist"], c["pessimist"])
                sch_ok, sch_detail = validate_schema(report, "crux_report.schema.json")
                if not sch_ok:
                    blocked_by, problems = "model", [f"schema: {sch_detail}"]
                else:
                    q_ok, q_problems = crux_report_checks(report)
                    if not q_ok:
                        blocked_by, problems = "model", q_problems
            except Exception as e:                      # noqa: BLE001
                detail = e.detail() if hasattr(e, "detail") else str(e)
                failures.append((c["id"], detail))
                problems = [f"mediator call failed: {e}"]

        blocked = blocked_by is not None
        should_block = c["label"] == "bad"

        if should_block and blocked:
            outcome = "CAUGHT"
        elif should_block and not blocked:
            outcome = "ESCAPED"
        elif not should_block and blocked:
            outcome = "FALSE BLOCK"
        else:
            outcome = "PASSED"

        rows.append({**c, "blocked_by": blocked_by, "outcome": outcome,
                     "detail": "; ".join(problems)[:150]})

    if failures:
        print("\n" + "!" * 78)
        print("MEDIATOR CALLS FAILED — infrastructure errors, not gate results.")
        print("The recall number below is meaningless until these are fixed.")
        print("!" * 78)
        for cid, detail in failures[:3]:
            print(f"\n[{cid}]\n{detail}")
        print("!" * 78)

    return rows


def report(rows: list[dict], live: bool) -> int:
    mode = "LIVE (deterministic + mediator)" if live else "OFFLINE (deterministic layer only)"
    print("=" * 78)
    print(f"Crux gate evaluation — {mode}")
    print("=" * 78)
    print(f"{'id':<5}{'expected':<10}{'caught_by':<11}{'result':<13}detail")
    print("-" * 78)
    for r in rows:
        exp = "block" if r["label"] == "bad" else "pass"
        print(f"{r['id']:<5}{exp:<10}{(r['caught_by'] or '-'):<11}{r['outcome']:<13}{r['detail'][:38]}")

    bad = [r for r in rows if r["label"] == "bad"]
    good = [r for r in rows if r["label"] == "good"]
    caught = [r for r in bad if r["outcome"] == "CAUGHT"]
    escaped = [r for r in bad if r["outcome"] == "ESCAPED"]
    false_blocks = [r for r in good if r["outcome"] == "FALSE BLOCK"]

    recall = len(caught) / len(bad) if bad else 0
    fbr = len(false_blocks) / len(good) if good else 0

    print("-" * 78)
    print(f"recall             {len(caught)}/{len(bad)}   {recall:.0%}   (known-bad debates blocked)")
    print(f"false block rate   {len(false_blocks)}/{len(good)}   {fbr:.0%}   (known-good debates blocked)")

    by = Counter(r["blocked_by"] for r in caught)
    print(f"blocked by code    {by.get('code', 0)}")
    print(f"blocked by model   {by.get('model', 0)}")

    if escaped:
        print("\nESCAPED:")
        for r in escaped:
            print(f"  {r['id']}  {r['failure_mode']:<26} (needs: {r['caught_by']})")
        if not live:
            print("\n  Expected offline. These require the mediator's judgment, not arithmetic.")
            print("  Re-run with --live to measure whether the mediator catches them.")

    print("=" * 78)
    return 1 if false_blocks else 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--live", action="store_true", help="also call the mediator model")
    ap.add_argument("--set", default=str(Path(__file__).parent / "golden_set.jsonl"))
    args = ap.parse_args()
    rows = evaluate(load_cases(Path(args.set)), args.live)
    return report(rows, args.live)


if __name__ == "__main__":
    sys.exit(main())
