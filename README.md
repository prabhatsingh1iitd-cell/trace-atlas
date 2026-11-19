# Trace Atlas

**Understand what your AI workflows do—and where their tokens go.**

Trace Atlas turns call-level LLM logs into an inspectable map of use cases, workflows, traces and individual calls. It combines model-assisted workflow discovery with deterministic usage accounting, so you can investigate expensive workflows without mixing measured counters, estimates and unknown values.

[![Checks](https://github.com/prabhatsingh1iitd-cell/trace-atlas/actions/workflows/checks.yml/badge.svg)](https://github.com/prabhatsingh1iitd-cell/trace-atlas/actions/workflows/checks.yml)

## Try the demo

Only Python 3.10+ and a browser are needed. No API key or third-party Python packages are required to explore the included results.

```sh
git clone https://github.com/prabhatsingh1iitd-cell/trace-atlas.git
cd trace-atlas
python3 code/serve.py
```

Open **http://127.0.0.1:8765**. The bundled demo contains **12 fictional traces and 36 calls** across support, engineering, research and an unresolved case. Labels are hand-authored and token counters are illustrative. It demonstrates the explorer and accounting—not model accuracy, customer adoption or measured cost savings.

1. Compare workflows by recorded tokens or call count in **Overview**.
2. Open **Use cases & workflows** to inspect activities and supporting excerpts.
3. Use **Usage lab** to examine concentration and explicitly hypothetical input-reduction scenarios.
4. Filter **Trace explorer**, open a trace and inspect the original call sequence.
5. Check **Method & quality** for coverage, provenance and interpretation limits.

The viewer runs locally, uses no external assets or analytics, and makes no model calls. It serves only the viewer and an explicit allowlist of result files. Use `--output /path/to/results` to inspect your own exports. You can also open `code/viewer.html` directly and select result files manually.

## What it does

- **Discover workflow structure.** Local TF-IDF and mini-batch clustering select diverse discovery examples; Hyde GLM discovers a taxonomy and assigns traces directly.
- **Follow evidence.** Use case → workflow → trace → span, with source IDs, call order, bounded excerpts and qualitative confidence retained.
- **Keep accounting reproducible.** Python computes rollups and distributions. Source-reported usage, tokenizer estimates and missing counters remain separate; session totals are never added twice.
- **Expose uncertainty.** Unsupported labels remain unresolved. Fuller-context review and same-model audits retain their history instead of hiding disagreements.
- **Explore usage.** Compare workflow intensity and concentration, filter individual traces, export results, and model hypothetical input reductions without claiming actual savings.

## Analyze your own traces

The analysis pipeline is tested with Python 3.13. It currently uses the Hyde `hyde/glm-5.3-flash` endpoint for semantic inference. Live analysis requires an account/key and may incur provider charges.

```sh
python3.13 -m venv .venv
source .venv/bin/activate
pip install -r code/requirements.txt
cp .env.example .env
# Set HYDE_API_KEY in .env locally.
python code/main.py all --dataset /path/to/traces.parquet \
  --project-name "My workflow analysis" --cache cache/my-analysis --output output/my-analysis
python code/validate.py --output output/my-analysis --dataset /path/to/traces.parquet
python code/serve.py --output output/my-analysis
```

See the [input format](docs/INPUT-FORMAT.md) for required Parquet fields. Use a separate cache directory for each dataset. Raw datasets, local outputs, inference caches and credentials are excluded from Git.

The stages `prepare`, `discover`, `classify`, `refine`, `audit`, `audit-complete`, `profiles` and `export` can also be run separately. `probe` and `probe-schema` check the provider's capabilities. Results use `project_name`; the viewer still opens earlier exports that lack that field.

## Architecture

```text
Parquet call records
    → source adapter, provenance and bounded evidence packets
    → diverse discovery sample → GLM taxonomy → direct trace assignments
    → fuller-context review and consistency audit
    → deterministic rollups + reconciliation
    → JSON/JSONL exports → local browser explorer
```

| Component | Responsibility |
| --- | --- |
| `code/data.py` | Validate IDs and usage provenance; reconstruct ordered traces |
| `code/mining.py`, `code/glm.py` | Discovery, classification and provider boundary |
| `code/refinement.py`, `code/audit_completion.py` | Expanded evidence and consistency review |
| `code/reporting.py`, `code/analytics.py` | Hierarchy rollups, distributions and concentration |
| `code/validate.py` | Independent export checks and optional source reconciliation |
| `code/viewer.*`, `code/serve.py` | Local interactive explorer |

## Checks and demo provenance

```sh
python3 code/validate.py --output demo
# With pipeline dependencies installed:
python -m unittest discover -s code/tests -v
python code/generate_demo.py --output /tmp/trace-atlas-demo
```

The generator creates fictional source records in a temporary directory, runs the real adapter and exporter, and validates the result against those records. It makes no model calls and never reads the private development dataset. The committed demo is reproducible from that generator.

`python3 code/package.py --output demo --destination /tmp/trace-atlas-demo.zip` creates a validated offline viewer bundle without changing this README.

## Limitations and data rights

Workflow labels are inferred from bounded evidence. Confidence is qualitative; same-model agreement is not independent accuracy. A trace receives one primary workflow, which can simplify mixed-purpose work. Token telemetry is not an invoice, and hypothetical reductions do not prove achievable savings.

The public repository includes only the synthetic demo. Historical external datasets and their derived exports remain excluded because some source permissions are unresolved. Their attribution and restrictions are preserved in [SOURCES_AND_NOTICES.txt](code/SOURCES_AND_NOTICES.txt). Use only data you are authorized to analyze and share.

Built by Prabhat Singh.
