"""Deterministic hierarchy rollups and compact, source-ID-preserving exports."""

from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from statistics import median
from data import atomic_json, read_json, dumps, merge_metrics, public_metrics, excerpt
from mining import UNKNOWN, unresolved, workflow_map
from analytics import usage_statistics, concentration

NOTES = [
    "One analytical trace is one supplied trace_id; calls are ordered by call_index. A trace receives one primary workflow and use case; all constituent calls inherit it. No secondary labels contribute usage.",
    "Recorded token shares divide known source_reported input plus output tokens by the same dataset-wide recorded sum. Estimates and session totals are excluded. Null means no applicable known counter; supplied zero remains zero.",
    "estimated_cl100k_base counters are supplied tokenizer estimates over serialized conversations, excluding provider chat templates and separate tool-schema overhead. They are not API charges. No new token estimates or dollar costs are invented.",
    "source_reported counts are historical telemetry, not verified invoices. Input counters for converted Claude/Pi calls already include cache reads and creation; these components are not added again.",
    "Missing per-call usage stays unknown. source_reported_session_usage is shown separately as a diagnostic and is not added to per-call totals or allocated across calls.",
    "Imported traces may be synthetic or benchmark traffic. Categories describe supported purposes, not verified production business adoption or successful outcomes.",
    "Classification uses bounded excerpts; omission and same-model semantic error remain possible. Confidence is qualitative and same-model audit agreement is not independent accuracy.",
    "Only hyde/glm-5.3-flash performs semantic inference. TF-IDF and mini-batch clustering select a diverse discovery sample; bulk assignments are direct GLM judgments, without label propagation.",
]


def write_jsonl(path, rows):
    path = Path(path)
    temp = path.with_suffix(path.suffix + ".tmp")
    with temp.open("w", encoding="utf-8") as f:
        for r in rows:
            f.write(dumps(r) + "\n")
    temp.replace(path)


def examples_for(members, traces, assignments):
    if not members:
        return []
    priority = {"high": 0, "medium": 1, "low": 2}
    center = median(len(traces[i]["calls"]) for i in members)
    ordered = sorted(
        members,
        key=lambda i: (
            priority[assignments[i]["confidence"]],
            abs(len(traces[i]["calls"]) - center),
            i,
        ),
    )
    choices = [
        (
            ordered[0],
            "Example near median trace length, prioritizing available confidence",
        )
    ]
    high = max(
        members,
        key=lambda i: (
            traces[i]["metrics"]["recorded_input_tokens"]
            + traces[i]["metrics"]["recorded_output_tokens"]
        ),
    )
    high_tokens = (
        traces[high]["metrics"]["recorded_input_tokens"]
        + traces[high]["metrics"]["recorded_output_tokens"]
    )
    if high != ordered[0] and high_tokens > 0:
        choices.append((high, "Largest recorded-token trace in this workflow"))
    result = []
    for tid, selection in choices:
        t = traces[tid]
        a = assignments[tid]
        sid = a.get("evidence_span_id")
        candidates = [e for e in t["events"] if e["span_id"] == sid]
        candidates.sort(key=lambda e: e["role"] != "user")
        if not candidates:
            candidates = [e for e in t["events"] if e["role"] == "user"] or t["events"]
        if not candidates:
            continue
        e = candidates[0]
        result.append(
            {
                "trace_id": tid,
                "span_id": e["span_id"],
                "call_index": e["call_index"],
                "role": e["role"],
                "excerpt": excerpt(e["text"], 240),
                "excerpt_is_truncated": len(e["text"]) > 240,
                "selection_method": selection,
                "confidence": a["confidence"],
                "call_count": len(t["calls"]),
            }
        )
    return result


