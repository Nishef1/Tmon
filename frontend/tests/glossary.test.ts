import { readFileSync, readdirSync, statSync } from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";
import { GLOSSARY, GLOSSARY_KEYS, featureInfo, glossaryEntry } from "@/lib/glossary";

function sources(dir: string): string[] {
  return readdirSync(dir).flatMap((f) => {
    const p = path.join(dir, f);
    if (statSync(p).isDirectory()) return sources(p);
    return /\.tsx$/.test(f) ? [p] : [];
  });
}

/** Terms of docs/glossary.md: first column of tables, and comma lists outside parentheses. */
function docTerms(md: string): string[] {
  const out: string[] = [];
  for (const raw of md.split(/\r?\n/)) {
    const line = raw.trim();
    if (!line || line.startsWith("#") || line.startsWith("قالب")) continue;
    if (line.startsWith("|")) {
      const cell = line.split("|")[1].trim();
      if (cell && cell !== "واژه" && !/^-+$/.test(cell)) out.push(cell);
      continue;
    }
    let depth = 0;
    let cur = "";
    for (const ch of line.replace(/\.$/, "")) {
      if (ch === "(") depth++;
      if (ch === ")") depth--;
      if (depth === 0 && (ch === "،" || ch === "؛")) {
        out.push(cur.trim());
        cur = "";
      } else cur += ch;
    }
    out.push(cur.trim());
  }
  return out.filter(Boolean);
}

describe("glossary", () => {
  it("has an entry for every term in docs/glossary.md", () => {
    const md = readFileSync(path.resolve(__dirname, "../../docs/glossary.md"), "utf8");
    const terms = docTerms(md);
    expect(terms.length).toBeGreaterThan(100);
    const names = new Set(
      GLOSSARY_KEYS.flatMap((k) => {
        const e = glossaryEntry(k)!;
        return [e.fa, ...(e.aliases ?? [])];
      }),
    );
    const missing = terms.filter((t) => !names.has(t));
    expect(missing).toEqual([]);
  });

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
