import { describe, expect, it } from "vitest";
// @ts-expect-error plain JS module served to the browser
import * as lib from "../site/lib.js";

const chain = (kind: string, extra: Record<string, unknown> = {}) => ({
  id: kind, title: kind, group: "Food", kind, forecast: { ok: true, pending_pct: 0, track: null }, ...extra,
});

describe("indexed", () => {
  it("indexes each series to 100 at its first point in range", () => {
    const a = { points: [["2020-01-01", 50], ["2026-01-01", 80], ["2026-06-01", 120]] };
    const b = { points: [["2026-02-01", 10], ["2026-03-01", 15]] };
    const [ia, ib] = lib.indexed([a, b], "1Y");
    expect(ia.map((p: { y: number }) => p.y)).toEqual([100, 150]);
    expect(ib.map((p: { y: number }) => p.y)).toEqual([100, 150]);
    expect(ia[1]).toMatchObject({ raw: 120, date: "2026-06-01" });
  });

  it("uses the whole history for All", () => {
    const a = { points: [["2000-01-01", 1], ["2026-01-01", 3]] };
    expect(lib.indexed([a], "All")[0].map((p: { y: number }) => p.y)).toEqual([100, 300]);
  });

  it("handles empty series and a zero base", () => {
    expect(lib.indexed([{ points: [] }], "3Y")).toEqual([[]]);
    const z = { points: [["2026-01-01", 0], ["2026-02-01", 2], ["2026-03-01", 4]] };
    expect(lib.indexed([z], "1Y")[0].map((p: { y: number }) => p.y)).toEqual([0, 100, 200]);
  });
});

describe("formatting", () => {
  it("formats percentages with a real minus sign", () => {
    expect(lib.fmtPct(3.25)).toBe("+3.3%");
    expect(lib.fmtPct(-3.6)).toBe("−3.6%");
    expect(lib.fmtPct(0)).toBe("0.0%");
    expect(lib.fmtPct(null)).toBe("—");
    expect(lib.pctClass(1)).toBe("pos");
    expect(lib.pctClass(-1)).toBe("neg");
    expect(lib.pctClass(undefined)).toBe("na");
  });

  it("formats numbers by magnitude", () => {
    expect(lib.fmtNum(2.63)).toBe("2.630");
    expect(lib.fmtNum(12.345)).toBe("12.35");
    expect(lib.fmtNum(1265.62)).toBe("1,265.6");
    expect(lib.fmtNum(undefined)).toBe("—");
  });

  it("formats dates and the update stamp", () => {
    expect(lib.fmtDate("2026-11-03")).toBe("3 Nov 2026");
    expect(lib.fmtDate("2026-11-03T18:00:00Z", { year: false })).toBe("3 Nov");
    const now = new Date("2026-11-12T12:00:00Z");
    expect(lib.fmtUpdated("2026-11-12T11:30:00Z", now)).toBe("Updated less than an hour ago");
    expect(lib.fmtUpdated("2026-11-11T23:00:00Z", now)).toBe("Updated 13 h ago");
    expect(lib.fmtUpdated("2026-11-08T12:00:00Z", now)).toBe("Updated 4 days ago");
    expect(lib.fmtUpdated("garbage", now)).toBe("Update time unknown");
  });
});

describe("hero copy", () => {
  it("says nothing big is coming when nothing is flagged", () => {
    expect(lib.heroSentence([chain("steady"), chain("weak")], 6)).toBe("No big store-price moves expected in the next 6 months.");
  });

  it("counts rises and falls with correct grammar", () => {
    expect(lib.heroSentence([chain("rise")], 6)).toBe("1 thing is likely to cost more within 6 months.");
    expect(lib.heroSentence([chain("rise"), chain("rise"), chain("fall")], 6)).toBe(
      "2 things are likely to cost more, and 1 is likely to cost less within 6 months.",
    );
    expect(lib.heroSentence([chain("fall"), chain("fall")], 3)).toBe("2 things are likely to cost less within 3 months.");
  });

  it("summarises the watch list", () => {
    const text = lib.heroDetail([chain("steady"), chain("weak"), chain("weak")], 6);
    expect(text).toContain("Watching 3 product chains");
    expect(text).toContain("1 has a reliable link");
    expect(text).toContain("2 have no reliable signal");
  });
});

describe("cards and buckets", () => {
  it("sorts by size of pending move, then title", () => {
    const sorted = lib.sortChains([
      chain("steady", { title: "B", forecast: { pending_pct: 1 } }),
      chain("steady", { title: "A", forecast: { pending_pct: -5 } }),
      chain("steady", { title: "C", forecast: { pending_pct: 1 } }),
      chain("weak", { title: "D", forecast: { ok: false } }),
    ]);
    expect(sorted.map((c: { title: string }) => c.title)).toEqual(["A", "B", "C", "D"]);
  });

  it("filters by group and counts per group", () => {
    const list = [chain("rise", { group: "Food" }), chain("fall", { group: "Energy" })];
    expect(lib.filterChains(list, "All")).toHaveLength(2);
    expect(lib.filterChains(list, "Energy")).toHaveLength(1);
    expect(lib.groupCounts(list, ["Food", "Energy", "Home"])).toEqual([
      { group: "All", count: 2 }, { group: "Food", count: 1 }, { group: "Energy", count: 1 }, { group: "Home", count: 0 },
    ]);
  });

  it("shows a big number only for chains with a forecast", () => {
    expect(lib.bigNumber(chain("rise", { forecast: { pending_pct: 7.2 } }), 6)).toEqual({ value: "+7.2%", note: "expected in the next 6 months" });
    expect(lib.bigNumber(chain("weak", { forecast: { pending_pct: 3 } }), 6)).toBeNull();
    expect(lib.bigNumber(chain("fast"), 6)).toBeNull();
    expect(lib.bigNumber(chain("steady", { forecast: { ok: false } }), 6)).toBeNull();
  });

  it("describes the backtest track record", () => {
    expect(lib.trackText({ ok: true, track: { flags: 11, hits: 10 } })).toBe(
      "Track record over the last ~6 years, tested out of sample: called the direction right 10 of 11 times it flagged a move.",
    );
    expect(lib.trackText({ ok: true, track: { flags: 0, hits: 0 } })).toContain("never flagged a big move");
    expect(lib.trackText({ ok: true, track: null })).toBe("");
    expect(lib.trackText({ ok: false })).toBe("");
  });

  it("has a label for every bucket", () => {
    expect(Object.keys(lib.KIND_LABEL)).toEqual(["rise", "fall", "fast", "steady", "weak"]);
  });
});
