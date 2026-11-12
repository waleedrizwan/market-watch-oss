// Pure helpers for the dashboard. No DOM access, so they're unit-tested in Node.

export const RANGES = { "1Y": 366, "3Y": 1096, "10Y": 3653, All: null };
export const DEFAULT_RANGE = "3Y";

export const BUCKETS = [
  { kind: "rise", title: "Likely to rise", note: "Upstream already moved up and stores usually follow. Buying sooner may pay off.", empty: "Nothing is flagged to rise right now." },
  { kind: "fall", title: "Likely to fall", note: "Upstream already dropped and stores usually follow. Waiting may pay off.", empty: "Nothing is flagged to fall right now." },
  { kind: "fast", title: "Moves fast", note: "Store prices track upstream within weeks, so there's no early warning. The upstream move itself is the signal." },
  { kind: "steady", title: "Steady", note: "A reliable link, but no big move pending." },
  { kind: "weak", title: "No reliable signal", note: "The upstream price hasn't predicted this store price well in the past, so there's no forecast. The charts are still useful context." },
];

export const KIND_LABEL = Object.fromEntries(BUCKETS.map((b) => [b.kind, b.title]));

const DAY_MS = 86_400_000;
const toTime = (d) => Date.parse(`${d}T00:00:00Z`);

/**
 * Index each series to 100 at its first point inside the range, so lines with
 * different units share one axis. The window ends at the newest point of any
 * series in the chart.
 */
export function indexed(seriesList, rangeKey) {
  const days = RANGES[rangeKey];
  const ends = seriesList.filter((s) => s.points.length).map((s) => toTime(s.points.at(-1)[0]));
  const latest = ends.length ? Math.max(...ends) : 0;
  const start = days == null ? -Infinity : latest - days * DAY_MS;
  return seriesList.map((s) => {
    const pts = s.points.filter((p) => toTime(p[0]) >= start);
    const base = pts.find((p) => p[1] !== 0)?.[1];
    if (!base) return [];
    return pts.map(([d, v]) => ({ x: toTime(d), y: Math.round((v / base) * 10000) / 100, raw: v, date: d }));
  });
}

export function fmtPct(v, digits = 1) {
  if (v == null || !Number.isFinite(v)) return "—";
  const sign = v > 0 ? "+" : v < 0 ? "−" : "";
  return `${sign}${Math.abs(v).toFixed(digits)}%`;
}

export function pctClass(v) {
  if (v == null || !Number.isFinite(v)) return "na";
  return v > 0 ? "pos" : v < 0 ? "neg" : "";
}

export function fmtNum(v) {
  if (v == null || !Number.isFinite(v)) return "—";
  const a = Math.abs(v);
  const digits = a >= 100 ? 1 : a >= 10 ? 2 : 3;
  return v.toLocaleString("en-US", { minimumFractionDigits: digits, maximumFractionDigits: digits });
}

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

export function fmtDate(iso, { year = true } = {}) {
  const [y, m, d] = iso.slice(0, 10).split("-").map(Number);
  return year ? `${d} ${MONTHS[m - 1]} ${y}` : `${d} ${MONTHS[m - 1]}`;
}

export function fmtUpdated(iso, now = new Date()) {
  const t = Date.parse(iso);
  if (!Number.isFinite(t)) return "Update time unknown";
  const hours = (now.getTime() - t) / 3_600_000;
  const when =
    hours < 1 ? "less than an hour ago" : hours < 36 ? `${Math.round(hours)} h ago` : `${Math.round(hours / 24)} days ago`;
  return `Updated ${when}`;
}

/** Sort a bucket: biggest pending move first, then by title. */
export function sortChains(chains) {
  return [...chains].sort(
    (a, b) =>
      Math.abs(b.forecast?.pending_pct ?? 0) - Math.abs(a.forecast?.pending_pct ?? 0) || a.title.localeCompare(b.title),
  );
}

export function filterChains(chains, group) {
  return group === "All" ? chains : chains.filter((c) => c.group === group);
}

/** The large sentence at the top of the page. */
export function heroSentence(chains, horizon) {
  const rise = chains.filter((c) => c.kind === "rise").length;
  const fall = chains.filter((c) => c.kind === "fall").length;
  const n = (k, one, many) => (k === 1 ? one : many.replace("#", k));
  if (!rise && !fall) return `No big store-price moves expected in the next ${horizon} months.`;
  const parts = [];
  if (rise) parts.push(n(rise, "1 thing is likely to cost more", "# things are likely to cost more"));
  if (fall) parts.push(n(fall, rise ? "1 is likely to cost less" : "1 thing is likely to cost less", rise ? "# are likely to cost less" : "# things are likely to cost less"));
  return `${parts.join(", and ")} within ${horizon} months.`;
}

export function heroDetail(chains, horizon) {
  const count = (k) => chains.filter((c) => c.kind === k).length;
  const have = (n) => `${n} ${n === 1 ? "has" : "have"}`;
  return (
    `Watching ${chains.length} product chains, each pairing a raw-material price with a store price. ` +
    `${have(count("steady"))} a reliable link and nothing pending; ${have(count("weak"))} no reliable signal yet. ` +
    `Forecasts assume upstream prices stay where they are for the next ${horizon} months.`
  );
}

export function trackText(fc) {
  const t = fc?.ok && fc.track;
  if (!t) return "";
  const flagged = t.flags
    ? `called the direction right ${t.hits} of ${t.flags} times it flagged a move`
    : "never flagged a big move";
  return `Track record over the last ~6 years, tested out of sample: ${flagged}.`;
}

/** Text for the big number on a card, or null when there's no forecast to show. */
export function bigNumber(chain, horizon) {
  if (!["rise", "fall", "steady"].includes(chain.kind)) return null;
  const p = chain.forecast?.pending_pct;
  if (p == null) return null;
  return { value: fmtPct(p), note: `expected in the next ${horizon} months` };
}

export function groupCounts(chains, groups) {
  return ["All", ...groups].map((g) => ({ group: g, count: filterChains(chains, g).length }));
}
