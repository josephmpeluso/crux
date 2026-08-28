# Crux

**A parallel debate that ends by naming the one fact that would settle it.**

Two agents — an optimist and a pessimist — build the strongest case they can
for and against a decision, in isolation, from the same evidence. A mediator
reads both and does one job: find the *crux*, the single unknown that, if you
resolved it, would end the disagreement. Then it decides whether a verdict is
even warranted yet.

```bash
pip install anthropic jsonschema

python orchestrator/run.py --dry-run                                # crux named, verdict withheld
python orchestrator/run.py --dry-run --scenario resolved_crux       # crux resolved in-pack, verdict issued
python orchestrator/run.py --dry-run --scenario asymmetric          # rejected: one side 2x the other
python orchestrator/run.py --dry-run --scenario phantom_opponent    # rejected: a side rebuts a view it never saw
python orchestrator/run.py --dry-run --scenario false_consensus     # both sides agree; reported as consensus
python evals/run_eval.py                                            # scores the gate
```

No API key needed for any of the above. On Windows, `.\setup.ps1` runs the
whole thing as one verification pass.

---

## Why this is not AgentDesk

[AgentDesk](../agentdesk) is a linear pipeline — research, then draft, then
review — for tasks where **ground truth exists**. A claim in an outreach email
either traces to a source URL or it doesn't, and the whole system is built
around mechanically checking that trace.

Crux is for the other kind of question: "should we build our own billing
system or buy one", "is this franchise worth signing", "do we take the
acquisition offer". **There is no ground truth.** Nothing to verify — only
competing reasoning, and usually one fact nobody has looked up yet that both
arguments quietly depend on.

Same engineering spine, different shape:

| | **AgentDesk** | **Crux** |
|---|---|---|
| topology | linear pipeline + feedback loop | parallel fan-out, then converge |
| is there a ground truth? | yes — claim → source URL | no — only competing arguments |
| what the system produces | an outreach email, or nothing | the crux, and whether a verdict is warranted |
| what the last agent does | **gates** — pass or block | **decision aid** — names what to go find out |
| model disagreement is… | a problem to resolve (reviewer vs arithmetic) | the entire input, by design (optimist vs pessimist) |
| iteration | retry budget of 2, then escalate to a human | **single pass** — no retries |
| terminal states | released / halted / escalated / rejected | report / rejected |
| the hard check | swap company nouns for `[COMPANY]`, is it still sendable? | is one position >25% longer than the other? |

The contrast is the point of building it. Both use typed JSON contracts,
schema validation, deterministic checks that run *before* any expensive model
call, and a known-limitations section that names what they don't catch.

---

## The three design decisions that matter

### 1. Parallel isolation

The optimist and pessimist never see each other's output. Neither call's
prompt contains a word the other wrote.

If the pessimist reads the optimist first, it stops analyzing and starts
rebutting — and a rebuttal is a weaker thing than an independently constructed
case. The mediator needs two real arguments to find the disagreement between
them, not an argument and its counter. This is the same context-isolation
principle that makes AgentDesk a real agent team rather than three personas in
one prompt.

In code: `run_pipeline()` builds one `pack_prompt` and hands the *identical*
prompt to two separate model calls (run concurrently, but concurrency is a
bonus — the isolation is the property). A position that says "critics might
argue…" is hallucinating an opponent it was never shown, and the
phantom-opponent check rejects the whole run.

### 2. Symmetry enforcement

Mediators favor whichever argument is longer or more confident, not whichever
is better. So both positions get the **identical word budget** (220 ± 60,
passed to each debater and recomputed in code, never trusted), and a
**symmetry check** flags any run where one position is more than 1.25× the
length of the other — even when both are individually within budget.

`evals/golden_set.jsonl` case `b06` is exactly that: both positions inside the
160–280 word budget, but the pessimist is 1.38× the optimist, and the
symmetry ratio is the only check that fires. The word budget alone would let
it through.

### 3. Order randomization

Mediators show position bias toward whichever argument they read first. So the
orchestrator randomizes which position is presented first and **records the
seed** in the run log. `python run.py --dry-run --seed 7` fixes it; every
`runs.jsonl` line carries `order_seed` and `presented_first` so a result is
reproducible and any order bias is auditable after the fact.

---

## What the mediator is not allowed to do

The failure mode this whole system exists to prevent: a mediator that reads
two arguments and outputs *"on balance, moderately positive."* That has told
the decision-maker nothing they couldn't have guessed.

- **It may not average.** `verdict_rationale` is never a bare "it depends" —
  it is always "it depends on X, and if X is A do this, if X is B do that."
- **It may not introduce new claims.** It works only from the two positions
  and the pack. No search tools — same reason AgentDesk's drafter has none.
- **It must fill `primary_crux` before any verdict.** Naming the crux is the
  deliverable. A verdict written while the crux is vague is the averaging
  behavior wearing a disguise, and `crux_report_checks()` in code rejects it.
- **It may withhold a verdict, and often should.** `verdict_withheld: true` is
  a valid, frequently correct output: the crux is unresolved, resolving it is
  cheap, and the deadline allows — so "go find out X first" beats a guess.

The deterministic `crux:usable` gate recomputes whether the report is
acceptable — a concrete `the_disagreement`, a findable `resolving_evidence`, a
real `how_to_obtain_it`, no vague filler. The mediator's own framing is
advisory, the same way AgentDesk's `release_decision()` ignores the reviewer's
own `pass` field.

---

## The demo question

*"Should we build our own customer-support ticketing system or buy an
off-the-shelf one?"*

