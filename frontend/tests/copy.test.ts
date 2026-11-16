import { readdirSync, readFileSync, statSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";

/** English jargon that must be written in Persian wherever a user can read it. Product names and
 *  library names (GBM, Brier) are allowed; everyday English words are not. A word glued to
 *  a code identifier (`r.drawdown`, `max_drawdown`, `d.seeds.length`) is code, not copy. */
const BANNED =
  /(?<![.\w/])(baseline|seeds?|walk-forward|drawdown|stop[- ]loss|take[- ]profit|hit[- ]rate)(?![\w(,)."])/i;
const ROOTS = ["app", "components", "lib"];
const SKIP = /api-schema|glossary-reference/;

function files(dir: string): string[] {
  return readdirSync(dir).flatMap((n) => {
    const p = join(dir, n);
    if (statSync(p).isDirectory()) return n === "node_modules" ? [] : files(p);
    return /\.tsx?$/.test(n) && !SKIP.test(p) ? [p] : [];
  });
}

describe("user-facing copy", () => {
  it("does not mix untranslated English jargon into Persian text", () => {
    const hits: string[] = [];
    for (const root of ROOTS) {
      for (const f of files(root)) {
        readFileSync(f, "utf8")
          .split("\n")
          .forEach((line, i) => {
            const t = line.trim();
            if (t.startsWith("//") || t.startsWith("*") || t.startsWith("/*")) return;
            if (/[؀-ۿ]/.test(line) && BANNED.test(line)) {
              hits.push(`${f}:${i + 1}: ${t.slice(0, 90)}`);
            }
          });
      }
    }
    expect(hits).toEqual([]);
  });
});
