"use strict";
const state = {
  results: null,
  quality: null,
  traces: [],
  traceMap: new Map(),
  workflowMap: new Map(),
  callMap: null,
  measure: "tokens",
  selectedCase: null,
  page: 0,
};
const $ = (s) => document.querySelector(s);
const fmt = (n) =>
  n === null || n === undefined
    ? "Unknown"
    : new Intl.NumberFormat("en-US").format(n);
const short = (n) =>
  n === null || n === undefined
    ? "—"
    : new Intl.NumberFormat("en-US", {
        notation: "compact",
        maximumFractionDigits: 2,
      }).format(n);
const pct = (n) => (n === null || n === undefined ? "—" : `${n.toFixed(1)}%`);
function el(tag, cls, text) {
  const e = document.createElement(tag);
  if (cls) e.className = cls;
  if (text !== undefined) e.textContent = String(text);
  return e;
}
function add(parent, ...children) {
  for (const c of children) if (c) parent.append(c);
  return parent;
}
function button(text, cls, click) {
  const b = el("button", cls, text);
  b.addEventListener("click", click);
  return b;
}
function notice(text) {
  $("#notice").hidden = !text;
  $("#notice").textContent = text;
}
function showTab(id) {
  document
    .querySelectorAll(".tab")
    .forEach((t) => t.classList.toggle("active", t.id === id));
  document
    .querySelectorAll(".nav")
    .forEach((b) => b.classList.toggle("active", b.dataset.tab === id));
  if (id === "traces") renderTraces();
  window.scrollTo({ top: 0, behavior: "smooth" });
}
document
  .querySelectorAll("[data-tab]")
  .forEach((b) => b.addEventListener("click", () => showTab(b.dataset.tab)));
document
  .querySelectorAll("[data-go]")
  .forEach((b) => b.addEventListener("click", () => showTab(b.dataset.go)));
$(".brand").addEventListener("click", (e) => {
  e.preventDefault();
  showTab("overview");
});
document.querySelectorAll("[data-measure]").forEach((b) =>
  b.addEventListener("click", () => {
    state.measure = b.dataset.measure;
    document
      .querySelectorAll("[data-measure]")
      .forEach((x) => x.classList.toggle("selected", x === b));
    renderDistribution();
  }),
);

function renderAll() {
  const r = state.results;
  if (!r) return;
  state.workflowMap.clear();
  for (const u of r.business_use_cases)
    for (const w of u.workflows) state.workflowMap.set(w.id, { u, w });
  state.selectedCase =
    state.selectedCase &&
    r.business_use_cases.some((u) => u.id === state.selectedCase)
      ? state.selectedCase
      : r.business_use_cases[0]?.id;
  if (state.quality?.status === "incomplete")
    notice(
      "Processing snapshot: record coverage and usage totals are complete; semantic inference is still in progress. Pending and failed cases are explicitly unresolved.",
    );
  $("#identity").textContent = `${r.student_id} · V${r.variant}`;
  $("#footer-status").textContent =
    `${fmt(r.summary.call_count)} calls · ${fmt(r.summary.trace_count)} traces · ${r.classification.taxonomy_version}`;
  const cards = [
    [
      "Historical calls",
      fmt(r.summary.call_count),
      "Every original span ID retained",
    ],
    [
      "Linked traces",
      fmt(r.summary.trace_count),
      "Ordered by the supplied call index",
    ],
    [
      "Recorded tokens",
      short(r.summary.recorded_total_tokens),
      `${short(r.summary.recorded_input_tokens)} input / ${short(r.summary.recorded_output_tokens)} output`,
    ],
    [
      "Estimated tokens",
      short(r.summary.estimated_total_tokens),
      "Supplied cl100k_base estimates only",
    ],
  ];
  $("#metrics").replaceChildren(
    ...cards.map((x, i) =>
      add(
        el("article", `metric${i === 2 ? " primary" : ""}`),
        el("div", "small-label", x[0]),
        el("div", "metric-value", x[1]),
        el("div", "metric-note", x[2]),
      ),
    ),
  );
  renderDistribution();
  renderCoverage();
  renderInsights();
  renderCases();
  renderQuality();
  renderUsage();
  renderReviewMeta();
  const select = $("#workflow-filter");
  select.replaceChildren(el("option", "", "All workflows"));
  select.firstChild.value = "";
  for (const { u, w } of state.workflowMap.values()) {
    const o = el("option", "", `${u.name} / ${w.name}`);
    o.value = w.id;
    select.append(o);
  }
  renderTraces();
}