def export(traces, manifest, cache, output, project_name):
    cache = Path(cache)
    out = Path(output)
    out.mkdir(parents=True, exist_ok=True)
    taxonomy = (
        read_json(cache / "taxonomy.json")
        if (cache / "taxonomy.json").exists()
        else {
            "version": "incomplete",
            "business_use_cases": [UNKNOWN],
            "discovery_trace_count": 0,
        }
    )
    assignments = (
        read_json(cache / "assignments.json")
        if (cache / "assignments.json").exists()
        else {}
    )
    profiles = (
        read_json(cache / "workflow_profiles.json")
        if (cache / "workflow_profiles.json").exists()
        else {}
    )
    for tid in traces:
        if tid not in assignments:
            assignments[tid] = unresolved(tid)
    if set(assignments) != set(traces):
        raise ValueError("Assignment/source mismatch")
    allowed = workflow_map(taxonomy)
    groups = defaultdict(list)
    for tid, a in assignments.items():
        if (
            a["workflow_id"] not in allowed
            or allowed[a["workflow_id"]][0]["id"] != a["use_case_id"]
        ):
            raise ValueError("Invalid hierarchy reference")
        groups[a["workflow_id"]].append(tid)
    baseline = manifest["baseline"]
    den = baseline["recorded_input_tokens"] + baseline["recorded_output_tokens"]
    usecases = []
    raw_rollups = []
    for uc in taxonomy["business_use_cases"]:
        workflows = []
        uc_metrics = []
        for wf in uc["workflows"]:
            members = sorted(groups[wf["id"]])
            if not members:
                continue
            m = merge_metrics(traces[t]["metrics"] for t in members)
            uc_metrics.append(m)
            workflows.append(
                {
                    **wf,
                    **public_metrics(m, den),
                    "assignment_confidence_counts": dict(
                        Counter(assignments[t]["confidence"] for t in members)
                    ),
                    "examples": examples_for(members, traces, assignments),
                    "trace_ids": members,
                    "activity_profile": profiles.get(wf["id"]),
                    "usage_statistics": usage_statistics(members, traces),
                }
            )
        if not workflows:
            continue
        m = merge_metrics(uc_metrics)
        raw_rollups.append(m)
        workflows.sort(key=lambda w: w["recorded_total_tokens"] or 0, reverse=True)
        usecases.append(
            {k: v for k, v in uc.items() if k != "workflows"}
            | public_metrics(m, den)
            | {"workflows": workflows}
        )
    if merge_metrics(raw_rollups) != baseline:
        raise ValueError("Hierarchy does not reconcile to baseline")
    usecases.sort(key=lambda u: u["recorded_total_tokens"] or 0, reverse=True)
    coverage = []
    for method in sorted(set(a["method"] for a in assignments.values())):
        members = [i for i, a in assignments.items() if a["method"] == method]
        coverage.append(
            {
                "method": method,
                **public_metrics(
                    merge_metrics(traces[i]["metrics"] for i in members), den
                ),
            }
        )
    unresolved_ids = [i for i, a in assignments.items() if a["workflow_id"] == "WF00"]
    unresolved_metrics = public_metrics(
        merge_metrics(traces[i]["metrics"] for i in unresolved_ids), den
    )
    statuses = Counter(a["status"] for a in assignments.values())
    confidence = Counter(a["confidence"] for a in assignments.values())
    audit = (
        read_json(cache / "audit.json")
        if (cache / "audit.json").exists()
        else {"status": "not_run"}
    )
    history = (
        read_json(cache / "audit_history.json")
        if (cache / "audit_history.json").exists()
        else []
    )
    refinement = (
        read_json(cache / "refinement.json")
        if (cache / "refinement.json").exists()
        else None
    )
    # Summarize only completed successful requests; raw requests stay outside public exports.
    request_usage = {"request_count": 0, "input_tokens": 0, "output_tokens": 0}
    for path in (cache / "requests").glob("*.json"):
        r = read_json(path)
        usage = r.get("usage") or {}
        request_usage["request_count"] += 1
        request_usage["input_tokens"] += usage.get("prompt_tokens") or 0
        request_usage["output_tokens"] += usage.get("completion_tokens") or 0
    ordered = sorted(
        traces,
        key=lambda i: (
            traces[i]["metrics"]["recorded_input_tokens"]
            + traces[i]["metrics"]["recorded_output_tokens"]
        ),
        reverse=True,
    )
    topn = max(1, round(len(ordered) * 0.01))
    top_tokens = sum(
        traces[i]["metrics"]["recorded_input_tokens"]
        + traces[i]["metrics"]["recorded_output_tokens"]
        for i in ordered[:topn]
    )
    insights = [
        {
            "type": "recorded_usage_concentration",
            "top_trace_count": topn,
            "trace_fraction_percent": 100 * topn / len(traces),
            "recorded_token_share_percent": 100 * top_tokens / den if den else None,
            "interpretation": "Prioritize review of these high-usage traces; concentration alone does not prove waste.",
        },
        {
            "type": "input_output_mix",
            "recorded_input_share_percent": 100
            * baseline["recorded_input_tokens"]
            / den
            if den
            else None,
            "interpretation": "Input context dominates only to the extent shown by the measured ratio. Inspect repeated context before proposing caching or compaction; no savings or provider discount is assumed.",
        },
    ]
    results = {
        "schema_version": "1.1",
        "project_name": project_name,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source": {
            "filename": "traces.parquet",
            "sha256": manifest["sha256"],
            "row_count": manifest["row_count"],
            "trace_count": manifest["trace_count"],
        },
        "hierarchy": "Business use case → workflow → trace_id → span_id",
        "usage_share_basis": "Known source_reported input + output tokens, excluding estimates and session totals",
        "recorded_share_denominator_tokens": den,
        "summary": public_metrics(baseline, den),
        "business_use_cases": usecases,
        "classification": {
            "model": "hyde/glm-5.3-flash",
            "taxonomy_version": taxonomy.get("version"),
            "discovery_trace_count": taxonomy.get("discovery_trace_count", 0),
            "assignment_methods": coverage,
            "confidence_trace_counts": dict(confidence),
            "status_trace_counts": dict(statuses),
            "unresolved": unresolved_metrics,
            "audit": audit,
            "audit_history": history,
            "fuller_context_review": refinement,
        },
        "analytics": {
            "usage_statistics": usage_statistics(sorted(traces), traces),
            "concentration_curve": concentration(traces),
            "input_reduction_scenarios": [
                {
                    "assumed_input_reduction_fraction": f,
                    "hypothetical_tokens_avoided": baseline["recorded_input_tokens"]
                    * f,
                    "hypothetical_remaining_recorded_tokens": den
                    - baseline["recorded_input_tokens"] * f,
                }
                for f in [0.05, 0.10, 0.20]
            ],
            "scenario_assumptions": "Sensitivity analysis only, not measured savings. Assumes the chosen fraction of source-reported input tokens can safely be avoided with unchanged output and quality. Does not infer provider cache eligibility, prices, invoice savings, or actual achievable reduction.",
        },
        "session_usage_diagnostic": manifest["session_usage_diagnostic"],
        "insights": insights,
        "notes": NOTES,
        "files": {
            "call_assignments": "call_assignments.jsonl",
            "trace_assignments": "trace_assignments.jsonl",
            "quality": "quality.json",
        },
    }
    quality = {
        "source_sha256": manifest["sha256"],
        "status": "complete"
        if not any(a["method"] == "unresolved" for a in assignments.values())
        else "incomplete",
        "original_record_coverage_percent": 100.0,
        "original_trace_coverage_percent": 100.0,
        "unique_span_ids": manifest["row_count"],
        "usage_basis_counts": manifest["usage_basis_counts"],
        "source_anomalies": manifest["anomalies"],
        "reconciliation": "All hierarchy counts and known token sums equal the independent source baseline.",
        "semantic_limitations": NOTES[5:7],
        "pipeline_inference_usage": request_usage,
        "pipeline_usage_note": "Completed cached API responses, including responses rejected by assignment validation; excludes failed/truncated requests and preflight. Separate from historical usage.",
        "audit": audit,
        "assignment_status_counts": dict(statuses),
    }
    write_jsonl(
        out / "call_assignments.jsonl",
        (
            {
                "trace_id": tid,
                "span_id": c["span_id"],
                "call_index": c["call_index"],
                "use_case_id": assignments[tid]["use_case_id"],
                "workflow_id": assignments[tid]["workflow_id"],
            }
            for tid in sorted(traces)
            for c in traces[tid]["calls"]
        ),
    )
    write_jsonl(
        out / "trace_assignments.jsonl",
        (
            {
                **assignments[tid],
                **public_metrics(traces[tid]["metrics"], den),
                "observed_tool_names": traces[tid]["tools"][:20],
                "packet_evidence_count": len(traces[tid]["packet"]["evidence"]),
                "packet_is_excerpted": True,
            }
            for tid in sorted(traces)
        ),
    )
    atomic_json(out / "results.json", results)
    atomic_json(out / "quality.json", quality)
    print(
        dumps(
            {
                "phase": "exported",
                "calls": baseline["call_count"],
                "traces": len(traces),
                "use_cases": len(usecases),
                "workflows": sum(len(u["workflows"]) for u in usecases),
                "unresolved_traces": len(unresolved_ids),
            }
        ),
        flush=True,
    )
    return results
