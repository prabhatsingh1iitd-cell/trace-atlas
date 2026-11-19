"""Complete partial audits without inflating the original agreement statistic."""

import asyncio
import hashlib
from pathlib import Path
from data import read_json, atomic_json, dumps, make_packet
from mining import CLASSIFY, assignment_schema, validate_assignments, unresolved


async def complete_audit(traces, taxonomy, assignments, cache, glm):
    cache = Path(cache)
    path = cache / "audit.json"
    prior = read_json(path)
    if (
        prior.get("completion_pass")
        and prior["validated_sample_size"] == prior["requested_sample_size"]
        and prior["adjudicated_count"] == prior["conflict_count"]
    ):
        return prior
    selected = prior["sample_trace_ids"]
    checks = {}
    original_task = (
        CLASSIFY
        + " This is a fresh consistency audit using expanded evidence. Do not assume earlier labels."
    )

    async def recover(batch):
        response = await glm.request(
            original_task,
            {
                "taxonomy": taxonomy,
                "traces": [make_packet(traces[i], expanded=True) for i in batch],
            },
            7000,
            schema=assignment_schema(batch, traces, taxonomy),
        )
        checks.update(validate_assignments(response, batch, traces, taxonomy))

    await asyncio.gather(
        *(recover(selected[i : i + 8]) for i in range(0, len(selected), 8))
    )
    recovered = set(checks)
    # Prior flags preserve the first comparison, even where adjudication changed a label.
    initial_agreement = {
        i: bool(assignments[i]["audit_initial_agreement"])
        for i in recovered
        if "audit_initial_agreement" in assignments[i]
    }
    if len(initial_agreement) != len(recovered):
        raise ValueError("Cannot reconstruct the original audit comparison")
    missing = [i for i in selected if i not in checks]

    async def repair(tid):
        response = await glm.request(
            original_task + " Complete this single-trace audit repair.",
            {"taxonomy": taxonomy, "traces": [make_packet(traces[tid], expanded=True)]},
            4000,
            schema=assignment_schema([tid], traces, taxonomy),
        )
        valid = validate_assignments(response, [tid], traces, taxonomy)
        if tid in valid:
            checks[tid] = valid[tid]
            initial_agreement[tid] = (
                valid[tid]["workflow_id"] == assignments[tid]["workflow_id"]
            )

    await asyncio.gather(*(repair(i) for i in missing))
    conflicts = sorted(i for i, v in initial_agreement.items() if not v)
    decisions = {}

    async def adjudicate(batch, single=False):
        task = (
            CLASSIFY
            + " Resolve disagreement between classifier and expanded-evidence audit. Choose only an evidenced workflow or WF00 for unresolved ambiguity. This completion pass does not revise the original agreement score."
        )
        if single:
            task += " Single-trace repair."
        payload = {
            "taxonomy": taxonomy,
            "traces": [make_packet(traces[i], expanded=True) for i in batch],
            "prior_judgments": [
                {"trace_id": i, "first": assignments[i], "second": checks[i]}
                for i in batch
            ],
        }
        response = await glm.request(
            task, payload, 6000, schema=assignment_schema(batch, traces, taxonomy)
        )
        decisions.update(validate_assignments(response, batch, traces, taxonomy))

    await asyncio.gather(
        *(adjudicate(conflicts[i : i + 4]) for i in range(0, len(conflicts), 4))
    )
    still_missing = [i for i in conflicts if i not in decisions]
    if still_missing:
        await asyncio.gather(*(adjudicate([i], True) for i in still_missing))
    for i in conflicts:
        if i in decisions:
            assignments[i] = decisions[i]
            assignments[i]["method"] = "glm_adjudicated"
        else:
            assignments[i] = unresolved(i, "unresolved")
            assignments[i]["method"] = "glm_audit_conflict"
            assignments[i]["explanation"] = (
                "GLM judgments disagreed and adjudication did not produce a validated resolution."
            )
    for i, agreed in initial_agreement.items():
        assignments[i]["audit_checked"] = True
        assignments[i]["audit_initial_agreement"] = agreed
    agreement = sum(initial_agreement.values())
    report = {
        **prior,
        "validated_sample_size": len(initial_agreement),
        "validated_trace_ids": sorted(initial_agreement),
        "initial_agreement_count": agreement,
        "initial_agreement_percent": 100 * agreement / len(initial_agreement)
        if initial_agreement
        else None,
        "conflict_count": len(conflicts),
        "adjudicated_count": len(decisions),
        "completion_pass": True,
        "repaired_missing_checks": len(initial_agreement) - len(recovered),
        "unvalidated_trace_ids": sorted(set(selected) - set(initial_agreement)),
        "unresolved_adjudication_count": len(conflicts) - len(decisions),
        "comparison_note": "Original agreement flags are retained through adjudication; the completion pass fills previously invalid checks and resolves disagreements without recomputing agreement against corrected labels.",
    }
    report["assignment_digest"] = hashlib.sha256(
        dumps(
            {
                i: {k: a.get(k) for k in ["workflow_id", "confidence", "method"]}
                for i, a in sorted(assignments.items())
            }
        ).encode()
    ).hexdigest()
    atomic_json(cache / "assignments.json", assignments)
    atomic_json(path, report)
    print(
        dumps(
            {
                "phase": "audit_completed",
                "validated": len(initial_agreement),
                "requested": len(selected),
                "conflicts": len(conflicts),
                "adjudicated": len(decisions),
            }
        ),
        flush=True,
    )
    return report
