# Crux — context for Claude Code

## What this is

A parallel optimist / pessimist / mediator topology for open judgment calls
where there is **no ground truth** — only two competing arguments and, usually,
one unlooked-up fact underneath them. The mediator's deliverable is the
*crux*: the single unknown that would settle the disagreement.

It is the deliberate contrast to the sibling repo AgentDesk (`../agentdesk`),
which is a linear pipeline for tasks where ground truth *does* exist. Same
engineering spine — typed contracts, schema validation, deterministic checks
before model calls, an honest limitations section. Different shape. **The
contrast is the product.** Read `README.md` first.

## How to work in this repo

- **Explain before you change.** Say what you're about to do in plain terms
  and why, then do it. The person who owns this needs to explain it in
  interviews and has no CS background.
- **Comment the reasoning, not the syntax.** `# symmetry check runs even when
  both positions pass the word budget, because 260 vs 200 still biases the
  mediator` is useful. `# loop over positions` is not.
- **Say when something is a judgment call**, not a fact. Whoever reads this
  needs to know which parts they could defend differently.

## Invariants — do not "fix" these

Each looks like a bug and is a deliberate decision. Changing any without being
asked destroys the thing the repo demonstrates.

1. **The optimist and pessimist never see each other's output.** Both model
   calls get the byte-identical `pack_prompt`. Do not "improve" one debater by
   showing it the other's position — that turns an argument into a rebuttal.
2. **A position that references an opponent is rejected** (phantom-opponent
   check). The debaters were never shown an opposing view; acknowledging one
   is a hallucination.
3. **Both positions get the identical word budget, recomputed in code.** The
   model's self-reported `word_count` is never trusted. Do not raise
   `WORD_TOLERANCE` to get a run to pass.
4. **`SYMMETRY_MAX_RATIO = 1.25` does not move.** It fires independently of the
   word budget. Loosening it re-opens the "longer argument reads as stronger"
   bias the check exists to close.
5. **Order randomization, with the seed logged.** Do not remove the seed from
   `run_meta` / `runs.jsonl`. Reproducibility and bias-auditing both depend on
   it.
6. **The mediator runs on a different model family than the debaters.** A
   model synthesizing arguments from its own family shares that family's blind
   spots. Do not unify the model config to "simplify."
7. **The mediator introduces no new claims.** It has no search tools and works
   only from the two positions and the pack. Same reason AgentDesk's QA
   reviewer has no search.
8. **`primary_crux` is filled before any verdict**, and `crux_report_checks()`
   enforces it in code. A verdict with a vague crux is the averaging behavior
   this system exists to block.
9. **`verdict_withheld: true` is a success outcome**, not indecision. A
   mediator that always issues a lean is averaging.
10. **Single pass. No retry budget.** This is the intentional opposite of
    AgentDesk's `MAX_REVISIONS = 2`. A broken position is rejected, not sent
    back. Do not add a revision loop.
11. **Malformed agent output is rejected without retry** (`ContractError`). A
    model that can't produce the schema is a prompt bug.
12. **`jsonio.py` is a copy of AgentDesk's, on purpose.** Do not replace it
    with a cross-repo import. If it needs a fix, fix it in both places.

## Generated files — edit the generator, not the output

| Generated | Generator |
|---|---|
| `orchestrator/fixtures/dry_run.json` | `orchestrator/fixtures/_build_fixtures.py` |
| `evals/golden_set.jsonl` | `evals/build_golden_set.py` |

Each generator self-checks on run (word counts, symmetry ratios, and that the
"good" eval cases actually pass the real gate). Hand-editing the output skips
those checks.

## Commands

```bash
python orchestrator/run.py --dry-run                              # REPORT, verdict withheld
python orchestrator/run.py --dry-run --scenario resolved_crux     # REPORT, verdict issued
python orchestrator/run.py --dry-run --scenario asymmetric        # REJECTED (symmetry + budget)
python orchestrator/run.py --dry-run --scenario phantom_opponent  # REJECTED (phantom opponent)
python orchestrator/run.py --dry-run --scenario false_consensus   # REPORT, consensus
python orchestrator/run.py --pack path/to/pack.json               # live, needs ANTHROPIC_API_KEY
python evals/run_eval.py                                          # offline gate score
python evals/run_eval.py --live                                   # adds real mediator calls (costs money)
python orchestrator/test_jsonio.py                                # parser tests
```

Windows: `.\setup.ps1` runs all of the offline commands as one pass.

## Definition of done for any change

1. All five `--dry-run` scenarios still produce their expected terminal state
   (`setup.ps1` checks this).
2. `python evals/run_eval.py` still shows **0 false blocks**.
3. Any new failure mode discovered gets added to `evals/build_golden_set.py`
   as its own mutation — the golden set grows and never shrinks.
4. If a known limitation was resolved, remove it from `README.md`; if a new
   one was introduced, add it.

## Current state

Working and verified on fixtures: the orchestrator, all five scenarios, the
offline eval (67% recall, 0% false blocks), the parser tests.

`orchestrator/fixtures/example_pack.json` is a real evidence_pack for anyone
who wants to try `--pack` live (it is the `clean_disagreement` pack).

One live run now exists (`--pack orchestrator/fixtures/example_pack.json`,
real Sonnet/Sonnet/Opus calls) — see README.md → "The demo question" for the
real result. The first attempt hit a real infra bug (pessimist call
truncated at the old `MAX_TOKENS=8000`; extended thinking on Claude 5 models
draws from the same budget as the visible reply). Fixed by raising all three
budgets to 16000, same fix AgentDesk made for the identical bug. The retry
produced a clean `REPORT`, verdict withheld, crux correctly named.

Not done: `run_eval.py --live` is unrun. The five dry-run scenarios have
never been run live. One clean execution is not a measured live failure
rate. There is no cost ceiling. Do not describe any of these as done.

## Do not touch

- `ANTHROPIC_API_KEY` — this project runs on fixtures only.
- The `../agentdesk` repo — separate project, separate git repo.
