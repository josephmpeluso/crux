#!/usr/bin/env python3
"""
Crux orchestrator.

Runs the optimist / pessimist / mediator topology with the properties that
make it trustworthy enforced in code rather than requested in prompts.

Crux is the deliberate contrast to AgentDesk. AgentDesk is a linear pipeline
with a feedback loop, for tasks where ground truth exists — a claim traces to
a source URL or it doesn't. Crux is a parallel fan-out / converge topology,
for open judgment calls where there is NO ground truth, only competing
reasoning: "should we build or buy", "should I sign this franchise". Nothing
to verify — only two arguments to weigh, and one fact hiding underneath them
that would settle the matter if anyone looked it up.

    evidence_pack
         |
     +---+---+        PARALLEL. Neither debater sees the other.
     v       v
  OPTIMIST  PESSIMIST
     |       |
     +---+---+
         v
   deterministic checks   <-- dangling refs, missing falsifiability,
         v                    word-budget, symmetry ratio, phantom opponent
      MEDIATOR                 (all BEFORE the mediator call)
         v
    crux_report          <-- names the primary crux, then decides whether a
                             verdict is even warranted

Three things are enforced here, not asked for:

1. PARALLEL ISOLATION. The optimist and pessimist calls never share context.
   Neither prompt contains the other's output. If the pessimist could read the
   optimist first, it would stop analyzing and start rebutting.
2. SYMMETRY. Both positions get the identical word budget, checked in code,
   plus a symmetry ratio that flags any run where one side is >25% longer.
   A longer argument reads as a stronger one to the mediator whether or not
   it is.
3. ORDER RANDOMIZATION. Which position the mediator reads first is randomized
   and the seed is logged, so order bias is both reduced and auditable.

Usage:
    python run.py --pack path/to/evidence_pack.json     # live, needs API key
    python run.py --dry-run                             # fixtures, no key
    python run.py --dry-run --scenario asymmetric
    python run.py --dry-run --seed 7                    # fix the reading order
"""

from __future__ import annotations

import argparse
import concurrent.futures
import json
import os
import random
import re
import sys
import time
import uuid
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any

from jsonio import extract_json, ParseFailure  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
CONTRACTS = ROOT / "contracts"
AGENTS = ROOT / "agents"
FIXTURES = Path(__file__).resolve().parent / "fixtures"

# --------------------------------------------------------------------------
# Configuration
# --------------------------------------------------------------------------

# Model tiering. The two debaters run on the same model — the job is
# symmetric, so asymmetry in capability would bias the synthesis before the
# mediator reads a word. The mediator runs on a DIFFERENT model family, for
# the same reason AgentDesk's QA reviewer does: a model synthesizing two
# arguments produced by its own family shares that family's blind spots, and
# correlated blind spots are how a bad synthesis looks fine.
MODELS = {
    "optimist": os.environ.get("CRUX_DEBATER_MODEL", "claude-sonnet-5"),
    "pessimist": os.environ.get("CRUX_DEBATER_MODEL", "claude-sonnet-5"),
    "mediator": os.environ.get("CRUX_MEDIATOR_MODEL", "claude-opus-5"),
}

# Output budgets, per agent. Undersizing these is not a soft failure — the
# reply gets cut mid-JSON and surfaces as "Unterminated string", which reads
# like a model problem and is a budget problem. The mediator gets the most
# room because its report reproduces both positions' disagreements in full.
MAX_TOKENS = {
    "optimist": 8000,
    "pessimist": 8000,
    "mediator": 16000,
}

# The word budget both debaters share. Counted on thesis + every reasoning
# claim (falsifiability list and structured fields excluded). Equal budgets
# are the point — see SYMMETRY above.
WORD_BUDGET = 220
WORD_TOLERANCE = 60          # a position may land 160-280 words

# If one position's word count divided by the other's exceeds this, the run
# is flagged for asymmetry even when both are individually within budget.
# 1.25 = "more than 25% longer", straight from the design brief.
SYMMETRY_MAX_RATIO = 1.25

