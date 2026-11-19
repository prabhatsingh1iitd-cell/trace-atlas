"""Validate exported results, optionally reconcile to the supplied Parquet."""

import argparse
import json
import math
from collections import Counter
from pathlib import Path

SUM_FIELDS = [
    "call_count",
    "trace_count",
    "recorded_input_tokens",
    "recorded_output_tokens",
    "estimated_input_tokens",
    "estimated_output_tokens",
    "recorded_input_known_calls",
    "recorded_output_known_calls",
    "recorded_both_known_calls",
    "estimated_input_known_calls",
    "estimated_output_known_calls",
    "calls_with_unknown_usage",
    "input_unknown_calls",
    "output_unknown_calls",
    "source_reported_calls",
    "estimated_calls",
    "unknown_basis_calls",
]


def read(path):
    return json.loads(Path(path).read_text())


def jsonl(path):
    with Path(path).open() as f:
        for line in f:
            if line.strip():
                yield json.loads(line)


def numeric_tree(value):
    if isinstance(value, float):
        assert math.isfinite(value), "Nonfinite JSON value"
    elif isinstance(value, dict):
        for v in value.values():
            numeric_tree(v)
    elif isinstance(value, list):
        for v in value:
            numeric_tree(v)


def validate(output, dataset=None):
    output = Path(output)
    r = read(output / "results.json")
    q = read(output / "quality.json")
    numeric_tree(r)
    numeric_tree(q)
    traces = list(jsonl(output / "trace_assignments.jsonl"))
    calls = list(jsonl(output / "call_assignments.jsonl"))
    tm = {t["trace_id"]: t for t in traces}
    assert len(tm) == len(traces), "Duplicate trace assignments"
    cm = {c["span_id"]: c for c in calls}
    assert len(cm) == len(calls), "Duplicate span assignments"
    wf = {w["id"]: (u, w) for u in r["business_use_cases"] for w in u["workflows"]}
    assert len(wf) == sum(len(u["workflows"]) for u in r["business_use_cases"])
    counts = Counter(c["trace_id"] for c in calls)
    assert set(counts) == set(tm)
    for c in calls:
        assert c["trace_id"] in tm and c["workflow_id"] in wf
        t = tm[c["trace_id"]]
        assert (c["workflow_id"], c["use_case_id"]) == (
            t["workflow_id"],
            t["use_case_id"],
        )
        assert c["use_case_id"] == wf[c["workflow_id"]][0]["id"]
    for t in traces:
        assert t["call_count"] == counts[t["trace_id"]]
        assert t["trace_count"] == 1
        if t.get("evidence_span_id"):
            assert cm[t["evidence_span_id"]]["trace_id"] == t["trace_id"]
    den = r["recorded_share_denominator_tokens"]
    assert den == (r["summary"]["recorded_input_tokens"] or 0) + (
        r["summary"]["recorded_output_tokens"] or 0
    )
    all_hierarchy_ids = []
    for u in r["business_use_cases"]:
        for w in u["workflows"]:
            ids = w["trace_ids"]
            all_hierarchy_ids += ids
            assert len(ids) == len(set(ids)) == w["trace_count"]
            assert all(tm[i]["workflow_id"] == w["id"] for i in ids)
            for k in SUM_FIELDS:
                assert sum(tm[i][k] or 0 for i in ids) == (w[k] or 0), (w["id"], k)
            for e in w["examples"]:
                assert len(e["excerpt"]) <= 241
                assert (
                    e["trace_id"] in ids
                    and cm[e["span_id"]]["trace_id"] == e["trace_id"]
                )
                assert cm[e["span_id"]]["call_index"] == e["call_index"]
            profile = w.get("activity_profile")
            if profile:
                assert profile["business_context"] in {
                    "supported",
                    "technical_only",
                    "unclear",
                }
                for activity in profile["observed_activities"]:
                    assert activity["evidence_trace_ids"] and set(
                        activity["evidence_trace_ids"]
                    ) <= set(ids)
            stats = w.get("usage_statistics")
            if stats:
                assert (
                    stats["recorded_tokens_per_complete_call"]["sample_count"]
                    == w["recorded_both_known_calls"]
                )
                for population in stats.values():
                    if not isinstance(population, dict):
                        continue
                    if population["sample_count"]:
                        assert (
                            0
                            <= population["p50"]
                            <= population["p90"]
                            <= population["p99"]
                            <= population["maximum"]
                        )
                        assert 0 <= population["mean"] <= population["maximum"]
                    else:
                        assert population["mean"] is None and population["p50"] is None
            if den:
                assert math.isclose(
                    w["share_of_recorded_tokens_percent"],
                    100
                    * (
                        (w["recorded_input_tokens"] or 0)
                        + (w["recorded_output_tokens"] or 0)
                    )
                    / den,
                    abs_tol=1e-9,
                )
        for k in SUM_FIELDS:
            assert sum(w[k] or 0 for w in u["workflows"]) == (u[k] or 0), (u["id"], k)
    assert Counter(all_hierarchy_ids) == Counter(tm.keys())
    for k in SUM_FIELDS:
        assert sum(u[k] or 0 for u in r["business_use_cases"]) == (
            r["summary"][k] or 0
        ), k
    assert len(calls) == r["summary"]["call_count"] == r["source"]["row_count"]
    assert len(traces) == r["summary"]["trace_count"] == r["source"]["trace_count"]
    if den:
        assert math.isclose(
            sum(u["share_of_recorded_tokens_percent"] for u in r["business_use_cases"]),
            100,
            abs_tol=1e-8,
        )
    if r.get("analytics"):
        for scenario in r["analytics"]["input_reduction_scenarios"]:
            avoided = (
                r["summary"]["recorded_input_tokens"]
                * scenario["assumed_input_reduction_fraction"]
            )
            assert math.isclose(avoided, scenario["hypothetical_tokens_avoided"])
            assert math.isclose(
                den - avoided, scenario["hypothetical_remaining_recorded_tokens"]
            )
        curve = r["analytics"]["concentration_curve"]
        assert all(
            a["share_of_recorded_tokens_percent"]
            <= b["share_of_recorded_tokens_percent"]
            for a, b in zip(curve, curve[1:])
        )
        assert math.isclose(curve[-1]["share_of_recorded_tokens_percent"], 100)
    if dataset:
        import pyarrow.parquet as pq

        p = Path(dataset)
        p = p / "traces.parquet" if p.is_dir() else p
        source = pq.read_table(
            p,
            columns=[
                "trace_id",
                "span_id",
                "call_index",
                "input_tokens",
                "output_tokens",
                "usage_basis",
            ],
        ).to_pylist()
        assert {s["span_id"] for s in source} == set(cm)
        assert len(source) == len(calls)
        for s in source:
            c = cm[s["span_id"]]
            assert (c["trace_id"], c["call_index"]) == (s["trace_id"], s["call_index"])
        for prefix, basis in [
            ("recorded", "source_reported"),
            ("estimated", "estimated_cl100k_base"),
        ]:
            for direction in ["input", "output"]:
                field = direction + "_tokens"
                total = sum(
                    s[field]
                    for s in source
                    if s["usage_basis"] == basis and s[field] is not None
                )
                assert total == (r["summary"][prefix + "_" + field] or 0)
        assert (
            sum(s["input_tokens"] is None or s["output_tokens"] is None for s in source)
            == r["summary"]["calls_with_unknown_usage"]
        )
        if r.get("analytics"):
            from statistics import median
            from collections import defaultdict

            samples = defaultdict(list)
            for s in source:
                if (
                    s["usage_basis"] == "source_reported"
                    and s["input_tokens"] is not None
                    and s["output_tokens"] is not None
                ):
                    samples[cm[s["span_id"]]["workflow_id"]].append(
                        s["input_tokens"] + s["output_tokens"]
                    )
            for wid, (_, w) in wf.items():
                values = samples[wid]
                actual = w["usage_statistics"]["recorded_tokens_per_complete_call"]
                assert actual["sample_count"] == len(values)
                if values:
                    assert actual["p50"] == median(values)
                    assert math.isclose(actual["mean"], sum(values) / len(values))
        # Verify exported excerpts against the original source record itself.
        from data import text_content, excerpt

        examples = {}
        for u in r["business_use_cases"]:
            for w in u["workflows"]:
                for e in w["examples"]:
                    examples.setdefault(e["span_id"], []).append(e)
        verified = 0
        for batch in pq.ParquetFile(p).iter_batches(
            batch_size=100,
            columns=[
                "span_id",
                "input_messages_json",
                "output_messages_json",
                "extra_json",
            ],
        ):
            for row in batch.to_pylist():
                if row["span_id"] not in examples:
                    continue
                candidates = []
                for field in ["input_messages_json", "output_messages_json"]:
                    messages = json.loads(row[field])
                    if not isinstance(messages, list):
                        messages = [messages]
                    candidates.extend(
                        (m.get("role", "unknown"), text_content(m).strip())
                        for m in messages
                        if isinstance(m, dict)
                    )
                instructions = json.loads(row["extra_json"]).get("system_instructions")
                if instructions:
                    candidates.append(("system", text_content(instructions).strip()))
                for e in examples[row["span_id"]]:
                    assert any(
                        role == e["role"] and excerpt(text[:4000], 240) == e["excerpt"]
                        for role, text in candidates
                    ), "Example does not match original record"
                    verified += 1
        assert verified == sum(len(v) for v in examples.values())
    return {
        "status": "PASS",
        "calls": len(calls),
        "traces": len(traces),
        "workflows": len(wf),
        "source_reconciled": bool(dataset),
    }


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--output", default="output")
    p.add_argument("--dataset")
    a = p.parse_args()
    print(json.dumps(validate(a.output, a.dataset), indent=2))