function renderDistribution() {
  const r = state.results;
  if (!r) return;
  const list = [...r.business_use_cases].sort((a, b) =>
    state.measure === "tokens"
      ? (b.recorded_total_tokens || 0) - (a.recorded_total_tokens || 0)
      : b.call_count - a.call_count,
  );
  const maximum = Math.max(
    ...list.map((u) =>
      state.measure === "tokens" ? u.recorded_total_tokens || 0 : u.call_count,
    ),
    1,
  );
  $("#distribution").replaceChildren(
    ...list.map((u) => {
      const value =
        state.measure === "tokens"
          ? u.recorded_total_tokens || 0
          : u.call_count;
      const share =
        state.measure === "tokens"
          ? u.share_of_recorded_tokens_percent
          : (100 * u.call_count) / r.summary.call_count;
      const row = button("", "distribution-row", () => {
        state.selectedCase = u.id;
        renderCases();
        showTab("hierarchy");
      });
      row.title = `${u.name}: ${fmt(value)} ${state.measure === "tokens" ? "recorded tokens" : "calls"}`;
      const label = add(
        el("div", "bar-label"),
        el("span", "label", u.name),
        el("strong", "", `${short(value)} · ${pct(share)}`),
      );
      const fill = el("div", "bar-fill");
      fill.style.width = `${(100 * value) / maximum}%`;
      if (state.measure === "tokens" && value > 0) {
        const input = el("span", "token-input"),
          output = el("span", "token-output");
        input.style.width = `${(100 * (u.recorded_input_tokens || 0)) / value}%`;
        output.style.width = `${(100 * (u.recorded_output_tokens || 0)) / value}%`;
        add(fill, input, output);
      }
      return add(row, label, add(el("div", "bar-track"), fill));
    }),
  );
  $("#denominator").textContent =
    state.measure === "tokens"
      ? `Share denominator: ${fmt(r.recorded_share_denominator_tokens)} recorded input + output tokens. Green = input; gold = output. Bars scaled to the largest category.`
      : `Share denominator: all ${fmt(r.summary.call_count)} calls, including estimated and unknown usage.`;
}

function renderCoverage() {
  const s = state.results.summary;
  $("#coverage-total").replaceChildren(
    document.createTextNode(
      pct((100 * s.source_reported_calls) / s.call_count),
    ),
    el("span", "", "of calls have source-reported usage"),
  );
  const rows = [
    ["Source-reported", s.source_reported_calls, "#255b4e"],
    ["Tokenizer-estimated", s.estimated_calls, "#d9ad6d"],
    ["Unknown usage", s.calls_with_unknown_usage, "#c1c9bd"],
  ];
  $("#coverage-bar").replaceChildren(
    ...rows.map((x) => {
      const e = el("span");
      e.style.width = `${(100 * x[1]) / s.call_count}%`;
      e.style.background = x[2];
      e.title = `${x[0]}: ${fmt(x[1])} calls`;
      return e;
    }),
  );
  $("#coverage-legend").replaceChildren(
    ...rows.map((x) => {
      const swatch = el("span", "swatch");
      swatch.style.background = x[2];
      return add(
        el("div", "coverage-item"),
        swatch,
        el("span", "", x[0]),
        el("strong", "", fmt(x[1])),
      );
    }),
  );
  const unknown = state.results.classification.unresolved;
  $("#classification-coverage").textContent =
    `${fmt(s.trace_count - unknown.trace_count)} assigned · ${fmt(unknown.trace_count)} unresolved`;
}

function renderInsights() {
  const r = state.results;
  const c = r.insights.find((i) => i.type === "recorded_usage_concentration");
  const ratio = r.insights.find((i) => i.type === "input_output_mix");
  const items = [
    [
      "↗",
      `${pct(c?.recorded_token_share_percent)} of recorded tokens in ${fmt(c?.top_trace_count)} traces`,
      "A focused place to investigate usage. Concentration is an observation, not evidence of waste.",
    ],
    [
      "⇄",
      `${pct(ratio?.recorded_input_share_percent)} of recorded tokens are input`,
      "Review repeated context before proposing caching or compaction. No savings or price assumptions are included.",
    ],
  ];
  $("#insights").replaceChildren(
    ...items.map((x) =>
      add(
        el("article", "insight"),
        el("div", "insight-symbol", x[0]),
        add(el("div"), el("h3", "", x[1]), el("p", "", x[2])),
      ),
    ),
  );
}