# Phrases that mean a single-stance debater is acknowledging, summarizing, or
# pre-empting an opposing view it was never shown. A position that does this
# is hallucinating an opponent, and the whole run is rejected. This is a
# denylist and denylists leak — see README "Known limitations". A model can
# rebut a phantom opponent without using any of these exact phrases, and the
# eval set has a case (m02) that proves it.
PHANTOM_OPPONENT_PATTERNS = [
    r"critics?\s+(might|would|could|may)?\s*(argue|say|claim|contend|point out|note)",
    r"\b(the\s+)?(bear|bull)\s+case\b",
    r"\bopponents?\b",
    r"\bproponents?\b",
    r"\bdetractors?\b",
    r"\bskeptics?\b",
    r"\bnaysayers?\b",
    r"(advocates?|supporters?)\s+(would|might|may|could)\s+(argue|say|claim|contend)",
    r"some\s+(would|might|may|could)\s+(argue|say|counter|contend|object)",
    r"one\s+(might|could|may)\s+(argue|counter|object|say)",
    r"the\s+(opposing|opposite|other|counter)\s+(view|side|position|case|argument)",
    r"\bcounter-?argument\b",
    r"\bcounterpoint\b",
    r"those\s+who\s+(support|oppose|favor|disagree)",
    r"while\s+(some|others|critics|supporters|proponents|advocates)",
    r"on\s+the\s+other\s+hand",
    r"devil'?s\s+advocate",
    r"to\s+be\s+fair\s+to\s+the\s+other\s+side",
]

# Phrases in a crux_report that mean the mediator averaged instead of naming
# a crux. Same denylist caveat as above; eval case m01 is a mediator that
# averages without tripping any of these.
VAGUE_CRUX_PHRASES = [
    "more information", "more data", "further research", "additional analysis",
    "additional information", "gather more", "better understanding of the situation",
    "more clarity overall", "further investigation is needed",
]
VAGUE_VERDICT_PHRASES = [
    "on balance, moderately", "moderately positive", "moderately negative",
    "somewhat favorable", "somewhat unfavorable", "lean slightly",
    "time will tell", "could go either way", "too close to call",
    "weigh the pros and cons", "pros and cons",
]

EVIDENCE_ID_RE = re.compile(r"^e[0-9]+$")


# --------------------------------------------------------------------------
# Run record
# --------------------------------------------------------------------------

@dataclass
class GateResult:
    gate: str
    passed: bool
    detail: str = ""


@dataclass
class RunRecord:
    run_id: str
    question: str
    started_at: float
    order_seed: int
    presented_first: str = ""
    gates: list[GateResult] = field(default_factory=list)
    outcome: str = "incomplete"     # report | rejected | interrupted
    verdict_withheld: bool | None = None
    primary_crux: str | None = None
    tokens_in: int = 0
    tokens_out: int = 0
    # Full agent output, persisted to runs.jsonl for every terminal state, so
    # the log is a self-contained audit record rather than a gate summary.
    pack: dict | None = None
    optimist: dict | None = None
    pessimist: dict | None = None
    report: dict | None = None

    def gate(self, name: str, passed: bool, detail: str = "") -> bool:
        self.gates.append(GateResult(name, passed, detail))
        status = "PASS" if passed else "FAIL"
        print(f"  [{status}] {name}" + (f" — {detail}" if detail else ""))
        return passed

    def to_json(self) -> str:
        d = asdict(self)
        d["duration_s"] = round(time.time() - self.started_at, 2)
        return json.dumps(d)


class ContractError(Exception):
    """Raised when an agent's output is unparseable. Deliberately not retried."""


# --------------------------------------------------------------------------
# Model transport
# --------------------------------------------------------------------------

def load_skill(name: str) -> str:
    """Read an agent SKILL.md and strip its YAML frontmatter for use as a system prompt."""
    text = (AGENTS / name / "SKILL.md").read_text(encoding="utf-8")
    if text.startswith("---"):
        parts = text.split("---", 2)
        if len(parts) >= 3:
            return parts[2].strip()
    return text.strip()


SCHEMA_FILES = {
    "optimist": "position.schema.json",
    "pessimist": "position.schema.json",
    "mediator": "crux_report.schema.json",
}


