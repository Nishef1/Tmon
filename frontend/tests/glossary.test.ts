import { readFileSync, readdirSync, statSync } from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";
import { GLOSSARY, GLOSSARY_KEYS, featureInfo } from "@/lib/glossary";

function sources(dir: string): string[] {
  return readdirSync(dir).flatMap((f) => {
    const p = path.join(dir, f);
    if (statSync(p).isDirectory()) return sources(p);
    return /\.tsx$/.test(f) ? [p] : [];
  });
}

describe("glossary", () => {
  it("has the full entry shape for every term", () => {
    for (const k of GLOSSARY_KEYS) {
      const e = GLOSSARY[k];
      expect(e.fa.length, k).toBeGreaterThan(1);
      expect(e.en.length, k).toBeGreaterThan(1);
      expect(e.definition.length, k).toBeGreaterThan(10);
      expect(e.why.length, k).toBeGreaterThan(5);
      expect(e.limits.length, k).toBeGreaterThan(0);
    }
  });

  it("only relates to terms that exist", () => {
    for (const k of GLOSSARY_KEYS) {
      for (const r of (GLOSSARY[k] as { related?: readonly string[] }).related ?? []) {
        expect(GLOSSARY_KEYS, `${k} -> ${r}`).toContain(r);
      }
    }
  });

  it("maps every model feature to an existing term", () => {
    for (const f of [
      "rsi_14",
      "ret_5",
      "sma_20_dist",
      "ema_50_dist",
      "roc_10",
      "unknown_feature",
    ]) {
      expect(GLOSSARY_KEYS).toContain(featureInfo(f).term);
    }
    expect(featureInfo("ret_5").label).toBe("بازده 5 روزه");
    expect(featureInfo("unknown_feature").label).toBe("unknown_feature");
  });

  it("is used only through terms that exist (every <Num term=...> resolves)", () => {
    const root = path.resolve(__dirname, "..");
    const used = new Set<string>();
    for (const dir of ["app", "components"]) {
      for (const file of sources(path.join(root, dir))) {
        const text = readFileSync(file, "utf8");
        for (const m of text.matchAll(/term="([a-z_]+)"/g)) used.add(m[1]);
        for (const m of text.matchAll(/\["[^"]+", "([a-z_]+)", /g)) used.add(m[1]);
      }
    }
    expect(used.size).toBeGreaterThan(10);
    for (const t of used) expect(GLOSSARY_KEYS, t).toContain(t);
  });
});
