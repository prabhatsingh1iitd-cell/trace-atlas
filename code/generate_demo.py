"""Build the public, fictional demo with the real adapter/exporter; no model calls."""

import argparse
import hashlib
import json
import tempfile
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

from data import atomic_json, dumps, prepare, read_json
from mining import UNKNOWN
from reporting import export
from validate import validate

DEMO_NOTE = (
    "Synthetic demo: fictional traces, hand-authored labels and illustrative token "
    "counters. No customer records, external dataset excerpts or model calls."
)


def generate(output):
    output = Path(output)
    scenarios = [
        ("Customer support", "Order status lookup", "Find a fictional order, inspect its shipment status, and draft a reply.",
         ["Look up demo order {n} and summarize its shipping status.", "Check the fictional shipment timeline for demo order {n}.", "Draft a concise status reply for demo order {n}."], "lookup_order"),
        ("Engineering", "Code review", "Inspect a fictional patch and outline a regression check.",
         ["Review demo patch {n} for a missing empty-list check.", "Describe a unit test for the empty-list branch in demo patch {n}.", "Summarize review findings for fictional patch {n}."], "inspect_patch"),
        ("Research", "Specification comparison", "Compare invented product specifications and summarize differences.",
         ["Compare the invented battery specifications of demo devices {n}A and {n}B.", "List differences from the supplied fictional specification table {n}.", "Summarize the tradeoffs in fictional comparison {n}."], "compare_specs"),
    ]
    use_cases = []
    for i, (name, workflow, description, _, _) in enumerate(scenarios, 1):
        use_cases.append({
            "id": f"UC{i:02}", "name": name, "description": description,
            "workflows": [{"id": f"WF{i:02}", "name": workflow,
                           "description": description, "inclusion": "Fictional tasks in this scenario.",
                           "exclusion": "Other scenarios or insufficient evidence."}],
        })
    use_cases.append(UNKNOWN)
    rows, assignments, profiles = [], {}, {}
    for n in range(1, 13):
        tid = f"demo-trace-{n:03}"
        group = min((n - 1) // 4, 2)
        scenario = scenarios[group]
        unresolved = n == 12
        wid = "WF00" if unresolved else f"WF{group + 1:02}"
        uid = "UC00" if unresolved else f"UC{group + 1:02}"
        for step in range(3):
            basis = "unknown" if unresolved else "estimated_cl100k_base" if n in (4, 8) else "source_reported"
            text = "Continue the fictional task; no goal was provided." if unresolved else scenario[3][step].format(n=n)
            rows.append({
                "trace_id": tid, "span_id": f"{tid}-call-{step + 1}", "call_index": step,
                "model": "fictional-demo-model", "usage_basis": basis,
                "input_tokens": None if basis == "unknown" else 180 + n * n * 17 + step * 53,
                "output_tokens": None if basis == "unknown" else 60 + n * 11 + step * 19,
                "input_messages_json": dumps([{"role": "user", "content": text}]),
                "output_messages_json": dumps([{"role": "assistant", "content": "Illustrative response for this fictional task.", "tool_calls": [{"function": {"name": scenario[4], "arguments": "{}"}}]}]),
                "extra_json": "{}", "session_call_count": 3,
            })
        assignments[tid] = {
            "trace_id": tid, "use_case_id": uid, "workflow_id": wid,
            "confidence": "low" if unresolved else "high",
            "evidence_span_id": f"{tid}-call-1",
            "explanation": "Hand-authored demo abstention: the fictional task has no stated goal." if unresolved else "Hand-authored demo label matches the fictional task description; not a model judgment.",
            "method": "hand_authored_demo", "status": "demo_unresolved" if unresolved else "demo_label",
            "taxonomy_version": "synthetic-demo-v1",
        }
    for i, scenario in enumerate(scenarios, 1):
        ids = [tid for tid, a in assignments.items() if a["workflow_id"] == f"WF{i:02}"]
        profiles[f"WF{i:02}"] = {
            "business_context": "supported", "scope_note": "Fictional scenario with hand-authored activity labels.",
            "observed_activities": [{"name": scenario[1], "evidence_trace_ids": ids}],
        }
    with tempfile.TemporaryDirectory(prefix="trace-atlas-demo-") as tmp:
        root = Path(tmp)
        source = root / "traces.parquet"
        pq.write_table(pa.Table.from_pylist(rows), source)
        cache = root / "cache"
        manifest = prepare(source, cache)
        # Fingerprint canonical authored records, independent of Parquet encoder metadata.
        manifest["sha256"] = hashlib.sha256(dumps(rows).encode()).hexdigest()
        atomic_json(cache / "taxonomy.json", {"version": "synthetic-demo-v1", "discovery_trace_count": 0, "business_use_cases": use_cases})
        atomic_json(cache / "assignments.json", assignments)
        atomic_json(cache / "workflow_profiles.json", profiles)
        atomic_json(cache / "audit.json", {"status": "not_run", "validated_sample_size": 0, "initial_agreement_percent": None, "adjudicated_count": 0, "interpretation": "No model audit was run. Labels are authored for demonstration only."})
        result = export(read_json(cache / "traces.json"), manifest, cache, output, "Trace Atlas · Synthetic demo")
        result["demo"] = True
        result["generated_at"] = "2026-11-19T00:00:00+00:00"
        result["source"].update(filename="synthetic-records.json", fingerprint_basis="SHA-256 of canonical synthetic-records.json bytes")
        result["classification"]["model"] = "Hand-authored demo; no inference"
        result["notes"] = [DEMO_NOTE, *result["notes"][:3], "Confidence values illustrate the interface; they do not report calibrated probabilities or model accuracy.", "Input reduction scenarios are hypothetical and do not establish achievable savings."]
        atomic_json(output / "results.json", result)
        quality = read_json(output / "quality.json")
        quality["semantic_limitations"] = [DEMO_NOTE]
        quality["pipeline_usage_note"] = "No provider requests were made to create this demo."
        atomic_json(output / "quality.json", quality)
        atomic_json(output / "synthetic-records.json", rows)
        atomic_json(output / "validation.json", validate(output, source))
        (output / "README.md").write_text("# Synthetic demo\n\n" + DEMO_NOTE + "\n\n12 traces, 36 calls, three named workflows and one unresolved workflow.\nRegenerate with `python code/generate_demo.py` after installing pipeline dependencies.\nThe fixed generated_at timestamp identifies this demo revision, not an inference run.\n", encoding="utf-8")
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", default=str(Path(__file__).resolve().parent.parent / "demo"))
    args = parser.parse_args()
    generate(args.output)
