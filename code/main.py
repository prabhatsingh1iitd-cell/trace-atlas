"""CLI: prepare, discover, classify, audit, export, or all."""

import argparse
import asyncio
import os
from pathlib import Path

os.environ.setdefault("LOKY_MAX_CPU_COUNT", "4")
from data import prepare, read_json, dumps, atomic_json
from glm import GLM, probe, probe_schema
from mining import discover, classify, audit


async def run(args):
    cache = Path(args.cache)
    if args.stage == "probe":
        await probe(cache)
        return
    if args.stage == "probe-schema":
        await probe_schema(cache)
        return
    manifest = prepare(args.dataset, cache)
    print(
        dumps(
            {
                "phase": "prepared",
                "calls": manifest["row_count"],
                "traces": manifest["trace_count"],
            }
        ),
        flush=True,
    )
    if args.stage == "prepare":
        return
    traces = read_json(cache / "traces.json")
    if args.stage == "export":
        from reporting import export

        export(traces, manifest, cache, args.output, args.student_id)
        return
    if not (cache / "glm_capabilities.json").exists():
        await probe(cache)
    if "json_schema" not in read_json(cache / "glm_capabilities.json"):
        await probe_schema(cache)
    glm = GLM(cache, args.concurrency)
    try:
        taxonomy = await discover(traces, cache, glm)
        if args.stage == "discover":
            return
        assignments = await classify(traces, taxonomy, cache, glm, args.batch_size)
        if args.stage in ("refine", "all"):
            from refinement import refine

            await refine(args.dataset, traces, taxonomy, assignments, cache, glm)
        if args.stage in ("audit", "refine", "all"):
            await audit(traces, taxonomy, assignments, cache, glm)
        if args.stage in ("audit", "audit-complete", "refine", "all"):
            from audit_completion import complete_audit

            await complete_audit(traces, taxonomy, assignments, cache, glm)
        if args.stage in ("profiles", "audit-complete", "refine", "all"):
            from profiles import build_profiles

            await build_profiles(traces, taxonomy, assignments, cache, glm)
        from reporting import export

        export(traces, manifest, cache, args.output, args.student_id)
    finally:
        atomic_json(cache / "last_request_stats.json", glm.stats)
        print(dumps({"phase": "api_stats", **glm.stats}), flush=True)
        await glm.close()


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument(
        "stage",
        choices=[
            "prepare",
            "probe",
            "probe-schema",
            "discover",
            "classify",
            "audit",
            "audit-complete",
            "refine",
            "profiles",
            "export",
            "all",
        ],
    )
    p.add_argument("--dataset", required=True)
    p.add_argument("--student-id", required=True)
    p.add_argument("--cache", default="cache")
    p.add_argument("--output", default="output")
    p.add_argument("--concurrency", type=int, default=3)
    p.add_argument("--batch-size", type=int, default=10)
    asyncio.run(run(p.parse_args()))
