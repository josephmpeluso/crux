#!/usr/bin/env python3
"""Builds dry_run.json and asserts every fixture is internally consistent.

A fixture that silently drifts out of spec — a position that no longer lands
in its word budget, a symmetry ratio that crept past 1.25 by accident — turns
a green test suite into a lie. This script recomputes the numbers the
orchestrator will recompute and fails loudly if they don't line up.

The five scenarios, and what each one exercises:

  clean_disagreement  real split; mediator names a sharp crux and WITHHOLDS a
                      verdict because resolving it is cheap and in time
  resolved_crux       same question, but the pack already contains the fact
                      that resolves the crux; mediator issues a verdict
  asymmetric          pessimist position is ~2x the optimist; the symmetry
                      check AND the word-budget check both fire; REJECTED
                      before the mediator is ever called
  phantom_opponent    the optimist rebuts a view it was never shown; the
                      phantom-opponent check fires; REJECTED
  false_consensus     both positions actually reach the same conclusion; the
                      mediator reports consensus with zero divergences rather
                      than manufacturing a fight
"""
import json
from pathlib import Path


def ev(eid, statement, source, confidence="high", date="2026-08-20"):
    return {
        "evidence_id": eid, "statement": statement, "source": source,
        "confidence": confidence, "retrieved_at": date,
    }


def step(claim, refs, inference_type, confidence):
    return {
        "claim": claim, "evidence_refs": refs,
        "inference_type": inference_type, "confidence": confidence,
    }


def meta(agent, attempt=1):
    return {"agent": agent, "model": "fixture", "attempt": attempt}


def wc(pos):
    parts = [pos["thesis"]] + [s["claim"] for s in pos["reasoning"]]
    return len(" ".join(parts).split())


# ======================================================================
# THE DEMO QUESTION: build vs buy a customer-support ticketing system.
#
# Picked because the disagreement hinges on ONE knowable unknown — how many
# internal-system integrations the tool actually needs, and how deep — which
# is cheap to find out and settles almost everything. That makes the crux
# mechanic visible: you can watch the mediator locate the single fact both
# debaters are quietly assuming in opposite directions.
# ======================================================================

BUILD_BUY_EVIDENCE = [
    ev("e1", "Support runs on shared email inboxes today; volume is about 400 tickets/week and growing roughly 8% per quarter.",
       "internal ops dashboard, Aug 2026", "high"),
    ev("e2", "Two senior backend engineers are free for a Q3 project; their fully-loaded cost is about $95k for the quarter.",
       "engineering staffing plan Q3 2026", "high"),
    ev("e3", "The leading off-the-shelf vendor quoted $1,900/month for the team's seat count on an annual contract.",
       "vendor quote, 12 Aug 2026", "high"),
    ev("e4", "Four internal systems (billing, inventory, CRM, provisioning) hold data that support agents currently copy between by hand.",
       "support process audit, Jul 2026", "medium"),
    ev("e5", "The vendor's API allows custom integrations, but each non-standard connector is quoted as a separate paid professional-services engagement.",
       "vendor statement of work draft", "medium"),
    ev("e6", "The last internal tool build (a reporting dashboard) shipped 5 months late and still needs about 1 day/week of maintenance.",
       "reporting dashboard postmortem, 2025", "medium"),
    ev("e7", "CSAT is 78%; the dominant complaint theme is slow first-response time.",
       "quarterly CSAT survey Q2 2026", "high"),
    ev("e8", "No one on the team has run a security or procurement review for an external SaaS vendor that would handle customer data.",
       "IT lead, Aug 2026", "medium"),
]

BUILD_BUY_PACK = {
    "question": "Should we build our own customer-support ticketing system or buy an off-the-shelf one?",
    "decision_deadline": "2026-09-30",
    "context": "Q3 planning. A 'build' commits the two available senior engineers for the quarter; a 'buy' commits to an annual contract and a first-time vendor security review.",
    "evidence": BUILD_BUY_EVIDENCE,
    "run_meta": {"agent": "pack-builder", "model": "fixture", "attempt": 1},
}