function renderCases() {
  const r = state.results;
  if (!r) return;
  $("#case-list").replaceChildren(
    ...r.business_use_cases.map((u) => {
      const b = button(
        "",
        `case-button${u.id === state.selectedCase ? " active" : ""}`,
        () => {
          state.selectedCase = u.id;
          renderCases();
        },
      );
      return add(
        b,
        el("strong", "", u.name),
        el(
          "small",
          "",
          `${u.workflows.length} workflows · ${pct(u.share_of_recorded_tokens_percent)} recorded share`,
        ),
      );
    }),
  );
  const u = r.business_use_cases.find((x) => x.id === state.selectedCase);
  if (!u) return;
  const detail = $("#case-detail");
  detail.replaceChildren(
    el("div", "eyebrow", u.id),
    el("h2", "case-title", u.name),
    el("p", "case-description", u.description),
  );
  for (const w of u.workflows) {
    const card = el("details", "panel workflow");
    if (state.selectedWorkflow === w.id) card.open = true;
    const head = el("summary", "workflow-head");
    const top = add(
      el("div", "workflow-top"),
      add(el("div"), el("h3", "", w.name), el("p", "", w.description)),
      el("span", "", "+"),
    );
    add(
      head,
      top,
      add(
        el("div", "workflow-stats"),
        el("span", "", `${fmt(w.call_count)} calls`),
        el("span", "", `${fmt(w.trace_count)} traces`),
        el(
          "span",
          "",
          `${pct(w.share_of_recorded_tokens_percent)} recorded share`,
        ),
      ),
    );
    const content = el("div", "workflow-content");
    add(
      content,
      add(
        el("p", "criterion"),
        el("b", "", "Include: "),
        document.createTextNode(w.inclusion || ""),
      ),
      add(
        el("p", "criterion"),
        el("b", "", "Exclude: "),
        document.createTextNode(w.exclusion || ""),
      ),
    );
    add(
      content,
      el(
        "p",
        "criterion",
        `Recorded input ${fmt(w.recorded_input_tokens)} · output ${fmt(w.recorded_output_tokens)}. Estimated total ${fmt(w.estimated_total_tokens)}. ${fmt(w.calls_with_unknown_usage)} calls have unknown usage.`,
      ),
    );
    if (w.activity_profile) {
      add(
        content,
        el("p", "criterion", w.activity_profile.scope_note),
        el("p", "small-label", "Activities supported by examples"),
      );
      const activities = el("ul", "activity-list");
      for (const activity of w.activity_profile.observed_activities) {
        const item = el("li");
        add(item, el("span", "", activity.name));
        for (const tid of activity.evidence_trace_ids)
          add(
            item,
            button(tid.slice(0, 8) + "…", "activity-evidence", () =>
              openTrace(tid),
            ),
          );
        activities.append(item);
      }
      add(content, activities);
    }
    for (const e of w.examples) {
      const meta = add(
        el("div", "example-meta"),
        el("span", "", `${e.role.toUpperCase()} · CALL ${e.call_index}`),
        button(`${e.trace_id.slice(0, 12)}…`, "", () => openTrace(e.trace_id)),
      );
      add(
        content,
        add(
          el("article", "example"),
          meta,
          el("blockquote", "", e.excerpt),
          el("div", "footnote", e.selection_method),
        ),
      );
    }
    add(
      content,
      button(`Explore ${fmt(w.trace_count)} traces →`, "text-button", () => {
        $("#workflow-filter").value = w.id;
        state.page = 0;
        showTab("traces");
      }),
    );
    add(card, head, content);
    detail.append(card);
  }
}

