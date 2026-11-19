"""Deterministic source adapter. No semantic inference occurs here."""

from __future__ import annotations
import hashlib
import json
import re
from collections import Counter
from pathlib import Path
import pyarrow.parquet as pq

VERSION = "adapter-1"
NUMERIC = [
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


def dumps(value):
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), allow_nan=False)


def atomic_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(dumps(value), encoding="utf-8")
    temp.replace(path)


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def empty_metrics():
    return dict.fromkeys(NUMERIC, 0)


def add_call(m, row):
    m["call_count"] += 1
    basis = row["usage_basis"]
    a, b = row["input_tokens"], row["output_tokens"]
    for value in (a, b):
        if value is not None and (
            isinstance(value, bool) or not isinstance(value, int) or value < 0
        ):
            raise ValueError("Invalid token counter; source must be reviewed")
    m["input_unknown_calls"] += a is None
    m["output_unknown_calls"] += b is None
    m["calls_with_unknown_usage"] += a is None or b is None
    if basis == "source_reported":
        m["source_reported_calls"] += 1
        prefix = "recorded"
        m["recorded_both_known_calls"] += a is not None and b is not None
    elif basis == "estimated_cl100k_base":
        m["estimated_calls"] += 1
        prefix = "estimated"
    elif basis == "unknown":
        m["unknown_basis_calls"] += 1
        # Numeric values with unknown provenance must never become recorded usage.
        if a is not None or b is not None:
            raise ValueError(
                "Unknown basis contains numeric usage: explicit provenance mapping required"
            )
        return
    else:
        raise ValueError("Unrecognized usage provenance")
    for direction, value in [("input", a), ("output", b)]:
        if value is not None:
            m[f"{prefix}_{direction}_tokens"] += value
            m[f"{prefix}_{direction}_known_calls"] += 1


def merge_metrics(items):
    out = empty_metrics()
    for m in items:
        for k in NUMERIC:
            out[k] += m[k]
    return out


def public_metrics(m, denominator):
    out = dict(m)
    for basis in ["recorded", "estimated"]:
        for direction in ["input", "output"]:
            if not m[f"{basis}_{direction}_known_calls"]:
                out[f"{basis}_{direction}_tokens"] = None
        known = m[f"{basis}_input_known_calls"] + m[f"{basis}_output_known_calls"]
        out[f"{basis}_total_tokens"] = (
            (m[f"{basis}_input_tokens"] + m[f"{basis}_output_tokens"])
            if known
            else None
        )
    observed = m["recorded_input_tokens"] + m["recorded_output_tokens"]
    out["share_of_recorded_tokens_percent"] = (
        100 * observed / denominator if denominator else None
    )
    out["recorded_complete_call_coverage_percent"] = (
        100 * m["recorded_both_known_calls"] / m["call_count"]
        if m["call_count"]
        else None
    )
    return out


def text_content(value, depth=0):
    """Read variable released message formats, excluding hidden reasoning."""
    if depth > 8 or value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return "\n".join(text_content(v, depth + 1) for v in value)
    if isinstance(value, dict):
        if str(value.get("type", "")).lower() in {
            "thinking",
            "reasoning",
            "redacted_thinking",
        }:
            return ""
        chunks = []
        for field in ("text", "content", "parts", "result", "arguments"):
            if field in value:
                item = value[field]
                if field == "arguments" and isinstance(item, dict):
                    chunks.append(dumps(item))
                else:
                    chunks.append(text_content(item, depth + 1))
        return "\n".join(chunks)
    return ""


def tool_names(value):
    names = set()
    if isinstance(value, list):
        for v in value:
            names.update(tool_names(v))
    elif isinstance(value, dict):
        if (
            "arguments" in value
            or "input" in value
            or value.get("type") in ("tool_call", "function", "tool_use")
        ) and isinstance(value.get("name"), str):
            names.add(value["name"][:100])
        for k in ("tool_calls", "function", "parts", "content"):
            if k in value:
                names.update(tool_names(value[k]))
    return names


def excerpt(text, limit=240):
    text = re.sub(r"\s+", " ", text).strip()
    # Additional conservative redaction for exported examples.
    text = re.sub(
        r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b", "[EMAIL]", text
    )
    text = re.sub(r"\b(?:sk-|ghp_|github_pat_)[A-Za-z0-9_-]{12,}\b", "[SECRET]", text)
    return text[:limit] + ("…" if len(text) > limit else "")


def _select_events(events, limit):
    if len(events) <= limit:
        return events
    indices = {0, len(events) - 1}
    for i in range(limit):
        indices.add(round(i * (len(events) - 1) / max(1, limit - 1)))
    return [events[i] for i in sorted(indices)][:limit]


def make_packet(trace, expanded=False):
    users = [e for e in trace["events"] if e["role"] == "user"]
    outputs = [e for e in trace["events"] if e["role"] == "assistant"]
    systems = [e for e in trace["events"] if e["role"] == "system"]
    selected = (
        _select_events(users, 5 if expanded else 3)
        + _select_events(outputs, 4 if expanded else 2)
        + _select_events(systems, 1)
    )
    # Evidence references are actual source spans, never a fabricated ID.
    selected.sort(key=lambda e: (e["call_index"], e["order"]))
    cap = 1600 if expanded else 850
    evidence = [
        {k: e[k] for k in ["span_id", "call_index", "role"]}
        | {"text": e["text"][:cap], "truncated": e["original_chars"] > cap}
        for e in selected
    ]
    return {
        "trace_id": trace["trace_id"],
        "call_count": len(trace["calls"]),
        "observed_tool_names": sorted(trace["tools"])[:24],
        "evidence": evidence,
        "distinct_messages_observed": trace["distinct_messages"],
        "packet_is_excerpted": True,
    }