# ---- optimist: build ----
OPT_BUILD = {
    "stance": "optimist",
    "thesis": "Build it. The support pain is an integration problem the team is uniquely placed to solve, the engineering capacity exists this quarter at roughly four years' worth of the vendor's subscription, and buying does not cleanly fix the thing customers actually complain about.",
    "reasoning": [
        step("The core complaint is slow first-response time, and agents lose that time hand-copying data between four internal systems on every ticket.",
             ["e7", "e4"], "direct", "high"),
        step("An off-the-shelf tool does not remove that work for free: the vendor bills each non-standard connector as a separate paid engagement, so the real cost of making it fit is well above the $1,900/month sticker.",
             ["e5", "e3"], "direct", "medium"),
        step("The capacity is already on the bench: two senior engineers at about $95k for the quarter is close to four years of the vendor's annual contract, so the build is not the more expensive option over any realistic horizon.",
             ["e2", "e3"], "extrapolation", "medium"),
        step("The four systems that need connecting are systems the team already owns and operates, which makes an in-house integration lower-risk than contracting a vendor to integrate systems it has never seen.",
             ["e4"], "extrapolation", "medium"),
        step("Building also avoids a customer-data security and procurement review that nobody on the team has ever run, keeping both the timeline and the customer data under the team's own control.",
             ["e8"], "direct", "medium"),
    ],
    "what_would_change_my_mind": [
        "If the integrations turn out to be shallow read-only lookups rather than deep two-way syncs, the vendor's standard connectors would likely be enough and the build loses its main rationale.",
        "If the two senior engineers are not actually free for the whole quarter, the cost comparison against the vendor contract collapses.",
        "If slow first-response time is really a staffing or process problem, then neither building nor buying fixes it and the whole framing is wrong.",
    ],
    "word_count": 0,
    "run_meta": meta("optimist"),
}

# ---- pessimist: buy ----
PES_BUY = {
    "stance": "pessimist",
    "thesis": "Buy it. The team's one data point on internal builds is a five-month slip with a permanent maintenance tax, support volume grows every quarter a build would eat, and the market has already solved this problem for a price that looks large next to a sticker and small next to two senior engineers for a quarter.",
    "reasoning": [
        step("The last internal build shipped five months late and still costs about a day a week to maintain; a ticketing system is more central than a reporting dashboard, so a comparable slip would hurt more.",
             ["e6"], "extrapolation", "medium"),
        step("Ticket volume is growing about 8% a quarter, so every quarter the build runs long is a quarter more of shared inboxes while CSAT is already at 78%.",
             ["e1", "e7"], "direct", "high"),
        step("The true engineering cost is not the $95k quarter in isolation: the dashboard's ongoing day-a-week implies a standing maintenance claim on the same two scarce engineers, indefinitely.",
             ["e2", "e6"], "extrapolation", "medium"),
        step("The vendor's paid connectors are at least a quotable, bounded number, whereas the effort to build integrations against four internal systems is unestimated and this team has a track record of estimating such work badly.",
             ["e5", "e4", "e6"], "extrapolation", "medium"),
        step("The security and procurement review is a one-time cost the company will have to pay eventually anyway as it adopts any external tooling, so treating it as a reason to build is deferring an unavoidable task, not avoiding it.",
             ["e8"], "extrapolation", "low"),
    ],
    "what_would_change_my_mind": [
        "If only one or two integrations are actually needed and they are straightforward, the build shrinks to a size where the track-record risk is tolerable.",
        "If the vendor's per-connector professional-services quotes come back very high, the cost advantage of buying narrows or reverses.",
        "If the two engineers would otherwise have no Q3 project, the opportunity-cost argument against spending them on this is much weaker.",
    ],
    "word_count": 0,
    "run_meta": meta("pessimist"),
}