function availableTraces() {
  if (state.traces.length) return state.traces;
  const rows = [];
  for (const { u, w } of state.workflowMap.values())
    for (const id of w.trace_ids)
      rows.push({ trace_id: id, use_case_id: u.id, workflow_id: w.id });
  return rows;
}
function filteredTraces() {
  const query = $("#search").value.trim().toLowerCase(),
    wid = $("#workflow-filter").value,
    confidence = $("#confidence-filter").value,
    status = $("#status-filter").value,
    usage = $("#usage-filter").value,
    sort = $("#sort-order").value;
  const rows = availableTraces().filter((t) => {
    const pair = state.workflowMap.get(t.workflow_id);
    return (
      (!wid || wid === t.workflow_id) &&
      (!confidence || t.confidence === confidence) &&
      (!query ||
        [t.trace_id, pair?.w.name, pair?.u.name]
          .join(" ")
          .toLowerCase()
          .includes(query)) &&
      (!status ||
        (status === "unresolved" && t.workflow_id === "WF00") ||
        (status === "audited" && t.audit_checked) ||
        (status === "reviewed" && t.fuller_context_reviewed)) &&
      (!usage ||
        (usage === "recorded" && t.recorded_input_known_calls > 0) ||
        (usage === "estimated" && t.estimated_input_known_calls > 0) ||
        (usage === "unknown" && t.calls_with_unknown_usage > 0))
    );
  });
  const key = {
    tokens: "recorded_total_tokens",
    calls: "call_count",
    input: "recorded_input_tokens",
    output: "recorded_output_tokens",
  }[sort];
  return rows.sort(
    (a, b) =>
      (key ? (b[key] || 0) - (a[key] || 0) : 0) ||
      a.trace_id.localeCompare(b.trace_id),
  );
}
function renderTraces() {
  if (!state.results) return;
  const rows = filteredTraces(),
    pages = Math.max(1, Math.ceil(rows.length / 40));
  state.page = Math.min(state.page, pages - 1);
  const page = rows.slice(state.page * 40, (state.page + 1) * 40);
  $("#trace-body").replaceChildren(
    ...page.map((t) => {
      const w = state.workflowMap.get(t.workflow_id)?.w;
      return add(
        el("tr"),
        el("td", "", t.trace_id),
        el("td", "", w?.name || t.workflow_id),
        el("td", "", t.call_count === undefined ? "—" : fmt(t.call_count)),
        el(
          "td",
          "",
          t.recorded_total_tokens === undefined
            ? "—"
            : short(t.recorded_total_tokens),
        ),
        add(
          el("td"),
          el(
            "span",
            `confidence ${t.confidence || "low"}`,
            t.confidence || "not loaded",
          ),
        ),
        add(
          el("td"),
          button("View →", "", () => openTrace(t.trace_id)),
        ),
      );
    }),
  );
  if (!rows.length) {
    const td = el("td", "empty", "No traces match these filters.");
    td.colSpan = 6;
    $("#trace-body").append(add(el("tr"), td));
  }
  $("#trace-count").textContent =
    `${fmt(rows.length)} matching traces${!state.traces.length ? " · Load trace_assignments.jsonl for individual metrics" : ""}`;
  $("#page-number").textContent = `${state.page + 1} / ${pages}`;
  $("#previous").disabled = state.page === 0;
  $("#next").disabled = state.page === pages - 1;
}
$("#search").addEventListener("input", () => {
  state.page = 0;
  renderTraces();
});
for (const id of ["workflow-filter", "confidence-filter"])
  $("#" + id).addEventListener("change", () => {
    state.page = 0;
    renderTraces();
  });
$("#previous").addEventListener("click", () => {
  state.page--;
  renderTraces();
});
$("#next").addEventListener("click", () => {
  state.page++;
  renderTraces();
});

