import {
  BUCKETS,
  DEFAULT_RANGE,
  RANGES,
  bigNumber,
  filterChains,
  fmtDate,
  fmtNum,
  fmtPct,
  fmtUpdated,
  groupCounts,
  heroDetail,
  heroSentence,
  indexed,
  pctClass,
  sortChains,
  trackText,
} from "./lib.js";

const $ = (sel, root = document) => root.querySelector(sel);
const css = (name) => getComputedStyle(document.documentElement).getPropertyValue(name).trim();
const SERIES_VARS = ["--s1", "--s2", "--s3", "--s4", "--s5", "--s6", "--s7"];
const GROUP_KEY = "mw-group";

let DATA;
let group = "All";
const charts = new Set();

function el(tag, attrs = {}, ...children) {
  const node = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (v == null || v === false) continue;
    if (k === "class") node.className = v;
    else if (k === "text") node.textContent = v;
    else node.setAttribute(k, v === true ? "" : v);
  }
  node.append(...children.filter((c) => c != null && c !== false));
  return node;
}

function readGroup() {
  try {
    return localStorage.getItem(GROUP_KEY);
  } catch {
    return null;
  }
}
function saveGroup(g) {
  try {
    localStorage.setItem(GROUP_KEY, g);
  } catch {
    /* storage unavailable */
  }
}

// ---------- Detail (chart + table) ----------

function seriesTable(ids) {
  const rows = ids.map((id, j) => {
    const s = DATA.series[id];
    const pct = (k) =>
      el(
        "td",
        { class: pctClass(s.changes[k]) },
        fmtPct(s.changes[k]),
        s.change_labels[k] !== k ? el("span", { class: "muted", text: ` ${s.change_labels[k]}` }) : null,
      );
    return el(
      "tr",
      { "data-series": id },
      el(
        "td",
        {},
        el(
          "div",
          { class: "series-name" },
          el("span", { class: `swatch s${j + 1}` }),
          el(
            "div",
            {},
            el("span", { text: s.label }),
            el("small", { text: j === 0 ? `${s.role}, driver` : s.role }),
            s.stale ? el("small", { class: "stale-text", text: s.stale }) : null,
          ),
        ),
      ),
      el(
        "td",
        {},
        s.latest ? fmtNum(s.latest.value) : "—",
        s.latest ? el("small", { class: "muted", text: ` ${s.unit}` }) : null,
      ),
      el("td", { class: "muted", text: s.latest ? fmtDate(s.latest.date) : "—" }),
      pct("30d"),
      pct("90d"),
      pct("1y"),
    );
  });
  return el(
    "div",
    { class: "table-scroll" },
    el(
      "table",
      { class: "series" },
      el(
        "thead",
        {},
        el(
          "tr",
          {},
          ...["Series", "Latest", "As of", "30d", "90d", "1y"].map((h) => el("th", { scope: "col", text: h })),
        ),
      ),
      el("tbody", {}, ...rows),
    ),
  );
}