def call_agent(agent: str, user_content: str, record: RunRecord, attempt: int = 1) -> dict[str, Any]:
    """Single model call. Returns the parsed JSON artifact.

    Raises ContractError on unparseable output — deliberately not retried,
    because malformed structure is a prompt bug, not a flake.
    """
    try:
        import anthropic
    except ImportError:
        raise SystemExit("pip install anthropic  (or use --dry-run)")

    client = anthropic.Anthropic()

    # The SKILL.md only names the schema by path; a model can't read that
    # file. Embedding the literal schema is what makes "conform to
    # position.schema.json" actually true.
    schema_text = (CONTRACTS / SCHEMA_FILES[agent]).read_text(encoding="utf-8")
    system_prompt = (
        load_skill(agent)
        + "\n\n## Output schema — match this exactly (additionalProperties is false)\n\n"
        + f"```json\n{schema_text}\n```"
    )
    if agent in ("optimist", "pessimist"):
        system_prompt += (
            f"\n\n## Your word budget\n\nThesis + all reasoning claims combined must be "
            f"{WORD_BUDGET} words, plus or minus {WORD_TOLERANCE}. The other debater has "
            f"the identical budget. Count before you emit. A run where one position is "
            f"more than 25% longer than the other is flagged for asymmetry regardless of "
            f"whether either is individually in range."
        )

    kwargs: dict[str, Any] = dict(
        model=MODELS[agent],
        max_tokens=MAX_TOKENS[agent],
        system=system_prompt,
        messages=[{"role": "user", "content": user_content}],
    )
    # No agent gets a search tool. The debaters must argue from the pack, and
    # the mediator must synthesize from the two positions — introducing
    # outside facts is a contract violation for all three.

    t0 = time.time()
    resp = client.messages.create(**kwargs)
    latency = int((time.time() - t0) * 1000)

    record.tokens_in += resp.usage.input_tokens
    record.tokens_out += resp.usage.output_tokens

    try:
        obj = extract_json(resp)
    except ParseFailure as e:
        raise ContractError(f"{agent}: {e.summary()}") from e

    obj.setdefault("run_meta", {})
    obj["run_meta"]["latency_ms"] = latency
    obj["run_meta"]["model"] = MODELS[agent]
    obj["run_meta"]["agent"] = agent
    obj["run_meta"]["attempt"] = attempt
    return obj


# --------------------------------------------------------------------------
# Gate: schema validation
# --------------------------------------------------------------------------

def validate_schema(obj: dict, schema_name: str) -> tuple[bool, str]:
    schema = json.loads((CONTRACTS / schema_name).read_text(encoding="utf-8"))
    try:
        import jsonschema
    except ImportError:
        missing = [k for k in schema.get("required", []) if k not in obj]
        if missing:
            return False, f"missing required keys {missing} (jsonschema not installed)"
        return True, "shallow check only — pip install jsonschema for full validation"

    validator = jsonschema.Draft202012Validator(schema)
    errors = sorted(validator.iter_errors(obj), key=lambda e: list(e.path))
    if errors:
        first = errors[0]
        path = "/".join(str(p) for p in first.path) or "<root>"
        return False, f"{len(errors)} error(s); first at {path}: {first.message[:160]}"
    return True, f"conforms to {schema_name}"


# --------------------------------------------------------------------------
# Deterministic checks — run on the two positions, BEFORE the mediator call
# --------------------------------------------------------------------------

def position_word_count(pos: dict) -> int:
    """Words in thesis + every reasoning claim.

    Counted here rather than trusting pos['word_count'] — the model estimates
    its own length optimistically, exactly like AgentDesk's drafter.
    """
    parts = [pos.get("thesis", "")]
    parts += [s.get("claim", "") for s in pos.get("reasoning", [])]
    return len(" ".join(parts).split())