Run `--dry-run` and watch the mediator work. The optimist argues build (the
pain is integration-shaped, the engineers are free this quarter, the vendor
nickel-and-dimes every connector). The pessimist argues buy (the last internal
build shipped 5 months late, volume grows every quarter, a bought tool is live
today). Both are honest. Both are well-argued.

The mediator's finding: **the entire disagreement reduces to one number nobody
has — how many internal-system integrations the tool actually needs, and how
many are two-way rather than read-only.** The optimist's case needs that
number to be large. The pessimist's needs it to be small. Neither has it; both
are assuming it, in opposite directions. It costs half a day to find out, well
inside the Q3 deadline. So the mediator *withholds the verdict* and says:
build the integration map first, and here is exactly what each possible result
implies.

The `resolved_crux` scenario is the same question with that number already in
the evidence pack — and there the mediator issues a verdict, because the crux
is settled.

---

## Measured results

`python evals/run_eval.py` — 15 cases, each a named mutation of one
known-good optimist/pessimist pair, so every case isolates one failure mode.

```
recall             8/12   67%   (known-bad debates blocked)
false block rate   0/3    0%    (known-good debates blocked)
blocked by code    8
blocked by model   0
```

**Eight of twelve bad debates blocked before spending a single mediator call,
at zero false positives.** The four that escape the deterministic layer are
the honest part:

- **m01 — phantom opponent, in substance.** The pessimist rebuts the
  optimist's actual argument without using any flagged phrase. Code checks for
  phrases; it cannot see that one position is *answering* the other.
- **m02 — a generic position.** Valid refs, right length, no phantom opponent,
  reads well. Swap "ticketing system" for any other build-vs-buy call and it
  still sends. Code cannot catch contentlessness.
- **m03 — a mislabeled inference.** An extrapolation marked `direct` with
  `high` confidence. Code cannot tell a direct read from a stretch — that is
  the mediator's job, and mislabeling is the debate version of a fabricated
  citation.
- **m04 — evidence drift.** A claim cites `e2` but restates it as something
  `e2` doesn't say ("free all year" vs "free for a Q3 project"). A real
  citation pointing at a distorted version of the fact.

`run_eval.py --live` would add real mediator calls and measure whether the
model catches those four. **It has not been run — this project makes no API
calls.** The number above is the honest one: 8/12 by code, 0/3 false blocks,
and four cases that need a model call this project hasn't made.

---

## Known limitations

A system diagram without this section is marketing.

- **The phantom-opponent check is a phrase denylist, and denylists leak.**
  Eval case `m01` proves it: a position can rebut a view it never saw using
  none of the ~17 patterns in the list. Every new evasion is a patch after the
  fact. A learned classifier would generalize; it would also need training
  data this project doesn't have.
- **`inference_type` is self-reported.** A debater labels its own steps
  `direct` or `extrapolation`, and only the mediator — on judgment, not
  arithmetic — can catch a stretch dressed as a direct read (`m03`). Nothing
  in the deterministic layer validates the label.
- **`confidence` on evidence and on reasoning steps is self-reported too.**
  Same problem AgentDesk documents: a miscalibrated input poisons everything
  downstream and the pipeline has no way to notice.
- **The word budget assumes length ≈ persuasive weight.** It's a decent proxy
  and the symmetry check leans on it, but a debater could pack a 220-word
  position with more rhetorical force than an equal-length opponent. The check
  measures characters, not conviction.
- **Single pass means a weak position produces a weak report.** There is no
  retry to send a thin optimist back for a stronger case. If a debater
  underperforms, the mediator characterizes what it actually said — which is
  correct behavior, but it means report quality depends on debater quality
  with no recovery loop. This is a deliberate contrast with AgentDesk's retry
  budget, not an oversight.
- **The mediator's `crux:usable` gate checks shape, not correctness.** It
  verifies `resolving_evidence` is specific and non-vague. It cannot verify
  the named crux is *actually* the load-bearing one — a mediator could name a
  real-but-secondary disagreement as primary and the code would pass it.
- **The eval set is synthetic.** Fifteen mutations of one baseline debate. It
  measures whether checks fire on known failure shapes. It does not measure
  whether the crux the mediator names is the one a domain expert would name,
  and nothing in this repo does.
- **No live run has ever happened.** Every terminal state, every scenario, and
  the entire eval are demonstrated on fixtures — real code paths, pre-written
  JSON inputs. Whether a real optimist and pessimist, run live, produce
  positions clean enough to reach the mediator is untested here by choice.

---

## Repo

```
contracts/       evidence_pack, position, crux_report — the three JSON schemas
agents/          optimist, pessimist, mediator — one SKILL.md contract each
orchestrator/
  run.py         parallel isolated calls, order randomization, the gates
  jsonio.py      robust JSON extraction, copied from AgentDesk (not imported)
  fixtures/      five scenarios + the generator that word-counts them
  test_jsonio.py parser tests
evals/           mutation-based golden set, the scorer, and results
CLAUDE.md        invariants for future sessions
setup.ps1        one-shot Windows verification pass
```

The contracts are the interface. Change a schema and both `run.py` and the
eval harness change with it — an interface nobody can quietly ignore.

---

## The argument

Anyone can prompt "argue both sides of this and tell me what you think." Run
it four hundred times and it converges on "there are compelling points on both
sides; the answer depends on your priorities" — which is true, useless, and
took no judgment to produce.

The part that takes judgment is deciding that the two sides should never see
each other, enforcing that their arguments are the same length so the
synthesis isn't biased by volume, randomizing the reading order so it isn't
biased by position, and holding the synthesizer to a standard higher than
"average them" — it has to find the *one thing* that would actually settle the
question, or admit it can't. That's what's in `run.py`, and you can watch it
work in about ten minutes with no API key.
