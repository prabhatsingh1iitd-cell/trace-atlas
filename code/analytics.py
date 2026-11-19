"""Descriptive usage statistics; recorded and estimated populations never mix."""

from statistics import median


def percentile(values, p):
    if not values:
        return None
    x = sorted(values)
    position = (len(x) - 1) * p
    lo = int(position)
    hi = min(lo + 1, len(x) - 1)
    return x[lo] + (x[hi] - x[lo]) * (position - lo)


def distribution(values):
    return {
        "sample_count": len(values),
        "mean": sum(values) / len(values) if values else None,
        "p50": median(values) if values else None,
        "p90": percentile(values, 0.90),
        "p99": percentile(values, 0.99),
        "maximum": max(values) if values else None,
    }


def usage_statistics(members, traces):
    recorded = []
    estimated = []
    complete_traces = []
    lengths = []
    for tid in members:
        t = traces[tid]
        lengths.append(len(t["calls"]))
        for c in t["calls"]:
            if c["input_tokens"] is None or c["output_tokens"] is None:
                continue
            total = c["input_tokens"] + c["output_tokens"]
            if c["usage_basis"] == "source_reported":
                recorded.append(total)
            elif c["usage_basis"] == "estimated_cl100k_base":
                estimated.append(total)
        if t["metrics"]["recorded_both_known_calls"] == len(t["calls"]):
            complete_traces.append(
                t["metrics"]["recorded_input_tokens"]
                + t["metrics"]["recorded_output_tokens"]
            )
    return {
        "recorded_tokens_per_complete_call": distribution(recorded),
        "estimated_tokens_per_complete_call": distribution(estimated),
        "recorded_tokens_per_fully_recorded_trace": distribution(complete_traces),
        "calls_per_trace": distribution(lengths),
        "population_note": "Recorded-call statistics require both source_reported counters. Estimated-call statistics use supplied estimates separately. Fully recorded trace statistics exclude any trace with estimated or unknown call usage. Percentiles use linear interpolation.",
    }


def concentration(traces):
    values = sorted(
        (
            t["metrics"]["recorded_input_tokens"]
            + t["metrics"]["recorded_output_tokens"]
            for t in traces.values()
        ),
        reverse=True,
    )
    total = sum(values)
    result = []
    for fraction in [0.01, 0.05, 0.10, 0.20, 0.50, 1.0]:
        n = max(1, round(len(values) * fraction))
        result.append(
            {
                "top_trace_count": n,
                "fraction_of_traces_percent": 100 * n / len(values),
                "share_of_recorded_tokens_percent": 100 * sum(values[:n]) / total
                if total
                else None,
            }
        )
    return result