def _phantom_opponent_hits(pos: dict) -> list[str]:
    """Return the phrases in a position that reference an opponent it never saw."""
    haystack = " ".join(
        [pos.get("thesis", "")]
        + [s.get("claim", "") for s in pos.get("reasoning", [])]
        + list(pos.get("what_would_change_my_mind", []))
    ).lower()
    hits = []
    for pat in PHANTOM_OPPONENT_PATTERNS:
        m = re.search(pat, haystack)
        if m:
            hits.append(m.group(0).strip())
    return hits


def deterministic_checks(pack: dict, optimist: dict, pessimist: dict) -> tuple[bool, list[str]]:
    """Cheap, certain checks that run before spending a mediator call.

    Everything here could in principle be judged by the mediator. None of it
    should be — code is free, instant, and has no opinion. And a position that
    fails one of these has broken its contract, so there is no reason to pay
    for a synthesis of it.
    """
    problems: list[str] = []
    valid_ids = {e["evidence_id"] for e in pack.get("evidence", [])}

    wc = {}
    for label, pos in (("optimist", optimist), ("pessimist", pessimist)):
        # -- stance matches the slot
        if pos.get("stance") != label:
            problems.append(f"{label}: stance is '{pos.get('stance')}', expected '{label}'")

        # -- dangling evidence refs: a claim citing evidence not in the pack
        used: set[str] = set()
        for i, step in enumerate(pos.get("reasoning", [])):
            refs = step.get("evidence_refs", [])
            used |= set(refs)
            # -- a 'direct' read must point at something; only pure logical
            #    steps (extrapolation) may cite nothing
            if step.get("inference_type") == "direct" and not refs:
                problems.append(
                    f"{label}: reasoning[{i}] is 'direct' but cites no evidence — "
                    f"a direct read has to name what it read"
                )
        dangling = used - valid_ids
        if dangling:
            problems.append(f"{label}: dangling evidence_refs {sorted(dangling)} not in the pack")

        # -- falsifiability (also schema-enforced; checked here so a degraded
        #    run without jsonschema still catches it)
        if not pos.get("what_would_change_my_mind"):
            problems.append(f"{label}: what_would_change_my_mind is empty — falsifiability is mandatory")

        # -- word budget
        n = position_word_count(pos)
        wc[label] = n
        if abs(n - WORD_BUDGET) > WORD_TOLERANCE:
            problems.append(
                f"{label}: {n} words, budget is {WORD_BUDGET}+/-{WORD_TOLERANCE} "
                f"({WORD_BUDGET - WORD_TOLERANCE}-{WORD_BUDGET + WORD_TOLERANCE})"
            )

        # -- phantom opponent
        hits = _phantom_opponent_hits(pos)
        if hits:
            problems.append(f"{label}: references an opponent it was never shown — {hits}")

    # -- symmetry ratio, across the two positions
    hi, lo = max(wc.values()), max(min(wc.values()), 1)
    ratio = hi / lo
    if ratio > SYMMETRY_MAX_RATIO:
        longer = max(wc, key=wc.get)
        problems.append(
            f"symmetry: {longer} position is {ratio:.2f}x the other "
            f"({wc['optimist']} vs {wc['pessimist']} words) — max allowed is {SYMMETRY_MAX_RATIO}x"
        )

    return len(problems) == 0, problems


# --------------------------------------------------------------------------
# Gate: crux_report quality — recomputed in code, the mediator's own framing
# is advisory
# --------------------------------------------------------------------------

def _wc(s: str) -> int:
    return len((s or "").split())