function buildChart(canvas, chain, rangeKey) {
  const ids = chain.series;
  const list = ids.map((id) => DATA.series[id]);
  const data = indexed(list, rangeKey);
  const ink2 = css("--ink-2");
  const rule = css("--rule");
  const config = {
    type: "line",
    data: {
      datasets: list.map((s, j) => {
        const color = css(SERIES_VARS[j] ?? "--s7");
        return {
          label: s.label + (s.stale ? " (stale)" : ""),
          data: data[j],
          borderColor: color,
          backgroundColor: color,
          borderWidth: j < 2 ? 2.4 : 1.4,
          borderDash: s.stale ? [6, 4] : [],
          pointRadius: data[j].length <= 3 ? 4 : 0,
          pointHoverRadius: 4,
          pointBorderColor: css("--sheet"),
          pointBorderWidth: 2,
          tension: 0.2,
          order: j < 2 ? j : 2 + j,
        };
      }),
    },
    options: {
      maintainAspectRatio: false,
      animation: false,
      parsing: false,
      normalized: true,
      interaction: { mode: "nearest", axis: "x", intersect: false },
      scales: {
        x: {
          type: "time",
          grid: { display: false },
          border: { color: rule },
          ticks: { color: ink2, maxRotation: 0, autoSkipPadding: 20 },
        },
        y: {
          grid: { color: rule },
          border: { display: false },
          ticks: { color: ink2, maxTicksLimit: 6 },
          title: { display: true, text: "Index, start of range = 100", color: ink2 },
        },
      },
      plugins: {
        legend: {
          position: "bottom",
          labels: { color: ink2, boxWidth: 14, boxHeight: 3, padding: 14, font: { family: "Inter" } },
        },
        tooltip: {
          backgroundColor: css("--ink"),
          titleColor: css("--paper"),
          bodyColor: css("--paper"),
          padding: 10,
          cornerRadius: 8,
          callbacks: {
            title: (items) => (items[0] ? fmtDate(items[0].raw.date) : ""),
            label: (ctx) => {
              const s = list[ctx.datasetIndex];
              return ` ${s.label}: ${fmtNum(ctx.raw.raw)} ${s.unit} (index ${ctx.raw.y.toFixed(1)})`;
            },
          },
        },
      },
    },
  };
  const chart = new window.Chart(canvas, config);
  charts.add(chart);
  return chart;
}

function renderDetail(chain, detail) {
  const ranges = el(
    "div",
    { class: "ranges", role: "group", "aria-label": "Time range" },
    ...Object.keys(RANGES).map((k) =>
      el("button", { type: "button", "data-range": k, "aria-pressed": String(k === DEFAULT_RANGE), text: k }),
    ),
  );
  const canvas = el("canvas", {
    role: "img",
    "aria-label": `${chain.title}: ${chain.series.length} price series, each indexed to 100 at the start of the range`,
  });
  detail.replaceChildren(
    el(
      "div",
      { class: "detail-head" },
      el("span", { class: "muted", text: "Each line is indexed to 100 at its first point in the range and stops at its last real value." }),
      ranges,
    ),
    el("div", { class: "chart-frame" }, canvas),
    seriesTable(chain.series),
    chain.links?.length
      ? el(
          "ul",
          { class: "links" },
          ...chain.links.map((l) => el("li", {}, el("a", { href: l.url, rel: "noopener", target: "_blank", text: l.label }))),
        )
      : "",
  );
  const chart = buildChart(canvas, chain, DEFAULT_RANGE);
  ranges.querySelectorAll("button").forEach((b) =>
    b.addEventListener("click", () => {
      ranges.querySelectorAll("button").forEach((x) => x.setAttribute("aria-pressed", String(x === b)));
      indexed(chain.series.map((id) => DATA.series[id]), b.dataset.range).forEach((d, j) => {
        chart.data.datasets[j].data = d;
        chart.data.datasets[j].pointRadius = d.length <= 3 ? 4 : 0;
      });
      chart.update();
    }),
  );
  return chart;
}

// ---------- Cards and buckets ----------

