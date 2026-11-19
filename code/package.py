"""Create a validated offline viewer bundle from explicitly selected result files."""

import argparse
import json
import tempfile
import zipfile
from pathlib import Path

from validate import validate

RESULT_FILES = ("results.json", "quality.json", "trace_assignments.jsonl", "call_assignments.jsonl")
VIEWER_FILES = ("viewer.html", "viewer.css", "viewer.js", "serve.py", "validate.py", "SOURCES_AND_NOTICES.txt")


def package(output, destination):
    output = Path(output).resolve()
    target = Path(destination).resolve()
    if target.suffix != ".zip":
        raise ValueError("Destination must end in .zip")
    report = validate(output)
    code = Path(__file__).resolve().parent
    readme = """# Trace Atlas — offline explorer

Run `python3 code/serve.py --output output`, then open http://127.0.0.1:8765.
No API key or third-party packages are required to view these results.
Validate with `python3 code/validate.py --output output`.

Source: https://github.com/prabhatsingh1iitd-cell/trace-atlas
Review result provenance and code/SOURCES_AND_NOTICES.txt before redistributing.
"""
    target.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="trace-atlas-bundle-", dir=target.parent) as tmp:
        archive = Path(tmp) / "bundle.zip"
        with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as z:
            z.writestr("README.md", readme)
            for name in VIEWER_FILES:
                z.write(code / name, "code/" + name)
            for name in RESULT_FILES:
                z.write(output / name, "output/" + name)
            z.writestr("output/validation.json", json.dumps(report))
        with zipfile.ZipFile(archive) as z:
            if z.testzip() is not None:
                raise ValueError("Archive integrity check failed")
            extracted = Path(tmp) / "extracted"
            z.extractall(extracted)
            validate(extracted / "output")
        archive.replace(target)
    return {"filename": str(target), "bytes": target.stat().st_size, "validation": report}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", default="output")
    parser.add_argument("--destination", default="trace-atlas.zip")
    args = parser.parse_args()
    print(json.dumps(package(args.output, args.destination), indent=2))
