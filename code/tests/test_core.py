import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from data import add_call, empty_metrics, public_metrics, text_content, excerpt
from mining import validate_assignments, UNKNOWN
from analytics import distribution, usage_statistics


class AccountingTests(unittest.TestCase):
    def test_zero_is_known_and_missing_is_not_zero(self):
        m = empty_metrics()
        add_call(
            m,
            {
                "input_tokens": 0,
                "output_tokens": None,
                "usage_basis": "source_reported",
            },
        )
        r = public_metrics(m, 100)
        self.assertEqual(r["recorded_input_tokens"], 0)
        self.assertIsNone(r["recorded_output_tokens"])
        self.assertEqual(r["recorded_input_known_calls"], 1)
        self.assertEqual(r["calls_with_unknown_usage"], 1)
        self.assertEqual(r["recorded_total_tokens"], 0)

    def test_estimates_do_not_inflate_recorded_share(self):
        m = empty_metrics()
        add_call(
            m,
            {"input_tokens": 80, "output_tokens": 20, "usage_basis": "source_reported"},
        )
        add_call(
            m,
            {
                "input_tokens": 10000,
                "output_tokens": 2000,
                "usage_basis": "estimated_cl100k_base",
            },
        )
        add_call(
            m, {"input_tokens": None, "output_tokens": None, "usage_basis": "unknown"}
        )
        r = public_metrics(m, 200)
        self.assertEqual(r["share_of_recorded_tokens_percent"], 50)
        self.assertEqual(r["recorded_total_tokens"], 100)
        self.assertEqual(r["estimated_total_tokens"], 12000)
        self.assertEqual(r["calls_with_unknown_usage"], 1)

    def test_all_unknown_and_zero_denominator(self):
        m = empty_metrics()
        add_call(
            m, {"input_tokens": None, "output_tokens": None, "usage_basis": "unknown"}
        )
        r = public_metrics(m, 0)
        self.assertIsNone(r["recorded_total_tokens"])
        self.assertIsNone(r["share_of_recorded_tokens_percent"])

    def test_invalid_usage_rejected(self):
        for value in [-1, float("nan"), True]:
            with self.assertRaises(ValueError):
                add_call(
                    empty_metrics(),
                    {
                        "input_tokens": value,
                        "output_tokens": 1,
                        "usage_basis": "source_reported",
                    },
                )


class AdapterTests(unittest.TestCase):
    def test_parts_content_and_reasoning(self):
        message = {
            "parts": [
                {"type": "text", "content": "visible"},
                {"type": "thinking", "thinking": "private"},
                {"type": "tool_call", "name": "lookup", "arguments": {"q": "value"}},
            ]
        }
        s = text_content(message)
        self.assertIn("visible", s)
        self.assertIn("value", s)
        self.assertNotIn("private", s)

    def test_excerpt_limit_and_redaction(self):
        e = excerpt("Contact person@example.com " + "a" * 500)
        self.assertNotIn("person@example.com", e)
        self.assertLessEqual(len(e), 241)


class ModelContractTests(unittest.TestCase):
    def setUp(self):
        self.traces = {"t": {"calls": [{"span_id": "s"}]}}
        self.taxonomy = {"business_use_cases": [UNKNOWN]}
        self.row = {
            "trace_id": "t",
            "workflow_id": "WF00",
            "confidence": "low",
            "evidence_span_id": "s",
            "explanation": "Insufficient synthetic evidence.",
        }

    def test_duplicate_assignment_is_rejected(self):
        self.assertEqual(
            validate_assignments(
                {"assignments": [self.row, self.row]}, ["t"], self.traces, self.taxonomy
            ),
            {},
        )

    def test_nonexistent_evidence_is_rejected(self):
        row = {**self.row, "evidence_span_id": "other"}
        self.assertEqual(
            validate_assignments(
                {"assignments": [row]}, ["t"], self.traces, self.taxonomy
            ),
            {},
        )

    def test_nonexistent_workflow_is_rejected(self):
        row = {**self.row, "workflow_id": "missing"}
        self.assertEqual(
            validate_assignments(
                {"assignments": [row]}, ["t"], self.traces, self.taxonomy
            ),
            {},
        )

    def test_single_object_only_valid_for_one_requested_trace(self):
        self.assertIn(
            "t", validate_assignments(self.row, ["t"], self.traces, self.taxonomy)
        )
        self.assertEqual(
            validate_assignments(
                self.row, ["t", "another"], self.traces, self.taxonomy
            ),
            {},
        )


class AnalyticsTests(unittest.TestCase):
    def test_percentiles_and_empty_population(self):
        d = distribution([0, 10, 20, 30])
        self.assertEqual(d["p50"], 15)
        self.assertEqual(d["p90"], 27)
        self.assertAlmostEqual(d["p99"], 29.7)
        self.assertIsNone(distribution([])["p50"])

    def test_provenance_populations_stay_separate(self):
        calls = [
            {"input_tokens": 80, "output_tokens": 20, "usage_basis": "source_reported"},
            {
                "input_tokens": 9000,
                "output_tokens": 1000,
                "usage_basis": "estimated_cl100k_base",
            },
            {"input_tokens": None, "output_tokens": None, "usage_basis": "unknown"},
        ]
        m = empty_metrics()
        for c in calls:
            add_call(m, c)
        stats = usage_statistics(["t"], {"t": {"calls": calls, "metrics": m}})
        self.assertEqual(stats["recorded_tokens_per_complete_call"]["mean"], 100)
        self.assertEqual(stats["estimated_tokens_per_complete_call"]["mean"], 10000)
        self.assertEqual(
            stats["recorded_tokens_per_fully_recorded_trace"]["sample_count"], 0
        )


if __name__ == "__main__":
    unittest.main()