function openTrace(id) {
  const t =
    state.traceMap.get(id) || availableTraces().find((x) => x.trace_id === id);
  if (!t) return;
  const pair = state.workflowMap.get(t.workflow_id);
  const d = $("#trace-detail");
  d.replaceChildren(
    el("div", "trace-id", id),
    el("h2", "", pair?.w.name || t.workflow_id),
    el("p", "trace-description", pair?.u.name || ""),
  );
  if (t.explanation) add(d, el("p", "trace-description", t.explanation));
  const cards = [
    ["Calls", fmt(t.call_count)],
    ["Recorded tokens", fmt(t.recorded_total_tokens)],
    ["Estimated tokens", fmt(t.estimated_total_tokens)],
    ["Calls with unknown usage", fmt(t.calls_with_unknown_usage)],
  ];
  add(
    d,
    add(
      el("div", "detail-grid"),
      ...cards.map((x) =>
        add(
          el("div", "detail-box"),
          el("div", "small-label", x[0]),
          el("strong", "", x[1]),
        ),
      ),
    ),
  );
  add(
    d,
    el(
      "p",
      "footnote",
      `Method: ${t.method || "load trace assignments"} · Confidence: ${t.confidence || "not loaded"} · Status: ${t.status || "not loaded"}`,
    ),
  );
  if (t.evidence_span_id)
    add(d, el("p", "footnote", `Evidence span ID: ${t.evidence_span_id}`));
  if (t.audit_checked)
    add(
      d,
      el(
        "p",
        "footnote",
        `Expanded-evidence audit: ${t.audit_initial_agreement ? "initial judgments agreed" : "disagreement reviewed"}. This is a same-model check.`,
      ),
    );
  if (t.observed_tool_names?.length)
    add(
      d,
      el("p", "small-label", "Observed tool names"),
      add(
        el("div"),
        ...t.observed_tool_names.map((x) => el("span", "pill", x)),
      ),
    );
  add(
    d,
    el(
      "p",
      "footnote",
      "The exported call_assignments.jsonl retains every constituent span ID and call index. No full prompt or response payload is included.",
    ),
  );
  const sequence = el("section", "call-sequence-section");
  add(
    sequence,
    button("Show original call IDs", "text-button", () =>
      showCallSequence(sequence, id),
    ),
  );
  add(d, sequence);
  $("#trace-dialog").showModal();
}
$("#close-dialog").addEventListener("click", () => $("#trace-dialog").close());
$("#trace-dialog").addEventListener("click", (e) => {
  if (e.target === $("#trace-dialog")) $("#trace-dialog").close();
});

function qualityRow(label, value) {
  return add(
    el("div", "quality-row"),
    el("span", "", label),
    el("strong", "", value),
  );
}
function setCalls(rows) {
  state.callMap = new Map();
  for (const row of rows) {
    if (!state.callMap.has(row.trace_id)) state.callMap.set(row.trace_id, []);
    state.callMap.get(row.trace_id).push(row);
  }
  for (const rows of state.callMap.values())
    rows.sort((a, b) => a.call_index - b.call_index);
}
async function showCallSequence(container, tid) {
  container.replaceChildren(el("p", "footnote", "Loading original call IDs…"));
  try {
    if (!state.callMap) {
      const response = await fetch("call_assignments.jsonl");
      if (!response.ok) throw Error();
      setCalls(
        (await response.text())
          .trim()
          .split(/\r?\n/)
          .filter(Boolean)
          .map((line) => JSON.parse(line)),
      );
    }
    const rows = state.callMap.get(tid) || [];
    const table = el("table");
    const head = add(
      el("thead"),
      add(
        el("tr"),
        el("th", "", "Source call index"),
        el("th", "", "Original span ID"),
        el("th", "", "Evidence"),
      ),
    );
    const body = el("tbody");
    for (const c of rows)
      add(
        body,
        add(
          el("tr"),
          el("td", "", c.call_index),
          el("td", "span-id", c.span_id),
          el(
            "td",
            "",
            c.span_id === state.traceMap.get(tid)?.evidence_span_id
              ? "Referenced"
              : "",
          ),
        ),
      );
    add(table, head, body);
    container.replaceChildren(
      el(
        "p",
        "footnote",
        `${fmt(rows.length)} original call IDs in source order. Payloads are excluded.`,
      ),
      add(el("div", "call-sequence"), table),
    );
  } catch (error) {
    container.replaceChildren(
      el(
        "p",
        "footnote",
        "Open call_assignments.jsonl using “Open result files”, then reopen this trace to inspect its call sequence.",
      ),
    );
  }
}
function renderQuality() {
  const r = state.results,
    q = state.quality,
    a = r.classification.audit;
  const grid = el("div", "quality-grid");
  const ledger = add(
    el("article", "panel quality-card"),
    el("h2", "", "Accounting & coverage"),
    qualityRow("Original calls", fmt(r.summary.call_count)),
    qualityRow("Original traces", fmt(r.summary.trace_count)),
    qualityRow("Recorded input", fmt(r.summary.recorded_input_tokens)),
    qualityRow("Recorded output", fmt(r.summary.recorded_output_tokens)),
    qualityRow("Estimated input", fmt(r.summary.estimated_input_tokens)),
    qualityRow("Estimated output", fmt(r.summary.estimated_output_tokens)),
    qualityRow("Unknown usage calls", fmt(r.summary.calls_with_unknown_usage)),
    el(
      "p",
      "footnote",
      "Source-reported counts are telemetry, not verified invoices. Recorded shares use known components only.",
    ),
  );
  const method = add(
    el("article", "panel quality-card"),
    el("h2", "", "Semantic method"),
    qualityRow("Permitted model", r.classification.model),
    qualityRow(
      "Discovery sample",
      `${fmt(r.classification.discovery_trace_count)} traces`,
    ),
    qualityRow(
      "Unresolved traces",
      fmt(r.classification.unresolved.trace_count),
    ),
    qualityRow("Latest audit sample", fmt(a.validated_sample_size)),
    qualityRow("Initial audit agreement", pct(a.initial_agreement_percent)),
    qualityRow("Disagreements adjudicated", fmt(a.adjudicated_count)),
    el(
      "p",
      "",
      a.interpretation || "Consistency audit has not been completed.",
    ),
  );
  add(grid, ledger, method);
  const steps = add(
    el("article", "panel quality-card quality-notes"),
    el("h2", "", "How the hierarchy was built"),
  );
  const ol = el("ol");
  for (const text of [
    "Reconstruct each source trace using trace_id and call_index.",
    "Sample diverse, high-usage, and uncertain traces using local statistical features.",
    "Ask the permitted GLM to discover and consolidate purpose/workflow definitions.",
    "Classify each trace directly, then audit a targeted sample with expanded evidence.",
    "Roll up all source counters with deterministic code; validate IDs and sums.",
  ])
    ol.append(el("li", "", text));
  add(steps, ol);
  const notes = add(
    el("article", "panel quality-card quality-notes"),
    el("h2", "", "Interpretation & limitations"),
  );
  const ul = el("ul");
  for (const note of r.notes) ul.append(el("li", "", note));
  add(notes, ul);
  const provenance = add(
    el("article", "panel quality-card quality-notes"),
    el("h2", "", "Provenance"),
    el("p", "", `Dataset SHA-256: ${r.source.sha256}`),
    el(
      "p",
      "",
      `Generated ${new Date(r.generated_at).toLocaleString()}. Source notices are included in code/SOURCES_AND_NOTICES.txt.`,
    ),
    el(
      "p",
      "",
      `${fmt(r.session_usage_diagnostic.trace_count)} traces contain separately reported session totals. These are excluded from the per-call ledger.`,
    ),
  );
  if (q?.pipeline_inference_usage)
    add(
      provenance,
      el(
        "p",
        "",
        `Analysis inference: ${fmt(q.pipeline_inference_usage.request_count)} successful cached GLM requests; ${fmt(q.pipeline_inference_usage.input_tokens)} prompt and ${fmt(q.pipeline_inference_usage.output_tokens)} completion tokens. This is separate from historical usage and excludes failed requests/preflight.`,
      ),
    );
  $("#quality-content").replaceChildren(grid, steps, notes, provenance);
}