CLEAN_REPORT = {
    "agreements": [
        "Doing nothing is not an option — both positions treat the shared-inbox status quo as unacceptable.",
        "The problem to solve is slow first-response time, and it is substantially an integration and workflow problem rather than purely a headcount problem.",
        "The four internal systems and the manual copying between them are central to whichever solution is chosen.",
        "Engineering capacity is the binding constraint under either path: the same two senior engineers are the scarce resource.",
        "The vendor's sticker price understates the real cost of buying, because the integration work is billed separately.",
    ],
    "divergences": [
        {
            "the_disagreement": "Whether the integration work needed to make any tool fit the four-system workflow is large enough that building in-house is cost-competitive with buying.",
            "optimist_position": "The vendor bills per connector, so real buy cost far exceeds the sticker; team-owned systems make an in-house build the lower-risk way to do the same integration work.",
            "pessimist_position": "Per-connector vendor quotes are at least bounded and knowable; an in-house integration estimate is neither, and this team's estimates have been badly wrong before.",
            "resolving_evidence": "The number of internal-system integrations the support tool actually needs, and for each one whether it is a read-only lookup or a two-way sync.",
            "how_to_obtain_it": "Have the two senior engineers walk the last 20 tickets and record, per ticket, which of the four systems an agent touched and whether they only read or also wrote data; then ask the vendor to quote connectors for exactly that list.",
            "cost_to_obtain": "cheap",
        },
        {
            "the_disagreement": "Whether this team can deliver an internal build close to on schedule.",
            "optimist_position": "Building connectors against systems the team owns is more predictable than the dashboard project was.",
            "pessimist_position": "The only data point is a five-month slip plus permanent maintenance load, and a ticketing system is more central.",
            "resolving_evidence": "A scoped estimate for the integration work from the two engineers who would do it, plus whether the dashboard slip had an identifiable non-recurring cause.",
            "how_to_obtain_it": "One estimation session, plus a 30-minute reread of the dashboard postmortem.",
            "cost_to_obtain": "cheap",
        },
        {
            "the_disagreement": "Whether the first-time vendor security and procurement review is a real blocker or a routine one-time cost.",
            "optimist_position": "It is friction the team has never navigated, and a build sidesteps it entirely.",
            "pessimist_position": "The company will need that capability regardless, so paying it once now is acceptable.",
            "resolving_evidence": "Whether any customer-data-handling SaaS is already in use elsewhere in the company, and the IT lead's estimate of how long a review takes.",
            "how_to_obtain_it": "One conversation with the IT lead.",
            "cost_to_obtain": "cheap",
        },
    ],
    "primary_crux": {
        "the_disagreement": "How many internal-system integrations the support tool genuinely needs, and how many are two-way rather than read-only.",
        "why_this_one": "It is load-bearing for both positions at the same time. The optimist's case needs the integration surface to be large and deep, so vendor per-connector costs balloon and an in-house build pays off. The pessimist's case needs it to be small, so the build risk is not worth taking and the vendor's price roughly holds. Neither debater has the number; both are assuming it in opposite directions, and every other divergence is downstream of it.",
        "resolving_evidence": "A per-ticket integration map from the last 20 tickets: which of the four internal systems an agent touched, read-only versus read-write, produced by the two engineers who would build it.",
        "how_to_obtain_it": "Half a day of the two senior engineers' time, followed by a matching connector quote request to the vendor.",
        "cost_to_obtain": "cheap",
        "resolvable_before_deadline": True,
    },
    "verdict_withheld": True,
    "verdict_rationale": "Withhold. The whole disagreement reduces to one unknown — the real integration surface — and resolving it costs about half a day, well inside the Q3 deadline. Committing $95k of scarce engineering time or an annual contract right now means betting on an assumption neither position could support. Build the integration map first. If it comes back as one or two mostly read-only integrations, buy: the pessimist's track-record and volume-growth arguments then carry and the build has no rationale. If it comes back as three or four two-way syncs, get the vendor's per-connector quote and re-run this decision: a build becomes genuinely competitive and the question shifts to whether the team can deliver it on time.",
    "run_meta": meta("mediator"),
}

# ======================================================================
# resolved_crux: the pack already contains the resolving fact (e9), so the
# mediator can issue a verdict instead of withholding one.
# ======================================================================

RESOLVED_PACK = json.loads(json.dumps(BUILD_BUY_PACK))
RESOLVED_PACK["evidence"].append(
    ev("e9", "Engineering walked the last 20 tickets: two integrations (billing lookup, CRM contact lookup) cover about 90% of tickets and both are read-only; the vendor quoted $4k one-time to build both connectors.",
       "engineering ticket review, 5 Sep 2026", "high", "2026-09-05")
)