def crux_report_checks(report: dict) -> tuple[bool, list[str]]:
    """A schema-valid report can still be a failure: a vague crux, or a
    verdict that averages. The orchestrator, not the model, decides whether
    the report is usable — same principle as AgentDesk's release_decision().
    """
    problems: list[str] = []

    pc = report.get("primary_crux", {})
    if _wc(pc.get("the_disagreement", "")) < 4:
        problems.append("primary_crux.the_disagreement is too thin to be a real crux")
    if _wc(pc.get("resolving_evidence", "")) < 4:
        problems.append("primary_crux.resolving_evidence names no specific findable fact")
    if _wc(pc.get("how_to_obtain_it", "")) < 4:
        problems.append("primary_crux.how_to_obtain_it names no concrete action")

    blob = " ".join([
        pc.get("the_disagreement", ""), pc.get("resolving_evidence", ""),
        pc.get("how_to_obtain_it", ""), pc.get("why_this_one", ""),
    ]).lower()
    for phrase in VAGUE_CRUX_PHRASES:
        if phrase in blob:
            problems.append(f"primary_crux leans on vague filler: '{phrase}'")

    rationale = report.get("verdict_rationale", "")
    low = rationale.lower()
    for phrase in VAGUE_VERDICT_PHRASES:
        if phrase in low:
            problems.append(f"verdict_rationale is an average, not a crux: '{phrase}'")

    # -- "no bare it depends": when a verdict is offered on a real
    #    disagreement, the rationale must lay out the branches
    if (report.get("verdict_withheld") is False
            and report.get("divergences")
            and "if " not in low):
        problems.append(
            "verdict offered but verdict_rationale has no 'if X then / if Y then' branch"
        )

    # -- the mediator has to have done something
    if not report.get("agreements") and not report.get("divergences"):
        problems.append("report names no agreements and no divergences — the mediator said nothing")

    return len(problems) == 0, problems


# --------------------------------------------------------------------------
# Order randomization
# --------------------------------------------------------------------------

def reading_order(seed: int) -> tuple[str, str]:
    """Return (first_stance, second_stance) for how the mediator sees them.

    Randomized because mediators show position bias toward whichever argument
    they read first. The seed is recorded in the run log so the order is
    reproducible and any bias is auditable after the fact.
    """
    rng = random.Random(seed)
    order = ["optimist", "pessimist"]
    rng.shuffle(order)
    return order[0], order[1]


def build_mediator_prompt(pack: dict, optimist: dict, pessimist: dict, first: str) -> str:
    by_stance = {"optimist": optimist, "pessimist": pessimist}
    second = "pessimist" if first == "optimist" else "optimist"

    def block(stance: str) -> str:
        return f"POSITION — {stance.upper()}\n{json.dumps(by_stance[stance], indent=2)}"

    return (
        f"EVIDENCE PACK:\n{json.dumps(pack, indent=2)}\n\n"
        f"The two positions were built in isolation. Neither debater saw the other.\n"
        f"They are presented below in a randomized order.\n\n"
        f"{block(first)}\n\n{block(second)}\n\n"
        f"Produce the crux_report. Fill primary_crux before deciding on a verdict."
    )


# --------------------------------------------------------------------------
# Pipeline
# --------------------------------------------------------------------------

