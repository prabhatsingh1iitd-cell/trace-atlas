"""Create and verify the assessment ZIP using an explicit file allowlist."""

import argparse
import json
import re
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--student-id", required=True)
    p.add_argument("--root", default=".")
    p.add_argument("--dataset")
    a = p.parse_args()
    if not re.fullmatch(r"[A-Za-z0-9_-]+", a.student_id):
        raise ValueError("Invalid student ID for filename")
    root = Path(a.root).resolve()
    result = json.loads((root / "output/results.json").read_text())
    quality = json.loads((root / "output/quality.json").read_text())
    assert result["student_id"] == a.student_id and result["variant"] == "02"
    audit = result["classification"]["audit"]
    unknown = result["classification"]["unresolved"]["trace_count"]
    status = f"All {result['summary']['call_count']:,} calls and {result['summary']['trace_count']:,} traces are represented; {unknown:,} traces have an unresolved semantic label."
    if quality["status"] != "complete":
        status += " INCOMPLETE: inference has not finished for all traces; pending or failed cases are explicitly unresolved."
    readme = f"""# Trace Atlas — Variant 02

Student ID: {a.student_id}

{status}

The pipeline preserves original trace/span IDs and source call order. Local TF-IDF and mini-batch clustering select diverse discovery examples. Only Hyde's `hyde/glm-5.3-flash` discovers the taxonomy, assigns traces, describes activities, and audits expanded evidence. Calls inherit their trace's primary workflow; no label propagation is used.

Uncertain traces receive a fuller-context review; promotion requires two agreeing, high-confidence GLM judgments with source evidence. Follow-up audit history is retained. Usage Lab adds provenance-specific distributions and explicitly hypothetical input-reduction scenarios.

Python computes all counts and usage. Recorded shares use source-reported input plus output tokens only. Supplied cl100k_base estimates, unknown values, and separately reported session totals remain distinct. Cache subtotals are not added again. These assessment sources are not necessarily production traffic.

## View saved results

From the extracted folder, run `python3 code/serve.py`, then open http://127.0.0.1:8765. No API key, dataset, or third-party packages are needed to view results. Alternatively open `code/viewer.html` and select the output JSON/JSONL files.

## Validate or reproduce

`python3 code/validate.py --output output`

For mining (tested with Python 3.13), install `code/requirements.txt`, set `HYDE_API_KEY` locally, then run:

`python3 code/main.py all --dataset /path/to/assigned/dataset --student-id {a.student_id} --concurrency 8`

Add `--dataset /path/to/assigned/dataset` to validation for independent source reconciliation. Inference caches are local and excluded from this submission.

Bounded excerpts can omit context. Confidence is qualitative; same-model audit agreement is not ground-truth accuracy. Exact assignments, examples, coverage, audit results, and usage provenance are in `output/`. Source notices are retained in `code/SOURCES_AND_NOTICES.txt`.
"""
    assert len(readme.split()) <= 300, len(readme.split())
    (root / "README.md").write_text(readme)
    validation = subprocess.run(
        [
            sys.executable,
            str(root / "code/validate.py"),
            "--output",
            str(root / "output"),
        ]
        + (["--dataset", str(Path(a.dataset).resolve())] if a.dataset else []),
        capture_output=True,
        text=True,
        check=True,
    )
    report = json.loads(validation.stdout)
    (root / "output/validation.json").write_text(
        json.dumps(report, separators=(",", ":"))
    )
    allowed_code = {".py", ".html", ".css", ".js", ".txt"}
    paths = [root / "README.md"] + [
        p
        for p in (root / "code").rglob("*")
        if p.is_file() and p.suffix in allowed_code and "__pycache__" not in p.parts
    ]
    names = [
        "results.json",
        "quality.json",
        "trace_assignments.jsonl",
        "call_assignments.jsonl",
        "validation.json",
    ]
    paths += [root / "output" / n for n in names]
    target = root / (a.student_id + "_V02.zip")
    temp = target.with_suffix(".zip.tmp")
    with zipfile.ZipFile(
        temp, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9
    ) as z:
        for path in sorted(paths):
            z.write(path, path.relative_to(root).as_posix())
    assert temp.stat().st_size < 5_000_000, "Archive exceeds 5 MB"
    with zipfile.ZipFile(temp) as z:
        assert z.testzip() is None
        assert all(
            n.split("/")[0] in {"README.md", "code", "output"} for n in z.namelist()
        )
        assert not any(
            part in {".env", ".venv", "__pycache__", "cache", "logs", ".git"}
            for n in z.namelist()
            for part in n.split("/")
        )
        with tempfile.TemporaryDirectory(prefix="hyde-submission-check-") as folder:
            z.extractall(folder)
            subprocess.run(
                [
                    sys.executable,
                    str(Path(folder) / "code/validate.py"),
                    "--output",
                    str(Path(folder) / "output"),
                ],
                check=True,
                capture_output=True,
                text=True,
            )
    temp.replace(target)
    print(
        json.dumps(
            {
                "filename": target.name,
                "bytes": target.stat().st_size,
                "readme_words": len(readme.split()),
                "archive_integrity": "PASS",
                "fresh_extraction_validation": "PASS",
                "semantic_status": quality["status"],
                "unresolved_traces": unknown,
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