OPT_BUILD_RESOLVED = json.loads(json.dumps(OPT_BUILD))
OPT_BUILD_RESOLVED["thesis"] = "Build it. Even with a smaller integration surface than expected, owning the support stack keeps customer data in-house, avoids a first-time vendor review, and costs less than the vendor contract over any multi-year horizon."
OPT_BUILD_RESOLVED["reasoning"] = [
    step("The ticket review shows two read-only integrations cover about 90% of tickets, so the connector work is small, well understood, and comfortably within the two senior engineers' Q3 capacity rather than an open-ended effort.",
         ["e9", "e2"], "direct", "high"),
    step("A small, well-scoped build is exactly the kind of project least exposed to the estimation risk that hurt the reporting dashboard, which was a far larger greenfield effort with none of this clarity about scope up front.",
         ["e9", "e6"], "extrapolation", "medium"),
    step("Two senior engineers for a quarter at about $95k is close to four years of the vendor's annual contract at $1,900 a month, so an in-house tool is the cheaper option over any realistic multi-year horizon.",
         ["e2", "e3"], "extrapolation", "medium"),
    step("The vendor's $4k connector quote is a one-time figure that says nothing about who maintains those connectors when the internal systems change, and that maintenance falls on the same team either way.",
         ["e9", "e4"], "extrapolation", "medium"),
    step("Building keeps customer data inside the company and avoids a security and procurement review that no one on the team has ever run, removing both a schedule risk and a data-exposure question from the decision.",
         ["e8"], "direct", "medium"),
]
OPT_BUILD_RESOLVED["what_would_change_my_mind"] = [
    "If the remaining 10% of tickets need a deep two-way integration after all, the build scope grows and the estimate risk comes back.",
    "If the two engineers have a higher-value Q3 project available, the opportunity cost of spending them here is too high.",
    "If the vendor's $4k connector quote also covers ongoing maintenance the team would otherwise carry, the buy cost advantage widens.",
]
OPT_BUILD_RESOLVED["run_meta"] = meta("optimist")

PES_BUY_RESOLVED = json.loads(json.dumps(PES_BUY))
PES_BUY_RESOLVED["thesis"] = "Buy it. The ticket review removed the one thing that could have justified a build: the integration surface is tiny, two read-only connectors the vendor will build for $4k, so paying two senior engineers for a quarter to reproduce that plus a whole ticketing system is a poor trade."
PES_BUY_RESOLVED["reasoning"] = [
    step("The ticket review shows just two read-only integrations actually matter, and the vendor will build both for a one-time $4k, which is a fraction of what the equivalent senior engineering time would cost to do the same work in-house.",
         ["e9", "e2"], "direct", "high"),
    step("With integrations no longer a differentiator, the decision reduces to building an entire ticketing system from scratch versus paying $1,900 a month for a mature product that already exists, while ticket volume keeps growing about 8% a quarter.",
         ["e9", "e3", "e1"], "direct", "high"),
    step("The team's only data point on internal builds is the reporting dashboard: five months late and still carrying a permanent day-a-week maintenance load, and nothing about a from-scratch ticketing system removes that risk.",
         ["e6"], "extrapolation", "medium"),
    step("Every quarter spent building is a quarter the team stays on shared inboxes with CSAT already at 78% and slow first response as the top complaint, so time-to-value weighs heavily toward the option that is live immediately.",
         ["e1", "e7"], "direct", "high"),
    step("The security and procurement review is a one-time organizational cost the company will pay eventually for any external tooling it adopts, so it is not a durable reason to take on a build.",
         ["e8"], "extrapolation", "low"),
]
PES_BUY_RESOLVED["what_would_change_my_mind"] = [
    "If the vendor's $1,900/month price is not locked and could rise sharply at renewal, the multi-year comparison shifts toward building.",
    "If the two engineers would otherwise be idle this quarter, the opportunity cost of a build is close to zero.",
    "If the 10% of tickets outside the two connectors turn out to need deep integration the vendor cannot do, buying leaves a gap.",
]
PES_BUY_RESOLVED["run_meta"] = meta("pessimist")