def run_pipeline(pack: dict, fixtures: dict | None, record: RunRecord) -> RunRecord:
    dry = fixtures is not None

    # ---- Gate: the pack itself has to be valid ---------------------------
    ok, detail = validate_schema(pack, "evidence_pack.schema.json")
    if not record.gate("schema:evidence_pack", ok, detail):
        record.outcome = "rejected"
        return record
    record.pack = pack

    # ---- Stage 1: the two debaters, in ISOLATION -------------------------
    # The essential property is that neither call's prompt contains the
    # other's output. Running them concurrently is a bonus, not the point —
    # a sequential version with the same isolation would be just as valid.
    print(f"\n[1/2] optimist + pessimist  ({'fixture' if dry else MODELS['optimist']}) — parallel, isolated")

    if dry:
        optimist = json.loads(json.dumps(fixtures["optimist"]))
        pessimist = json.loads(json.dumps(fixtures["pessimist"]))
    else:
        pack_prompt = (
            f"EVIDENCE PACK:\n{json.dumps(pack, indent=2)}\n\n"
            f"Build your position. You are one debater; you will not see the other."
        )
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as ex:
            f_opt = ex.submit(call_agent, "optimist", pack_prompt, record)
            f_pes = ex.submit(call_agent, "pessimist", pack_prompt, record)
            optimist = f_opt.result()
            pessimist = f_pes.result()

    record.optimist = optimist
    record.pessimist = pessimist

    for label, pos in (("optimist", optimist), ("pessimist", pessimist)):
        ok, detail = validate_schema(pos, "position.schema.json")
        if not record.gate(f"schema:position:{label}", ok, detail):
            record.outcome = "rejected"
            return record

    # ---- Gate: deterministic checks, BEFORE the mediator call -----------
    print("\n[gate] deterministic checks on both positions")
    ok, problems = deterministic_checks(pack, optimist, pessimist)
    record.gate("deterministic", ok, "; ".join(problems) if problems else
                "refs, falsifiability, word budget, symmetry, phantom-opponent all clean")
    if not ok:
        # Single pass — there is no retry budget. A position that fails its
        # contract is a prompt bug, and the mediator is never called on it.
        record.outcome = "rejected"
        print("\n  Rejected before the mediator. Crux is single-pass by design —")
        print("  a broken position does not get a revision round. Fix the pack")
        print("  or the debater prompt and re-run.")
        return record

    # ---- Stage 2: the mediator -----------------------------------------
    first, second = reading_order(record.order_seed)
    record.presented_first = first
    print(f"\n[2/2] mediator  ({'fixture' if dry else MODELS['mediator']}) — reads {first} first (seed {record.order_seed})")

    if dry:
        report = json.loads(json.dumps(fixtures["crux_report"]))
        report.setdefault("run_meta", {})
        report["run_meta"].update({"agent": "mediator", "model": "fixture", "attempt": 1})
    else:
        report = call_agent("mediator", build_mediator_prompt(pack, optimist, pessimist, first), record)
    report["run_meta"]["order_seed"] = record.order_seed
    report["run_meta"]["presented_first"] = first
    record.report = report

    ok, detail = validate_schema(report, "crux_report.schema.json")
    if not record.gate("schema:crux_report", ok, detail):
        record.outcome = "rejected"
        return record

    ok, problems = crux_report_checks(report)
    record.gate("crux:usable", ok, "; ".join(problems) if problems else
                "primary crux is concrete; verdict is a branch, not an average")
    if not ok:
        record.outcome = "rejected"
        return record

    record.outcome = "report"
    record.verdict_withheld = report.get("verdict_withheld")
    record.primary_crux = report.get("primary_crux", {}).get("the_disagreement")
    return record


# --------------------------------------------------------------------------
# Reporting
# --------------------------------------------------------------------------

def _print_position(pos: dict) -> None:
    print(f"\n{pos.get('stance', '?').upper()} — {position_word_count(pos)} words "
          f"(budget {WORD_BUDGET}+/-{WORD_TOLERANCE})")
    print(f"  thesis: {pos.get('thesis', '')}")
    for i, s in enumerate(pos.get("reasoning", [])):
        refs = ",".join(s.get("evidence_refs", [])) or "—"
        print(f"  {i + 1}. [{s.get('inference_type', '?')}/{s.get('confidence', '?')}] "
              f"({refs}) {s.get('claim', '')}")
    print("  what would change my mind:")
    for w in pos.get("what_would_change_my_mind", []):
        print(f"    · {w}")


