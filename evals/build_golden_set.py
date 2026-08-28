#!/usr/bin/env python3
"""Generates the golden eval set for Crux.

Each case is a named mutation applied to one known-good baseline — the
`clean_disagreement` optimist/pessimist pair — so every case isolates exactly
one failure mode. Hand-writing a dozen bad debates produces a dozen subtly
different debates and no clean attribution when the gate misses one.

Each case declares `caught_by`:
  code   — a deterministic check should catch it, no mediator call needed
  model  — only the mediator (or a human) can catch it; judgment required
  none   — intentionally clean; blocking it is a false positive

That split is the point. A gate that only catches what code can catch is a
linter. A gate that needs a model for everything is expensive and slow. Crux's
deterministic layer is designed to catch contract violations — dangling refs,
asymmetry, phantom-opponent phrasing — and to be honest that it cannot catch a
position which is generic, or which quietly misreads its evidence, or which
rebuts an opponent without ever naming one. Those need the mediator, and
measuring whether the mediator catches them needs API calls this project does
not make.
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "orchestrator"))

FIX = json.loads((ROOT / "orchestrator" / "fixtures" / "dry_run.json").read_text())
PACK = FIX["clean_disagreement"]["evidence_pack"]
BASE_OPT = FIX["clean_disagreement"]["optimist"]
BASE_PES = FIX["clean_disagreement"]["pessimist"]


def clone(d):
    return json.loads(json.dumps(d))


def wc(pos):
    parts = [pos["thesis"]] + [s["claim"] for s in pos["reasoning"]]
    return len(" ".join(parts).split())


CASES = []


def case(cid, label, failure_mode, caught_by, mutate_opt=None, mutate_pes=None, note=""):
    o, p = clone(BASE_OPT), clone(BASE_PES)
    if mutate_opt:
        mutate_opt(o)
    if mutate_pes:
        mutate_pes(p)
    CASES.append({
        "id": cid,
        "label": label,                       # "good" or "bad"
        "failure_mode": failure_mode,
        "caught_by": caught_by,
        "note": note,
        "pack": PACK,
        "optimist": o,
        "pessimist": p,
    })


# ---------------------------------------------------------------- clean cases
case("g01", "good", None, "none", None, None,
     "Baseline. Both positions in budget, symmetric, every ref valid. Blocking it is a false positive.")


def _reword_opt(o):
    o["thesis"] = o["thesis"].replace("Build it.", "The team should build this in-house.")
    o["reasoning"][0]["claim"] = "Customers' top complaint is how long a first response takes, and agents burn that time hand-copying data across four internal systems on every single ticket."


case("g02", "good", None, "none", _reword_opt, None,
     "Baseline reworded. Guards against the gate keying on exact strings.")


def _trim_pes_in_budget(p):
    # drop the weakest reasoning step; still well within 160-280 and symmetry holds
    p["reasoning"] = p["reasoning"][:4]


case("g03", "good", None, "none", None, _trim_pes_in_budget,
     "Pessimist drops its lowest-confidence step. Shorter but in budget and symmetric. Must not block.")


# ------------------------------------------------- code-catchable failures
def _dangling(o):
    o["reasoning"][2]["evidence_refs"] = ["e2", "e99"]


case("b01", "bad", "dangling_evidence_ref", "code", _dangling, None,
     "Cites e99, which is not in the pack. A fabricated citation.")


def _direct_no_evidence(o):
    o["reasoning"].append({
        "claim": "An in-house build will clearly pay for itself within two years.",
        "evidence_refs": [],
        "inference_type": "direct",
        "confidence": "high",
    })


case("b02", "bad", "direct_without_evidence", "code", _direct_no_evidence, None,
     "A 'direct' reasoning step that cites nothing. A direct read has to name what it read.")


def _no_falsifiability(o):
    o["what_would_change_my_mind"] = []


case("b03", "bad", "missing_falsifiability", "code", _no_falsifiability, None,
     "Drops what_would_change_my_mind entirely. Also a schema violation; the deterministic layer catches it too.")


def _overlong(o):
    filler = (" Furthermore, when the organization considers the full lifecycle cost of ownership, "
              "including onboarding, training, documentation, and the eventual migration away from "
              "whatever is chosen, the in-house option compounds its advantages in ways that a "
              "surface-level price comparison between a monthly subscription and a quarter of "
              "salary systematically and badly understates every single time.")
    o["reasoning"][0]["claim"] += filler * 3


case("b04", "bad", "word_budget_over", "code", _overlong, None,
     "Optimist balloons well past the 280-word ceiling.")


def _underlong(p):
    p["thesis"] = "Buy it."
    p["reasoning"] = [
        {"claim": "The team's one build shipped five months late.", "evidence_refs": ["e6"],
         "inference_type": "direct", "confidence": "high"},
        {"claim": "Volume grows 8% a quarter.", "evidence_refs": ["e1"],
         "inference_type": "direct", "confidence": "high"},
    ]


case("b05", "bad", "word_budget_under", "code", None, _underlong,
     "Pessimist gutted to ~15 words, far under the 160-word floor.")


def _asym_pes(p):
    # baseline optimist is untouched (~199 words). Push the pessimist from
    # ~220 to ~265 — still inside the 160-280 budget on its own, but now
    # ~1.33x the optimist, so ONLY the cross-position symmetry ratio fires.
    extra = (" The deeper pattern is that every number favoring a build is one the team would have "
             "to estimate itself, and the one time it tried, on the reporting dashboard, the "
             "estimate was wrong by five months — a categorical estimation failure, not a "
             "tolerable error bar for a customer-facing system under a quarterly deadline.")
    p["reasoning"][3]["claim"] += extra


case("b06", "bad", "symmetry_violation_only", "code", None, _asym_pes,
     "Both positions individually within the 160-280 budget, but the pessimist is ~1.3x the "
     "optimist so the symmetry ratio (max 1.25x) is the only check that fires. This is the "
     "case the symmetry check exists for — the word budget alone would let it through.")


def _phantom_phrase(p):
    p["reasoning"][0]["claim"] = (
        "Proponents of building will point to the team owning the systems, but the bear case is "
        "simpler: the last internal build shipped five months late and still costs a day a week.")


case("b07", "bad", "phantom_opponent_phrase", "code", None, _phantom_phrase,
     "Pessimist uses 'proponents' and 'the bear case' — acknowledging a view it was never shown.")


def _stance_swap(o):
    o["stance"] = "pessimist"


case("b08", "bad", "stance_mismatch", "code", _stance_swap, None,
     "The optimist slot contains a position labelled 'pessimist'. Schema-valid in isolation; "
     "only the orchestrator, which knows which slot it asked for, can catch it.")


# ------------------------------------------------- model-only failures
def _subtle_phantom(p):
    p["reasoning"][3]["claim"] = (
        "The argument that owning the four systems makes an in-house build lower-risk does not "
        "hold up: the team still has to maintain every connector forever, and the vendor's "
        "per-connector quote is at least a bounded number the in-house estimate never is.")


case("m01", "bad", "phantom_opponent_subtle", "model", None, _subtle_phantom,
     "The pessimist rebuts the optimist's actual argument ('owning the systems makes a build "
     "lower-risk') without using any flagged phrase. A phantom opponent in substance, invisible "
     "to the phrase denylist. The mediator should notice one position is answering the other.")


def _generic_opt(o):
    o["thesis"] = "Building in-house is the right call: it gives the team control, flexibility, and better economics over time, and the people to do it are available."
    o["reasoning"] = [
        {"claim": "Owning the system means the team can shape it to fit how the work actually happens rather than bending its own process to fit a vendor's assumptions about how support should run.",
         "evidence_refs": ["e4"], "inference_type": "extrapolation", "confidence": "medium"},
        {"claim": "The engineering capacity to take this on is available right now, and the start of a planning cycle with people on the bench is exactly when a build is cheapest to begin.",
         "evidence_refs": ["e2"], "inference_type": "direct", "confidence": "high"},
        {"claim": "Over a multi-year horizon a one-time build cost compares favorably against an indefinite monthly subscription that only ever goes up, so the economics point toward building rather than renting.",
         "evidence_refs": ["e2", "e3"], "inference_type": "extrapolation", "confidence": "medium"},
        {"claim": "The team has shipped internal tooling before and can apply the lessons from that experience to deliver this one more predictably than the first time around.",
         "evidence_refs": ["e6"], "inference_type": "extrapolation", "confidence": "low"},
        {"claim": "A tool the team controls can evolve as the business changes and new requirements come up, whereas a bought product locks the process to whatever roadmap the vendor decides to prioritize next quarter.",
         "evidence_refs": ["e4"], "inference_type": "extrapolation", "confidence": "low"},
        {"claim": "Investing in the team's own capability to build and own critical systems pays back beyond this one project, in retained knowledge and in the confidence to take on the next build without outside help.",
         "evidence_refs": ["e2"], "inference_type": "extrapolation", "confidence": "low"},
    ]


case("m02", "bad", "generic_position", "model", _generic_opt, None,
     "The hard one. Valid refs, right length, no phantom opponent, reads fine. But swap "
     "'ticketing system' for any other build-vs-buy decision and it still sends. Code cannot "
     "catch a position that is generic — only the mediator noticing it says nothing specific.")


def _mislabeled(p):
    p["reasoning"][2]["inference_type"] = "direct"   # it's plainly an extrapolation
    p["reasoning"][2]["confidence"] = "high"
    p["reasoning"][2]["claim"] = (
        "The true engineering cost is the $95k quarter plus a permanent day-a-week maintenance "
        "claim on both engineers for as long as the tool exists.")


case("m03", "bad", "mislabeled_inference", "model", None, _mislabeled,
     "An extrapolation (projecting the dashboard's maintenance load onto a tool that doesn't "
     "exist yet) relabelled 'direct' with 'high' confidence. Code cannot tell a direct read "
     "from a stretch — that's the mediator's job, and mislabeling is the debate version of a "
     "fabricated citation.")


def _drift(o):
    o["reasoning"][2]["claim"] = (
        "Two senior engineers are on the bench all year at about $95k per quarter, so the team "
        "has the capacity for this build and several like it.")


case("m04", "bad", "evidence_drift", "model", _drift, None,
     "Cites e2 but restates it: e2 says two engineers are free 'for a Q3 project' at '$95k for "
     "the quarter', not 'all year' at '$95k per quarter'. A real citation pointing at a "
     "distorted version of what it says. Structurally invisible to code.")


if __name__ == "__main__":
    out = Path(__file__).parent / "golden_set.jsonl"
    with out.open("w", encoding="utf-8") as fh:
        for c in CASES:
            fh.write(json.dumps(c) + "\n")

    good = sum(1 for c in CASES if c["label"] == "good")
    by_code = sum(1 for c in CASES if c["caught_by"] == "code")
    by_model = sum(1 for c in CASES if c["caught_by"] == "model")
    print(f"wrote {out}")
    print(f"  {len(CASES)} cases: {good} clean, {by_code} code-catchable, {by_model} model-only")
    # sanity: the 'good' cases must actually be clean under the real gate
    from run import deterministic_checks
    for c in CASES:
        ok, problems = deterministic_checks(c["pack"], c["optimist"], c["pessimist"])
        tag = "CLEAN" if ok else f"BLOCKED ({'; '.join(problems)[:70]})"
        flag = ""
        if c["label"] == "good" and not ok:
            flag = "  <-- FALSE BLOCK, fix the baseline"
        if c["caught_by"] == "code" and ok:
            flag = "  <-- code was supposed to catch this"
        print(f"  {c['id']:<5} {c['label']:<5} {c['caught_by'] or '-':<6} {tag}{flag}")