RESOLVED_REPORT = {
    "agreements": [
        "The shared-inbox status quo is unacceptable and a tool of some kind is being adopted.",
        "The ticket review settled the integration question: two read-only connectors cover about 90% of tickets.",
        "Engineering capacity is the scarce resource under either path.",
        "The first-time security and procurement review is a one-time cost, not a recurring one.",
        "Support volume is growing every quarter, so time-to-value matters.",
    ],
    "divergences": [
        {
            "the_disagreement": "Whether owning the stack for data control and long-run cost outweighs the delivery risk and time-to-value of a build now that integrations are known to be small.",
            "optimist_position": "A small, well-scoped build avoids the vendor review, keeps data in-house, and costs less over a multi-year horizon.",
            "pessimist_position": "With integrations no longer a differentiator, a build reproduces an existing $1,900/month product while carrying this team's known slip risk.",
            "resolving_evidence": "Whether the two engineers have a higher-value Q3 project available, and whether the vendor's $1,900/month price is contractually locked against renewal increases.",
            "how_to_obtain_it": "One conversation with the engineering lead about Q3 priorities, and one clause check with the vendor on renewal pricing.",
            "cost_to_obtain": "cheap",
        }
    ],
    "primary_crux": {
        "the_disagreement": "Whether the two senior engineers have a materially higher-value use of the quarter than building this tool.",
        "why_this_one": "Once the ticket review shrank the integration surface, the cost and data-control arguments for building got weaker and the opportunity cost of the engineers became the deciding factor. If they have nothing better to do, the build's downside is small; if they do, buying is clearly right.",
        "resolving_evidence": "The engineering lead's ranked list of candidate Q3 projects for these two engineers and the value attached to each.",
        "how_to_obtain_it": "One prioritization conversation with the engineering lead, referencing the existing Q3 staffing plan.",
        "cost_to_obtain": "cheap",
        "resolvable_before_deadline": True,
    },
    "verdict_withheld": False,
    "verdict_rationale": "Lean buy. The ticket review already resolved the original crux — integrations are two read-only connectors the vendor will build for $4k — which removes the optimist's strongest argument. What remains is opportunity cost. If the engineering lead confirms these two engineers have any project worth more than a support-tool build, buy the vendor product: it is faster to value while volume grows, and the team's one build data point is a five-month slip. If the engineers would genuinely otherwise be idle this quarter and the vendor price is not locked against renewal hikes, a build is defensible on long-run cost — but that is the weaker branch and it needs both conditions to hold.",
    "run_meta": meta("mediator"),
}

# ======================================================================
# asymmetric: the pessimist writes ~2x the optimist. Both the per-position
# word-budget check and the cross-position symmetry ratio fire, and the run
# is rejected before the mediator is called.
# ======================================================================

OPT_SHORT = json.loads(json.dumps(OPT_BUILD))
OPT_SHORT["thesis"] = "Build it. The pain is integration-shaped, the engineers are available now, and buying does not cleanly solve it."
OPT_SHORT["reasoning"] = [
    step("Customers complain about slow first response, and agents lose that time copying between four internal systems.",
         ["e7", "e4"], "direct", "high"),
    step("Two senior engineers are free this quarter at about $95k, close to four years of the vendor contract.",
         ["e2", "e3"], "extrapolation", "medium"),
]
OPT_SHORT["what_would_change_my_mind"] = [
    "If the integrations are shallow read-only lookups, the vendor's standard connectors would be enough.",
]
OPT_SHORT["run_meta"] = meta("optimist")

PES_LONG = json.loads(json.dumps(PES_BUY))
# pad every claim with extra verbiage so the position roughly doubles the optimist
PES_LONG["thesis"] = ("Buy the off-the-shelf product, without hesitation, because the entire weight of the "
    "team's actual operating history points that way, and because the apparent price gap between a monthly "
    "subscription and a one-quarter engineering project is an illusion that disappears the moment ongoing "
    "maintenance, opportunity cost, and delivery risk are priced in honestly rather than waved away.")
