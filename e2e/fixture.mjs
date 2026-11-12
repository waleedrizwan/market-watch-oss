// Builds a deterministic data.json covering every card state the dashboard can show.
import { writeFileSync } from "node:fs";

const DAY = 86_400_000;
const today = new Date();
const iso = (d) => d.toISOString().slice(0, 10);
const monthly = (n, f) =>
  Array.from({ length: n }, (_, i) => {
    const d = new Date(Date.UTC(today.getUTCFullYear(), today.getUTCMonth() - (n - i), 1));
    return [iso(d), Math.round(f(i) * 1000) / 1000];
  });
const dailyPts = (n, f) => Array.from({ length: n }, (_, i) => [iso(new Date(today - (n - 1 - i) * DAY)), f(i)]);

function series(id, label, role, unit, points, extra = {}) {
  const last = points.at(-1);
  return {
    id, label, role, unit, frequency: extra.frequency ?? "monthly",
    latest: last ? { date: last[0], value: last[1] } : null,
    changes: extra.changes ?? { "30d": 1.2, "90d": -3.4, "1y": 12.5 },
    change_labels: extra.frequency === "daily" ? { "30d": "30d", "90d": "90d", "1y": "1y" } : { "30d": "1m", "90d": "3m", "1y": "12m" },
    history_days: extra.history_days ?? 3650,
    stale: extra.stale ?? null,
    points,
  };
}

const track = (hits, flags) => ({ corr: 0.5, flags, hits, checks: 24 });
const fc = (pending, extra = {}) => ({ ok: true, pending_pct: pending, passthrough_pct: 60, half_lag_months: 2, r2_gain: 0.3, n_months: 200, track: track(5, 6), ...extra });

const data = {
  generated_at: new Date(Date.now() - 2 * 3_600_000).toISOString(),
  horizon_months: 6,
  groups: ["Electronics", "Food", "Energy"],
  chains: [
    { id: "beef", title: "Beef", group: "Food", kind: "rise", headline: "Likely to rise about 7% over the next 6 months.", reason: "Cattle: up 30% over 12 months.", forecast: fc(7.2), live_gap: null, stale: [], series: ["cattle", "beef_retail"], links: [{ label: "FRED: beef", url: "https://fred.stlouisfed.org/" }] },
    { id: "gas", title: "Gasoline", group: "Energy", kind: "fall", headline: "Likely to fall about 5% over the next 6 months.", reason: "Crude: down 20% over 12 months.", forecast: fc(-5.1), live_gap: null, stale: [], series: ["wti", "gas_retail"], links: [] },
    { id: "eggs", title: "Eggs", group: "Food", kind: "fast", headline: "Store price follows the upstream price within weeks.", reason: "Farm eggs: down 66% over 12 months.", forecast: fc(1, { track: null, half_lag_months: 0 }), live_gap: null, stale: [], series: ["farm_eggs", "eggs_retail"], links: [] },
    { id: "bread", title: "Bread", group: "Food", kind: "steady", headline: "No big move expected over the next 6 months (+1.0%).", reason: "Wheat: flat.", forecast: fc(1.0), live_gap: null, stale: [], series: ["wheat", "bread_retail"], links: [] },
    {
      id: "computers", title: "Computers, RAM & SSDs", group: "Electronics", kind: "weak",
      headline: "The upstream price hasn't reliably predicted this store price in the past, so no forecast.",
      reason: "Chip makers' prices (PPI): down 2% over 12 months.", forecast: fc(-2.1, { track: track(0, 0) }),
      live_gap: "Live chip prices: not enough history yet (DDR5 16Gb chip spot has 16 of 90 days).",
      stale: ["512Gb TLC NAND wafer spot: last fetch failed: RuntimeError: item '512Gb TLC' not in table 'Wafer Spot Price'"],
      series: ["ppi_semis", "cpi_computers", "ddr5_chip", "nand_wafer"],
      links: [{ label: "DRAMeXchange", url: "https://www.dramexchange.com/" }],
    },
  ],
  series: {
    cattle: series("cattle", "Cattle, world price", "upstream", "USD/kg", monthly(120, (i) => 4 + i * 0.02)),
    beef_retail: series("beef_retail", "Ground beef", "retail", "USD/lb", monthly(120, (i) => 3 + i * 0.01)),
    wti: series("wti", "Crude oil (WTI)", "upstream", "USD/bbl", monthly(120, (i) => 70 + Math.sin(i / 6) * 10)),
    gas_retail: series("gas_retail", "Gasoline", "retail", "USD/gal", monthly(120, (i) => 3 + Math.sin((i - 1) / 6) * 0.4)),
    farm_eggs: series("farm_eggs", "Farm egg prices (PPI)", "upstream", "index", monthly(120, (i) => 100 + Math.sin(i / 3) * 40)),
    eggs_retail: series("eggs_retail", "Eggs (dozen)", "retail", "USD", monthly(120, (i) => 2 + Math.sin(i / 3) * 0.5)),
    wheat: series("wheat", "Wheat, world price", "upstream", "USD/t", monthly(120, () => 250)),
    bread_retail: series("bread_retail", "White bread", "retail", "USD/lb", monthly(120, (i) => 1.5 + i * 0.005)),
    ppi_semis: series("ppi_semis", "Chip makers' prices (PPI)", "upstream", "index", monthly(120, (i) => 80 - i * 0.05)),
    cpi_computers: series("cpi_computers", "Computers & peripherals", "retail", "index", monthly(120, (i) => 60 + i * 0.03)),
    ddr5_chip: series("ddr5_chip", "DDR5 16Gb chip spot", "upstream", "USD/chip", dailyPts(16, (i) => 40 + i), { frequency: "daily", changes: { "30d": null, "90d": null, "1y": null }, history_days: 16 }),
    nand_wafer: series("nand_wafer", "512Gb TLC NAND wafer spot", "upstream", "USD/die-equiv", [[iso(new Date(today - 40 * DAY)), 4.444]], {
      frequency: "weekly", changes: { "30d": null, "90d": null, "1y": null }, history_days: 0,
      stale: "last fetch failed: RuntimeError: item '512Gb TLC' not in table 'Wafer Spot Price'",
    }),
  },
};

writeFileSync(process.argv[2], JSON.stringify(data));
console.log(`fixture written to ${process.argv[2]}`);