function setTraces(rows) {
  state.traces = rows;
  state.traceMap = new Map(rows.map((t) => [t.trace_id, t]));
}
$("#files").addEventListener("change", async (e) => {
  try {
    const incoming = {};
    for (const file of e.target.files) {
      if (
        ![
          "results.json",
          "quality.json",
          "trace_assignments.jsonl",
          "call_assignments.jsonl",
        ].includes(file.name)
      )
        continue;
      const text = await file.text();
      incoming[file.name] = file.name.endsWith(".jsonl")
        ? text
            .trim()
            .split(/\r?\n/)
            .filter(Boolean)
            .map((line) => JSON.parse(line))
        : JSON.parse(text);
    }
    const results = incoming["results.json"] || state.results;
    if (!results?.business_use_cases || !results.source?.sha256)
      throw new Error("Select a valid results.json file.");
    const ids = new Set(
      results.business_use_cases.flatMap((u) =>
        u.workflows.flatMap((w) => w.trace_ids),
      ),
    );
    for (const name of ["trace_assignments.jsonl", "call_assignments.jsonl"]) {
      if (
        incoming[name] &&
        incoming[name].some((row) => !ids.has(row.trace_id))
      )
        throw new Error(`${name} does not match this result dataset.`);
    }
    if (
      incoming["quality.json"]?.source_sha256 &&
      incoming["quality.json"].source_sha256 !== results.source.sha256
    )
      throw new Error("quality.json does not match this result dataset.");
    if (state.results?.source.sha256 !== results.source.sha256) {
      setTraces([]);
      state.callMap = null;
      state.quality = null;
      state.selectedCase = null;
    }
    state.results = results;
    if (incoming["quality.json"]) state.quality = incoming["quality.json"];
    if (incoming["trace_assignments.jsonl"])
      setTraces(incoming["trace_assignments.jsonl"]);
    if (incoming["call_assignments.jsonl"])
      setCalls(incoming["call_assignments.jsonl"]);
    notice("");
    renderAll();
  } catch (error) {
    notice(`Could not load files: ${error.message}`);
  }
});
async function boot() {
  try {
    const response = await fetch("results.json");
    if (!response.ok) throw new Error("Results not available");
    state.results = await response.json();
    const loaded = await Promise.allSettled([
      fetch("trace_assignments.jsonl")
        .then((r) => {
          if (!r.ok) throw Error();
          return r.text();
        })
        .then((text) =>
          setTraces(
            text
              .trim()
              .split(/\r?\n/)
              .filter(Boolean)
              .map((line) => JSON.parse(line)),
          ),
        ),
      fetch("quality.json")
        .then((r) => r.json())
        .then((q) => {
          state.quality = q;
        }),
    ]);
    renderAll();
    if (loaded[0].status === "rejected")
      notice(
        "Hierarchy loaded. Open trace_assignments.jsonl to enable individual trace metrics.",
      );
  } catch (error) {
    notice(
      "Start the local viewer with python code/serve.py, or use “Open result files” to select output/results.json and trace_assignments.jsonl.",
    );
  }
}
boot();

