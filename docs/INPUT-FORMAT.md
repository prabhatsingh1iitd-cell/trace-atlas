# Input format

Pass a Parquet file to `--dataset`, or a directory containing `traces.parquet`. Each row represents one LLM call. The adapter requires these columns:

| Column | Type | Meaning |
| --- | --- | --- |
| `trace_id` | string | Nonempty ID shared by calls in one workflow trace |
| `span_id` | string | Nonempty globally unique call ID |
| `call_index` | integer | Unique within the trace; establishes call order |
| `model` | string | Source model identifier |
| `input_tokens`, `output_tokens` | integer or null | Nonnegative counters; zero is known, null is unknown |
| `usage_basis` | string | `source_reported`, `estimated_cl100k_base`, or `unknown` |
| `input_messages_json`, `output_messages_json` | JSON-encoded string | Message lists, typically `[{"role":"user","content":"..."}]` |
| `extra_json` | JSON-encoded string | Metadata object; use `{}` when absent |
| `session_call_count` | integer | Declared calls in the trace; inconsistent counts are flagged |

For `unknown` provenance, both token values must be null. Estimates never enter recorded-token shares. `extra_json` can include `system_instructions` and `source_reported_session_usage`; session totals remain a separate diagnostic.

Hidden reasoning content is excluded by the text adapter. Example excerpts receive basic email/token-pattern redaction; this is not a complete anonymization guarantee. Review your data and exported excerpts before sharing.

The executable example in `code/generate_demo.py` constructs a complete fictional dataset in this format. Its taxonomy and assignments are hand-authored to demonstrate the viewer; real analysis obtains them through the provider pipeline.
