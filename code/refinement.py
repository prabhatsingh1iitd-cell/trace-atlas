"""Conservative GLM-only review of unresolved traces with fuller source context."""

import asyncio
import hashlib
import json
from pathlib import Path
import pyarrow.parquet as pq
from data import atomic_json, read_json, dumps, text_content
from mining import CLASSIFY, validate_assignments, assignment_schema


def spread(items, n):
    if len(items) <= n:
        return items
    return [items[round(i * (len(items) - 1) / (n - 1))] for i in range(n)]


def fuller_packets(dataset, selected, traces):
    path = Path(dataset)
    path = path / "traces.parquet" if path.is_dir() else path
    events = {i: [] for i in selected}
    seen = {i: set() for i in selected}
    for batch in pq.ParquetFile(path).iter_batches(
        batch_size=100,
        columns=[
            "trace_id",
            "span_id",
            "call_index",
            "input_messages_json",
            "output_messages_json",
            "extra_json",
        ],
    ):
        for r in batch.to_pylist():
            tid = r["trace_id"]
            if tid not in events:
                continue
            for field in ["input_messages_json", "output_messages_json"]:
                messages = json.loads(r[field])
                messages = messages if isinstance(messages, list) else [messages]
                for m in messages:
                    if not isinstance(m, dict) or m.get("role") not in (
                        "user",
                        "assistant",
                        "system",
                    ):
                        continue
                    txt = text_content(m).strip()
                    if not txt:
                        continue
                    digest = hashlib.sha256((m["role"] + "\0" + txt).encode()).digest()
                    if digest in seen[tid]:
                        continue
                    seen[tid].add(digest)
                    clipped = (
                        txt
                        if len(txt) <= 4200
                        else txt[:3000] + "\n[...middle omitted...]\n" + txt[-1200:]
                    )
                    events[tid].append(
                        {
                            "role": m["role"],
                            "span_id": r["span_id"],
                            "call_index": r["call_index"],
                            "text": clipped,
                            "truncated": len(txt) > 4200,
                        }
                    )
    packets = {}
    for tid, items in events.items():
        items.sort(key=lambda e: e["call_index"])
        chosen = (
            spread([e for e in items if e["role"] == "user"], 5)
            + spread([e for e in items if e["role"] == "assistant"], 3)
            + spread([e for e in items if e["role"] == "system"], 1)
        )
        chosen.sort(key=lambda e: e["call_index"])
        budget = 22000
        for e in chosen:
            cap = min(4200, max(1000, budget // max(1, len(chosen))))
            if len(e["text"]) > cap:
                e["text"] = (
                    e["text"][: cap * 3 // 4]
                    + "\n[...omitted...]\n"
                    + e["text"][-cap // 4 :]
                )
                e["truncated"] = True
        packets[tid] = {
            "trace_id": tid,
            "call_count": len(traces[tid]["calls"]),
            "observed_tool_names": traces[tid]["tools"][:30],
            "evidence": chosen,
            "packet_is_excerpted": True,
            "review_scope": "Broader unique user and assistant messages, spread across the trace; long messages include beginning and end.",
        }
    return packets


async def refine(dataset, traces, taxonomy, assignments, cache, glm):
    cache = Path(cache)
    report_path = cache / "refinement.json"
    if report_path.exists():
        return read_json(report_path)
    ids = sorted(i for i, a in assignments.items() if a["workflow_id"] == "WF00")
    packets = fuller_packets(dataset, set(ids), traces)
    atomic_json(cache / "fuller_review_packets.json", packets)
    adapted = {i: {**traces[i], "packet": packets[i]} for i in ids}
    results = {}
    done = 0

    async def work(tid):
        nonlocal done
        judgments = []
        prompts = [
            CLASSIFY
            + " Fuller-context review: assess the entire observed objective. Preserve WF00 when missing business context, competing objectives, or a taxonomy gap prevents a supported match.",
            CLASSIFY
            + " Independent fuller-context verification: do not assume any prior label. Distinguish a supported business/workflow objective from a merely plausible interpretation. Abstain with WF00 if the evidence does not support the category.",
        ]
        for prompt in prompts:
            response = await glm.request(
                prompt,
                {"taxonomy": taxonomy, "traces": [packets[tid]]},
                4500,
                schema=assignment_schema([tid], adapted, taxonomy),
            )
            valid = validate_assignments(response, [tid], adapted, taxonomy)
            judgments.append(valid.get(tid))
        first, second = judgments
        accepted = bool(
            first
            and second
            and first["workflow_id"] == second["workflow_id"]
            and first["workflow_id"] != "WF00"
            and first["confidence"] == second["confidence"] == "high"
            and first["evidence_span_id"]
            and second["evidence_span_id"]
        )
        old = dict(assignments[tid])
        if accepted:
            assignments[tid] = {
                **second,
                "method": "glm_expanded_review",
                "fuller_context_reviewed": True,
                "review_agreement": True,
            }
            # Historical audit flags refer to the previous classification version.
            if old.get("audit_checked"):
                assignments[tid]["prior_audit_checked"] = True
        else:
            assignments[tid]["fuller_context_reviewed"] = True
            assignments[tid]["review_agreement"] = bool(
                first and second and first["workflow_id"] == second["workflow_id"]
            )
        results[tid] = {
            "trace_id": tid,
            "original_workflow_id": "WF00",
            "review_workflow_id": assignments[tid]["workflow_id"],
            "changed": accepted,
            "judgments_valid": bool(first and second),
            "judgments_agreed": bool(
                first and second and first["workflow_id"] == second["workflow_id"]
            ),
            "evidence_characters": sum(
                len(e["text"]) for e in packets[tid]["evidence"]
            ),
        }
        done += 1
        if done % 10 == 0 or done == len(ids):
            print(
                dumps(
                    {
                        "phase": "fuller_context_review",
                        "reviewed": done,
                        "total": len(ids),
                        "resolved": sum(v["changed"] for v in results.values()),
                    }
                ),
                flush=True,
            )

    await asyncio.gather(*(work(i) for i in ids))
    changed = sum(r["changed"] for r in results.values())
    report = {
        "stage": "before_followup_audit",
        "reviewed_trace_count": len(ids),
        "resolved_trace_count": changed,
        "unresolved_before_followup_audit_trace_count": sum(
            a["workflow_id"] == "WF00" for a in assignments.values()
        ),
        "policy": "Replace an unresolved label only when two GLM judgments on broader source excerpts agree on the same supported workflow, both rate confidence high, and both cite valid source spans. Same-model agreement is not independent accuracy.",
        "traces": [results[i] for i in sorted(results)],
    }
    if changed and (cache / "audit.json").exists():
        history_path = cache / "audit_history.json"
        history = read_json(history_path) if history_path.exists() else []
        previous = read_json(cache / "audit.json")
        previous["revision_note"] = (
            "Audit before the fuller-context review of unresolved traces."
        )
        history.append(previous)
        atomic_json(history_path, history)
    atomic_json(cache / "assignments.json", assignments)
    atomic_json(report_path, report)
    return report
