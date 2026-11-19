# Trace Atlas — Variant 02

Student ID: 2023ME20601

All 50,000 calls and 3,118 traces are represented; 54 traces have an unresolved semantic label.

The pipeline preserves original trace/span IDs and source call order. Local TF-IDF and mini-batch clustering select diverse discovery examples. Only Hyde's `hyde/glm-5.3-flash` discovers the taxonomy, assigns traces, describes activities, and audits expanded evidence. Calls inherit their trace's primary workflow; no label propagation is used.

Uncertain traces receive a fuller-context review; promotion requires two agreeing, high-confidence GLM judgments with source evidence. Follow-up audit history is retained. Usage Lab adds provenance-specific distributions and explicitly hypothetical input-reduction scenarios.

Python computes all counts and usage. Recorded shares use source-reported input plus output tokens only. Supplied cl100k_base estimates, unknown values, and separately reported session totals remain distinct. Cache subtotals are not added again. These assessment sources are not necessarily production traffic.

## View saved results

From the extracted folder, run `python3 code/serve.py`, then open http://127.0.0.1:8765. No API key, dataset, or third-party packages are needed to view results. Alternatively open `code/viewer.html` and select the output JSON/JSONL files.

## Validate or reproduce

`python3 code/validate.py --output output`

For mining (tested with Python 3.13), install `code/requirements.txt`, set `HYDE_API_KEY` locally, then run:

`python3 code/main.py all --dataset /path/to/assigned/dataset --student-id 2023ME20601 --concurrency 8`

Add `--dataset /path/to/assigned/dataset` to validation for independent source reconciliation. Inference caches are local and excluded from this submission.

Bounded excerpts can omit context. Confidence is qualitative; same-model audit agreement is not ground-truth accuracy. Exact assignments, examples, coverage, audit results, and usage provenance are in `output/`. Source notices are retained in `code/SOURCES_AND_NOTICES.txt`.