PES_LONG["reasoning"] = [
    step("The single most relevant piece of evidence the team has about its own ability to ship internal tooling is the reporting dashboard, which shipped a full five months later than planned and, more than a year on, still consumes approximately one full engineering day every single week in maintenance, and a customer-facing ticketing system sits far closer to the critical path of the business than an internal dashboard ever did, so a slip of comparable proportion would do proportionally greater damage to revenue, to customer trust, and to the morale of the very engineers being asked to build it.",
         ["e6"], "extrapolation", "medium"),
    step("Ticket volume is not static but is compounding at roughly eight percent every quarter, which means that every additional quarter the build overruns its schedule is a quarter in which an ever-larger number of customers are served through shared email inboxes, with no routing, no prioritization, and no visibility, while the customer satisfaction score already sits at a distinctly unhealthy seventy-eight percent and the dominant complaint is precisely the slow first-response time that a longer build guarantees will get worse before it gets better.",
         ["e1", "e7"], "direct", "high"),
    step("The headline engineering cost of roughly ninety-five thousand dollars for the quarter is presented as though it were a one-time payment, but the dashboard precedent makes clear that internal tools carry a permanent maintenance tail, so the true cost of building is that quarter of salary plus an indefinite standing claim of something like a day a week from the same two senior engineers who are the scarcest resource the organization has, forever, or until the tool is finally decommissioned years later.",
         ["e2", "e6"], "extrapolation", "medium"),
    step("Whatever integration work is required against the four internal systems, the vendor's model at least produces a specific dollar figure per connector that can be reviewed, negotiated, and budgeted before any commitment is made, whereas the in-house alternative requires this specific team to produce an accurate up-front estimate of integration effort, and the one time the team attempted an estimate of remotely comparable scope the result was wrong by five months, which is not a small error bar but a categorical failure of estimation.",
         ["e5", "e4", "e6"], "extrapolation", "medium"),
    step("The security and procurement review that the team has never run is being treated as a hidden cost of buying, but it is nothing of the sort, because it is a one-time organizational capability that any growing company must develop the moment it adopts any external system that touches customer data, and deferring it by building in-house this one time does not remove the task, it merely pushes the same unavoidable work a few months into the future while the company continues to grow and the eventual review becomes larger.",
         ["e8"], "extrapolation", "low"),
    step("Taken together, the pattern is that every argument for building rests on an optimistic reading of a number the team does not actually have — integration effort, delivery date, maintenance load, opportunity cost — while every argument for buying rests on a number that is already written down somewhere, which is exactly the asymmetry that should drive a decision made under a deadline.",
         ["e2", "e3", "e6"], "extrapolation", "medium"),
]
PES_LONG["what_would_change_my_mind"] = [
    "If only one or two integrations are actually needed and they are straightforward, the build shrinks to a size where the estimation risk is tolerable and the case reverses.",
    "If the vendor's per-connector quotes come back extremely high, the bounded-cost advantage of buying erodes.",
]
PES_LONG["run_meta"] = meta("pessimist")

# ======================================================================
# phantom_opponent: the optimist acknowledges and rebuts a view it was never
# shown. The phantom-opponent check fires; the run is rejected.
# ======================================================================

OPT_PHANTOM = json.loads(json.dumps(OPT_BUILD))
OPT_PHANTOM["reasoning"][1] = step(
    "Critics might argue that the team's track record on internal builds is poor, but building connectors against systems the team already owns is a categorically different task from the greenfield dashboard project, so the bear case does not apply here.",
    ["e4", "e6"], "extrapolation", "medium",
)
OPT_PHANTOM["run_meta"] = meta("optimist")

# ======================================================================
# false_consensus: opposite stances assigned, but the reasoning converges.
# The pessimist, told to argue against, cannot build a real case for keeping
# the legacy stack — only for a graceful wind-down. The mediator must report
# consensus rather than invent a divergence.
# ======================================================================

SHUTDOWN_EVIDENCE = [
    ev("e1", "The v1 product line is about 6% of revenue and declining roughly 15% per quarter.",
       "revenue dashboard Q2 2026", "high"),
    ev("e2", "v1 shares no infrastructure with v2; it runs on a separate stack that needs its own 2-engineer on-call rotation.",
       "infrastructure inventory, 2026", "high"),
    ev("e3", "40 customers remain on v1; all have been offered a paid migration to v2 and 30 have accepted.",
       "customer success tracker, Aug 2026", "medium"),
    ev("e4", "The 10 customers not yet migrated are all month-to-month with no contractual lock-in.",
       "contracts review, Aug 2026", "medium"),
    ev("e5", "v1's separate stack had two Sev-1 incidents last quarter, consuming about 60 engineer-hours.",
       "incident log Q2 2026", "high"),
    ev("e6", "Support reports v1 tickets take about 3x longer to resolve because of lost institutional knowledge.",
       "support team retro, Jul 2026", "medium"),
]

SHUTDOWN_PACK = {
    "question": "Should we shut down the v1 product line now that v2 has shipped?",
    "decision_deadline": "2026-10-15",
    "context": "v2 has been generally available for two quarters. The question is whether to formally end-of-life v1 now or keep it running into next year.",
    "evidence": SHUTDOWN_EVIDENCE,
    "run_meta": {"agent": "pack-builder", "model": "fixture", "attempt": 1},
}