function renderReviewMeta() {
  const r = state.results,
    unknown = r.classification.unresolved;
  $("#overview-meta").replaceChildren(
    ...[
      `${r.business_use_cases.filter((u) => u.id !== "UC00").length} identified use cases`,
      `${[...state.workflowMap.keys()].filter((id) => id !== "WF00").length} resolved workflow types`,
      `${pct((100 * (r.summary.trace_count - unknown.trace_count)) / r.summary.trace_count)} traces assigned`,
      `${fmt(r.classification.audit.validated_sample_size)} in latest audit`,
    ].map((x) => el("span", "meta-chip", x)),
  );
  $("#download-results").disabled = false;
  const review = r.classification.fuller_context_review;
  if (review) {
    const card = add(
      el("article", "panel quality-card quality-notes"),
      el("h2", "", "Fuller-context review & audit history"),
      el("p", "", review.policy),
      qualityRow("Uncertain traces reviewed", fmt(review.reviewed_trace_count)),
      qualityRow(
        "Labels promoted by two agreeing judgments",
        fmt(review.resolved_trace_count),
      ),
      qualityRow(
        "Currently unresolved after all reviews",
        fmt(unknown.trace_count),
      ),
      qualityRow(
        "Unresolved recorded-token share",
        pct(unknown.share_of_recorded_tokens_percent),
      ),
    );
    for (const previous of r.classification.audit_history || [])
      add(
        card,
        el(
          "p",
          "footnote",
          `Earlier audit: ${fmt(previous.validated_sample_size)} traces; ${pct(previous.initial_agreement_percent)} initial same-model agreement. ${previous.revision_note || ""}`,
        ),
      );
    add(
      card,
      el(
        "p",
        "footnote",
        "Audit samples include random, high-usage, and uncertain cases. Samples change after label revisions; agreement percentages are not comparable accuracy scores. Original agreement is preserved through adjudication.",
      ),
    );
    $("#quality-content").append(card);
  }
}