def print_audit(record: RunRecord) -> None:
    if not any([record.pack, record.optimist, record.pessimist, record.report]):
        return

    print("\n" + "=" * 70)
    print(f"AUDIT — {record.outcome.upper()}")
    print("=" * 70)

    if record.pack:
        print(f"\nQUESTION: {record.pack.get('question', '?')}")
        dl = record.pack.get("decision_deadline")
        if dl:
            print(f"DEADLINE: {dl}")
        print(f"EVIDENCE ({len(record.pack.get('evidence', []))} items):")
        for e in record.pack.get("evidence", []):
            print(f"  [{e['evidence_id']}] ({e['confidence']}) {e['statement']}")
            print(f"         source: {e['source']}")

    if record.optimist:
        _print_position(record.optimist)
    if record.pessimist:
        _print_position(record.pessimist)

    r = record.report
    if r:
        print("\n" + "-" * 70)
        print(f"CRUX REPORT   (mediator read {r.get('run_meta', {}).get('presented_first', '?')} "
              f"first, seed {r.get('run_meta', {}).get('order_seed', '?')})")
        print("-" * 70)
        if r.get("agreements"):
            print("agreements:")
            for a in r["agreements"]:
                print(f"  = {a}")
        print(f"divergences: {len(r.get('divergences', []))}")
        for d in r.get("divergences", []):
            print(f"  [><] {d.get('the_disagreement', '')}")
            print(f"      optimist:  {d.get('optimist_position', '')}")
            print(f"      pessimist: {d.get('pessimist_position', '')}")
            print(f"      resolve by: {d.get('resolving_evidence', '')}")
            print(f"      how: {d.get('how_to_obtain_it', '')}  [{d.get('cost_to_obtain', '?')}]")

        pc = r.get("primary_crux", {})
        print("\nPRIMARY CRUX:")
        print(f"  {pc.get('the_disagreement', '')}")
        print(f"  why this one: {pc.get('why_this_one', '')}")
        print(f"  resolving evidence: {pc.get('resolving_evidence', '')}")
        print(f"  how to obtain: {pc.get('how_to_obtain_it', '')}  [{pc.get('cost_to_obtain', '?')}]")
        print(f"  resolvable before deadline: {pc.get('resolvable_before_deadline')}")

        print(f"\nVERDICT WITHHELD: {r.get('verdict_withheld')}")
        print(f"  {r.get('verdict_rationale', '')}")

    print("\n" + "=" * 70)
    print(f"TERMINAL STATE: {record.outcome.upper()}")
    print("=" * 70)


def main() -> int:
    ap = argparse.ArgumentParser(description="Crux — parallel optimist/pessimist/mediator")
    ap.add_argument("--pack", help="path to an evidence_pack JSON file (live mode)")
    ap.add_argument("--dry-run", action="store_true", help="run on fixtures, no API key needed")
    ap.add_argument("--scenario", default="clean_disagreement", help="fixture scenario for --dry-run")
    ap.add_argument("--seed", type=int, help="fix the mediator's reading-order seed (default: random)")
    ap.add_argument("--log", default="runs.jsonl")
    args = ap.parse_args()

    # Windows consoles default to cp1252 and the audit output contains
    # en-dashes and bullets. Force UTF-8 so a print never crashes the run.
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass

    fixtures = None
    if args.dry_run:
        all_fixtures = json.loads((FIXTURES / "dry_run.json").read_text(encoding="utf-8"))
        if args.scenario not in all_fixtures:
            print(f"Unknown scenario '{args.scenario}'. Available: {', '.join(all_fixtures)}")
            return 2
        fixtures = all_fixtures[args.scenario]
        pack = fixtures["evidence_pack"]
    elif args.pack:
        pack = json.loads(Path(args.pack).read_text(encoding="utf-8"))
    else:
        ap.error("--pack is required unless --dry-run is set")

    seed = args.seed if args.seed is not None else random.randrange(1_000_000)
    record = RunRecord(
        run_id=uuid.uuid4().hex[:8],
        question=pack.get("question", "?"),
        started_at=time.time(),
        order_seed=seed,
    )

    print("=" * 70)
    print(f"Crux run {record.run_id}")
    print(f"  {record.question}")
    if args.dry_run:
        print(f"  DRY RUN — scenario: {args.scenario}")
    print("=" * 70)

    try:
        try:
            record = run_pipeline(pack, fixtures, record)
        except ContractError as e:
            record.gate("contract", False, str(e))
            record.outcome = "rejected"
        except BaseException as e:
            record.gate("infrastructure", False, f"{type(e).__name__}: {e}")
            record.outcome = "interrupted"
            raise
    finally:
        print_audit(record)
        print("\n" + "-" * 70)
        print(f"OUTCOME: {record.outcome.upper()}   "
              f"verdict_withheld: {record.verdict_withheld}   seed: {record.order_seed}")
        if record.tokens_in or record.tokens_out:
            print(f"tokens: {record.tokens_in} in / {record.tokens_out} out")
        print("-" * 70)
        with open(args.log, "a", encoding="utf-8") as fh:
            fh.write(record.to_json() + "\n")
        print(f"logged to {args.log}")

    return 0 if record.outcome == "report" else 1


if __name__ == "__main__":
    sys.exit(main())