OPT_SHUTDOWN = {
    "stance": "optimist",
    "thesis": "Shut it down now. v1 is a small and shrinking share of revenue that carries a wildly disproportionate operational cost, and the migration is nearly finished with no contractual obstacle to closing out the rest.",
    "reasoning": [
        step("v1 is about 6% of revenue and falling roughly 15% a quarter, so its contribution is small and headed toward zero on its own.",
             ["e1"], "direct", "high"),
        step("It runs on a wholly separate stack with its own two-engineer on-call rotation, which is a fixed operational cost that does not shrink as the revenue does.",
             ["e2"], "direct", "high"),
        step("That stack produced two Sev-1s and about 60 engineer-hours of incident work last quarter, plus support tickets that take three times as long to resolve, so the real cost is well above the on-call rotation alone.",
             ["e5", "e6"], "direct", "high"),
        step("Migration is most of the way done: 30 of 40 customers have already accepted the paid path to v2, so shutting down is finishing a process, not starting one.",
             ["e3"], "direct", "medium"),
        step("The 10 who have not migrated are month-to-month with no lock-in, so there is no contractual barrier to a clean wind-down on a defined timeline.",
             ["e4"], "direct", "medium"),
    ],
    "what_would_change_my_mind": [
        "If any of the 10 remaining customers are strategically important accounts whose churn would cost far more than their v1 revenue, the timeline should stretch to protect them.",
        "If decommissioning the separate stack turns out to need significant engineering work itself, the near-term cost saving is smaller than it looks.",
    ],
    "word_count": 0,
    "run_meta": meta("optimist"),
}

PES_SHUTDOWN = {
    "stance": "pessimist",
    "thesis": "There is no real case for keeping the v1 stack running beyond a short wind-down. The only argument against shutting down now is managing the last 10 customers gracefully, and even that is a timing question rather than a reason to keep v1 alive.",
    "reasoning": [
        step("The 10 non-migrated customers still represent live revenue and relationships, and an abrupt cutoff could turn a managed migration into churn and public complaints.",
             ["e3", "e4"], "extrapolation", "medium"),
        step("However, those customers are month-to-month with no lock-in, which means they can leave at any time regardless, so keeping v1 running does not actually secure that revenue.",
             ["e4"], "direct", "medium"),
        step("The operational burden is real and one-directional: a separate stack, its own on-call rotation, two Sev-1s last quarter, and triple-length support tickets, none of which improves by waiting.",
             ["e2", "e5", "e6"], "direct", "high"),
        step("Revenue is declining about 15% a quarter, so every quarter v1 stays up the cost-to-value ratio gets worse, not better.",
             ["e1"], "direct", "high"),
        step("The strongest version of the against-shutdown position is therefore only a request for a defined wind-down window for the last 10 accounts, not a case for keeping the stack indefinitely.",
             ["e3", "e4"], "extrapolation", "medium"),
    ],
    "what_would_change_my_mind": [
        "If several of the 10 remaining customers signal they need more than a quarter to migrate for legitimate technical reasons, the wind-down window should be longer.",
        "If v1 revenue were stable or growing rather than declining 15% a quarter, the disproportionate operational cost would be easier to justify carrying.",
    ],
    "word_count": 0,
    "run_meta": meta("pessimist"),
}