function openWorkflow(wid) {
  const pair = state.workflowMap.get(wid);
  if (!pair) return;
  state.selectedCase = pair.u.id;
  state.selectedWorkflow = wid;
  renderCases();
  showTab("hierarchy");
}
function renderUsage() {
  if (!state.results) return;
  const scope = $("#scenario-scope"),
    selected = scope.value;
  scope.replaceChildren(el("option", "", "All use cases"));
  scope.firstChild.value = "";
  for (const { u, w } of state.workflowMap.values()) {
    const option = el("option", "", `${u.name} / ${w.name}`);
    option.value = w.id;
    scope.append(option);
  }
  scope.value = selected;
  renderIntensity();
  renderScenario();
  const curve = state.results.analytics?.concentration_curve || [];
  $("#concentration").replaceChildren(
    ...curve.map((point) => {
      const label = add(
        el("div", "bar-label"),
        el(
          "span",
          "",
          `Top ${pct(point.fraction_of_traces_percent)} · ${fmt(point.top_trace_count)} traces`,
        ),
        el("strong", "", pct(point.share_of_recorded_tokens_percent)),
      );
      const fill = el("div", "bar-fill");
      fill.style.width = `${point.share_of_recorded_tokens_percent || 0}%`;
      return add(
        el("div", "concentration-row"),
        label,
        add(el("div", "bar-track"), fill),
      );
    }),
  );
}
function renderIntensity() {
  const query = $("#lab-search").value.trim().toLowerCase();
  const rows = [...state.workflowMap.values()].filter(({ u, w }) =>
    `${u.name} ${w.name}`.toLowerCase().includes(query),
  );
  rows.sort(
    (a, b) =>
      (b.w.usage_statistics?.recorded_tokens_per_complete_call.p90 || 0) -
      (a.w.usage_statistics?.recorded_tokens_per_complete_call.p90 || 0),
  );
  $("#intensity-body").replaceChildren(
    ...rows.map(({ u, w }) => {
      const stats = w.usage_statistics?.recorded_tokens_per_complete_call;
      return add(
        el("tr"),
        add(
          el("td"),
          button(w.name, "workflow-link", () => openWorkflow(w.id)),
          el("div", "cell-subtitle", u.name),
        ),
        el("td", "", fmt(stats?.sample_count)),
        el("td", "", pct((100 * w.recorded_both_known_calls) / w.call_count)),
        el("td", "", short(stats?.p50)),
        el("td", "", short(stats?.p90)),
        el("td", "", pct(w.share_of_recorded_tokens_percent)),
      );
    }),
  );
  if (!rows.length) {
    const td = el("td", "empty", "No matching workflows.");
    td.colSpan = 6;
    $("#intensity-body").append(add(el("tr"), td));
  }
}
function renderScenario() {
  const r = state.results;
  if (!r) return;
  const id = $("#scenario-scope").value,
    group = id ? state.workflowMap.get(id)?.w : r.summary;
  if (!group) return;
  if (!group.recorded_input_known_calls) {
    $("#reduction-label").textContent = pct(
      Number($("#reduction-slider").value),
    );
    $("#scenario-values").replaceChildren(
      el(
        "p",
        "empty",
        "No source-reported input counters are available in this scope. A reduction scenario cannot be calculated.",
      ),
    );
    return;
  }
  const reduction = Number($("#reduction-slider").value) / 100,
    input = group.recorded_input_tokens || 0,
    output = group.recorded_output_tokens || 0,
    total = input + output,
    avoided = input * reduction;
  $("#reduction-label").textContent = pct(reduction * 100);
  const values = [
    ["Recorded baseline", short(total)],
    ["Hypothetical input avoided", short(avoided)],
    ["Hypothetical remaining total", short(total - avoided)],
  ];
  $("#scenario-values").replaceChildren(
    ...values.map((x) =>
      add(
        el("div", "scenario-value"),
        el("span", "", x[0]),
        el("strong", "", x[1]),
      ),
    ),
  );
  if (!group.recorded_input_known_calls)
    $("#scenario-values").append(
      el(
        "p",
        "footnote",
        "No source-reported input counters are available in this scope.",
      ),
    );
}
function downloadJSON(filename, value) {
  const url = URL.createObjectURL(
    new Blob([JSON.stringify(value, null, 2)], { type: "application/json" }),
  );
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  link.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
$("#download-results").addEventListener("click", () => {
  if (state.results) downloadJSON("trace_atlas_results.json", state.results);
});
$("#download-filtered").addEventListener("click", () =>
  downloadJSON("trace_atlas_filtered_traces.json", {
    schema_version: "1.0",
    source_sha256: state.results.source.sha256,
    trace_count: filteredTraces().length,
    traces: filteredTraces(),
  }),
);
$("#lab-search").addEventListener("input", renderIntensity);
$("#scenario-scope").addEventListener("change", renderScenario);
$("#reduction-slider").addEventListener("input", renderScenario);
for (const id of ["status-filter", "usage-filter", "sort-order"])
  $("#" + id).addEventListener("change", () => {
    state.page = 0;
    renderTraces();
  });
$("#clear-filters").addEventListener("click", () => {
  for (const id of [
    "search",
    "workflow-filter",
    "confidence-filter",
    "status-filter",
    "usage-filter",
  ])
    $("#" + id).value = "";
  $("#sort-order").value = "tokens";
  state.page = 0;
  renderTraces();
});