def prepare(dataset, cache):
    dataset = Path(dataset)
    path = dataset / "traces.parquet" if dataset.is_dir() else dataset
    cache = Path(cache)
    cache.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            digest.update(chunk)
    fingerprint = digest.hexdigest()
    manifest_path = cache / "manifest.json"
    if manifest_path.exists():
        manifest = read_json(manifest_path)
        if (
            manifest.get("sha256") == fingerprint
            and manifest.get("adapter_version") == VERSION
            and (cache / "traces.json").exists()
        ):
            return manifest
        if manifest.get("sha256") != fingerprint and any(
            (cache / name).exists() for name in ["taxonomy.json", "assignments.json"]
        ):
            raise ValueError(
                "This cache belongs to another dataset. Use a fresh --cache directory."
            )
    traces = {}
    spans = set()
    counts = Counter()
    baseline = empty_metrics()
    session_usage = {}
    anomalies = []
    p = pq.ParquetFile(path)
    for batch in p.iter_batches(batch_size=100):
        for r in batch.to_pylist():
            tid = r["trace_id"]
            sid = r["span_id"]
            if not tid or not sid or sid in spans:
                raise ValueError("Missing or duplicate original IDs")
            spans.add(sid)
            add_call(baseline, r)
            counts[r["usage_basis"]] += 1
            if tid not in traces:
                traces[tid] = {
                    "trace_id": tid,
                    "calls": [],
                    "events": [],
                    "tools": set(),
                    "seen": set(),
                    "metrics": empty_metrics(),
                    "models": set(),
                    "semantic_hash": hashlib.sha256(),
                    "distinct_messages": 0,
                }
            t = traces[tid]
            add_call(t["metrics"], r)
            t["models"].add(r["model"])
            call = {
                k: r[k]
                for k in [
                    "span_id",
                    "call_index",
                    "input_tokens",
                    "output_tokens",
                    "usage_basis",
                ]
            }
            t["calls"].append(call)
            for name in ["input_messages_json", "output_messages_json"]:
                messages = json.loads(r[name])
                if not isinstance(messages, list):
                    messages = [messages]
                t["semantic_hash"].update(dumps(messages).encode())
                for order, m in enumerate(messages):
                    if not isinstance(m, dict):
                        continue
                    role = m.get("role", "unknown")
                    t["tools"].update(tool_names(m))
                    if role not in ("user", "assistant", "system"):
                        continue
                    txt = text_content(m).strip()
                    if not txt:
                        continue
                    h = hashlib.sha256((role + "\0" + txt).encode()).digest()
                    if h in t["seen"]:
                        continue
                    t["seen"].add(h)
                    t["distinct_messages"] += 1
                    # Keep all distinct user tasks; cap stored samples from other roles.
                    ev = {
                        "span_id": sid,
                        "call_index": r["call_index"],
                        "role": role,
                        "text": txt[:4000],
                        "original_chars": len(txt),
                        "order": order,
                    }
                    t["events"].append(ev)
            extra = json.loads(r["extra_json"])
            instructions = extra.get("system_instructions")
            if instructions and not any(e["role"] == "system" for e in t["events"]):
                txt = (
                    text_content(instructions)
                    if not isinstance(instructions, str)
                    else instructions
                )
                if txt:
                    t["events"].append(
                        {
                            "span_id": sid,
                            "call_index": r["call_index"],
                            "role": "system",
                            "text": txt[:4000],
                            "original_chars": len(txt),
                            "order": -1,
                        }
                    )
            usage = extra.get("source_reported_session_usage")
            if usage is not None:
                if tid in session_usage and session_usage[tid] != usage:
                    anomalies.append("conflicting_session_usage")
                session_usage[tid] = usage
            if r["session_call_count"] != 0:
                t["declared_count"] = r["session_call_count"]
    for t in traces.values():
        t["calls"].sort(key=lambda c: c["call_index"])
        t["events"].sort(key=lambda e: (e["call_index"], e["order"]))
        if len({c["call_index"] for c in t["calls"]}) != len(t["calls"]):
            raise ValueError("Duplicate call_index within trace")
        if t.get("declared_count") != len(t["calls"]):
            anomalies.append("declared_session_count_mismatch")
        t["metrics"]["trace_count"] = 1
        t["tools"] = sorted(t["tools"])
        t["models"] = sorted(t["models"])
        t["semantic_hash"] = t["semantic_hash"].hexdigest()
        t.pop("seen")
        t["packet"] = make_packet(t)
    baseline["trace_count"] = len(traces)
    session_summary = {
        "trace_count": len(session_usage),
        "input_tokens": sum(
            v.get("prompt_tokens") or 0 for v in session_usage.values()
        ),
        "output_tokens": sum(
            v.get("completion_tokens") or 0 for v in session_usage.values()
        ),
        "included_in_per_call_totals": False,
    }
    manifest = {
        "adapter_version": VERSION,
        "sha256": fingerprint,
        "row_count": len(spans),
        "trace_count": len(traces),
        "usage_basis_counts": dict(counts),
        "baseline": baseline,
        "session_usage_diagnostic": session_summary,
        "anomalies": dict(Counter(anomalies)),
    }
    atomic_json(cache / "traces.json", traces)
    atomic_json(manifest_path, manifest)
    return manifest