CONSENSUS_REPORT = {
    "agreements": [
        "v1 is a small and shrinking share of revenue: about 6%, declining roughly 15% per quarter.",
        "The operational cost of v1 is real and disproportionate: a separate stack, a dedicated on-call rotation, two Sev-1 incidents last quarter, and triple-length support tickets.",
        "The migration is nearly complete: 30 of 40 customers have accepted the paid path to v2.",
        "The 10 remaining customers have no contractual lock-in, so keeping v1 running does not actually secure their revenue.",
        "Both positions conclude that v1 should be wound down; they differ only on how much time to give the last 10 accounts.",
    ],
    "divergences": [],
    "primary_crux": {
        "the_disagreement": "How long a wind-down window the 10 remaining v1 customers should be given before the stack is switched off.",
        "why_this_one": "It is the only point the two independently built positions do not already agree on, and even here the disagreement is narrow: both accept that v1 is being shut down, so the crux affects the schedule, not the decision.",
        "resolving_evidence": "Each of the 10 remaining customers' stated migration timeline and whether any has a legitimate technical blocker to moving within a quarter.",
        "how_to_obtain_it": "A one-week round of check-in calls by customer success with the 10 accounts, against the existing migration tracker.",
        "cost_to_obtain": "cheap",
        "resolvable_before_deadline": True,
    },
    "verdict_withheld": False,
    "verdict_rationale": "Proceed with the shutdown. Both positions were built independently and both reach the same conclusion: wind v1 down. The pessimist, whose assignment was to argue against, could not construct a case for keeping the separate stack running — only a case for an orderly exit for the 10 no-lock-in customers. There is no genuine divergence here to resolve before deciding. The one open question is the wind-down window: run a one-week check-in with the 10 remaining accounts, and if several report a real technical blocker to migrating within a quarter, extend the window for those accounts specifically — but do not keep the stack past that, and do not let the window slip open-ended.",
    "run_meta": meta("mediator"),
}

# ---------------------------------------------------------------- assemble
for _p in (OPT_BUILD, PES_BUY, OPT_BUILD_RESOLVED, PES_BUY_RESOLVED, OPT_SHORT,
           PES_LONG, OPT_PHANTOM, OPT_SHUTDOWN, PES_SHUTDOWN):
    _p["word_count"] = wc(_p)

FIXTURES = {
    "clean_disagreement": {
        "evidence_pack": BUILD_BUY_PACK,
        "optimist": OPT_BUILD,
        "pessimist": PES_BUY,
        "crux_report": CLEAN_REPORT,
    },
    "resolved_crux": {
        "evidence_pack": RESOLVED_PACK,
        "optimist": OPT_BUILD_RESOLVED,
        "pessimist": PES_BUY_RESOLVED,
        "crux_report": RESOLVED_REPORT,
    },
    "asymmetric": {
        "evidence_pack": BUILD_BUY_PACK,
        "optimist": OPT_SHORT,
        "pessimist": PES_LONG,
        # no crux_report: this run is rejected before the mediator is called
    },
    "phantom_opponent": {
        "evidence_pack": BUILD_BUY_PACK,
        "optimist": OPT_PHANTOM,
        "pessimist": PES_BUY,
        # no crux_report: rejected before the mediator
    },
    "false_consensus": {
        "evidence_pack": SHUTDOWN_PACK,
        "optimist": OPT_SHUTDOWN,
        "pessimist": PES_SHUTDOWN,
        "crux_report": CONSENSUS_REPORT,
    },
}

WORD_BUDGET = 220
WORD_TOLERANCE = 60
SYMMETRY_MAX_RATIO = 1.25

if __name__ == "__main__":
    def ratio(a, b):
        return max(a, b) / max(min(a, b), 1)

    # clean_disagreement and false_consensus and resolved_crux must be
    # internally clean: both positions in budget, symmetry under the limit.
    for name in ("clean_disagreement", "resolved_crux", "false_consensus"):
        o, p = wc(FIXTURES[name]["optimist"]), wc(FIXTURES[name]["pessimist"])
        assert abs(o - WORD_BUDGET) <= WORD_TOLERANCE, f"{name} optimist {o} words, out of budget"
        assert abs(p - WORD_BUDGET) <= WORD_TOLERANCE, f"{name} pessimist {p} words, out of budget"
        assert ratio(o, p) <= SYMMETRY_MAX_RATIO, f"{name} symmetry {ratio(o,p):.2f}x over limit"
        print(f"  {name}: optimist {o}w, pessimist {p}w, symmetry {ratio(o,p):.2f}x  OK")

    # asymmetric MUST trip the checks — assert it actually does
    o, p = wc(OPT_SHORT), wc(PES_LONG)
    assert ratio(o, p) > SYMMETRY_MAX_RATIO, f"asymmetric symmetry only {ratio(o,p):.2f}x — not asymmetric enough"
    assert abs(p - WORD_BUDGET) > WORD_TOLERANCE, f"asymmetric pessimist {p}w — should exceed budget"
    print(f"  asymmetric: optimist {o}w, pessimist {p}w, symmetry {ratio(o,p):.2f}x  (trips both checks, as intended)")

    out = Path(__file__).parent / "dry_run.json"
    out.write_text(json.dumps(FIXTURES, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {out}")