function card(chain) {
  const node = $("#card-template").content.firstElementChild.cloneNode(true);
  node.id = `chain-${chain.id}`;
  node.dataset.kind = chain.kind;
  $("[data-title]", node).textContent = chain.title;
  $("[data-group]", node).textContent = chain.group;
  $("[data-headline]", node).textContent = chain.headline;
  $("[data-reason]", node).textContent = chain.reason;

  const big = bigNumber(chain, DATA.horizon_months);
  if (big) {
    $("[data-big]", node).hidden = false;
    $("[data-big-value]", node).textContent = big.value;
    $("[data-big-note]", node).textContent = big.note;
  }
  if (chain.live_gap) {
    const gap = $("[data-gap]", node);
    gap.hidden = false;
    gap.textContent = chain.live_gap;
  }
  const track = trackText(chain.forecast);
  if (track) {
    const t = $("[data-track]", node);
    t.hidden = false;
    t.textContent = track;
  }
  if (chain.stale.length) {
    const list = $("[data-stale]", node);
    list.hidden = false;
    list.replaceChildren(...chain.stale.map((s) => el("li", { text: s })));
    $(".card-top", node).append(el("span", { class: "pill stale", text: "Stale data" }));
  }

  const btn = $("[data-toggle]", node);
  const detail = $("[data-detail]", node);
  const detailId = `detail-${chain.id}`;
  detail.id = detailId;
  btn.setAttribute("aria-controls", detailId);
  let chart = null;
  btn.addEventListener("click", () => {
    const open = btn.getAttribute("aria-expanded") !== "true";
    btn.setAttribute("aria-expanded", String(open));
    btn.textContent = open ? "Hide chart" : "Show chart";
    node.classList.toggle("open", open);
    detail.hidden = !open;
    if (open && !chart) chart = renderDetail(chain, detail);
  });
  return node;
}

function render() {
  charts.forEach((c) => c.destroy());
  charts.clear();
  const root = $("#buckets");
  const chains = filterChains(DATA.chains, group);
  const sections = [];
  for (const b of BUCKETS) {
    const items = sortChains(chains.filter((c) => c.kind === b.kind));
    if (!items.length && !b.empty) continue;
    const id = `bucket-${b.kind}`;
    sections.push(
      el(
        "section",
        { class: "bucket", "data-kind": b.kind, "aria-labelledby": id },
        el(
          "h2",
          { id },
          el("span", { class: "marker", "aria-hidden": "true" }),
          b.title,
          el("span", { class: "count", text: String(items.length) }),
        ),
        el("p", { class: "bucket-note", text: b.note }),
        items.length ? el("div", { class: "grid" }, ...items.map(card)) : el("p", { class: "empty", text: b.empty }),
      ),
    );
  }
  root.replaceChildren(...sections);
}

function renderFilters() {
  const nav = $("#filters");
  const counts = groupCounts(DATA.chains, DATA.groups);
  nav.replaceChildren(
    ...counts.map(({ group: g, count }) => {
      const b = el(
        "button",
        { type: "button", "data-group": g, "aria-pressed": String(g === group) },
        g,
        el("span", { class: "count", text: String(count) }),
      );
      b.addEventListener("click", () => {
        group = g;
        saveGroup(g);
        nav.querySelectorAll("button").forEach((x) => x.setAttribute("aria-pressed", String(x === b)));
        render();
      });
      return b;
    }),
  );
}

function renderHero() {
  $("#hero-title").textContent = heroSentence(DATA.chains, DATA.horizon_months);
  $("#hero-detail").textContent = heroDetail(DATA.chains, DATA.horizon_months);
  const stamp = $("#updated");
  stamp.textContent = fmtUpdated(DATA.generated_at);
  stamp.title = new Date(DATA.generated_at).toUTCString();
}

function showError(message) {
  $("#hero-title").textContent = "The latest prices didn’t load.";
  $("#hero-detail").textContent = "";
  $("#updated").textContent = "Data unavailable";
  $("#buckets").replaceChildren(
    el("p", { class: "notice error", role: "alert", text: `${message} Reload the page to try again.` }),
  );
}

async function main() {
  try {
    if (!window.Chart) throw new Error("The chart library didn’t load.");
    const res = await fetch("/data.json", { cache: "no-store" });
    if (!res.ok) throw new Error(`The data request failed (HTTP ${res.status}).`);
    DATA = await res.json();
    const saved = readGroup();
    if (saved && (saved === "All" || DATA.groups.includes(saved))) group = saved;
    renderHero();
    renderFilters();
    render();
    window.matchMedia("(prefers-color-scheme: dark)").addEventListener?.("change", render);
  } catch (err) {
    showError(err.message);
  }
}

main();
