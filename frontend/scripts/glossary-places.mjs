// Which pages show each glossary term, found by reading the `term="..."` props of the source.
// `node scripts/glossary-places.mjs`          writes lib/glossary-places.json (runs before build)
// `node scripts/glossary-places.mjs --check`  exits 1 when the committed file is out of date
import { readdirSync, readFileSync, statSync, writeFileSync } from "node:fs";
import { join } from "node:path";

// First match wins: a source file path (forward slashes) -> the page a reader finds it on.
const PLACES = [
  [/components\/model\/|app\/model\//, { label: "صفحهٔ مدل", href: "/model" }],
  [/components\/portfolio\/|app\/portfolios\//, { label: "پرتفوی", href: "/portfolios" }],
  [/components\/IndustryTable|app\/industries\//, { label: "صنایع و نمادها", href: "/industries" }],
  [/components\/compare\/|app\/compare\//, { label: "مقایسه", href: "/compare" }],
  [/app\/market\//, { label: "بازار", href: "/market" }],
  [/app\/picks\/|TrackBuy|DeletePick/, { label: "خریدهای من", href: "/picks" }],
  [
    /components\/today\/|TradableRanking|ZoneTables|OutsideBasket|ExposureCard|app\/page/,
    { label: "امروز بازار", href: "/" },
  ],
  [
    /components\/(stock|entry|book)\/|SymbolDashboard|TechnicalCard|TurningCard|PeersCard|DriversCard|CandleChart|app\/instruments\//,
    { label: "صفحهٔ هر نماد", href: "/screener" },
  ],
];
const TERM = /\bterm[=:]\s*\{?\s*"([a-z0-9_]+)"/g;

function sources(dir) {
  return readdirSync(dir).flatMap((n) => {
    const p = join(dir, n);
    if (statSync(p).isDirectory()) return sources(p);
    return p.endsWith(".tsx") ? [p] : [];
  });
}

export function scan(root = ".") {
  const out = {};
  for (const sub of ["app", "components"]) {
    for (const file of sources(join(root, sub)).sort()) {
      const path = file.replaceAll("\\", "/");
      const place = PLACES.find(([re]) => re.test(path))?.[1];
      if (!place) continue;
      for (const m of readFileSync(file, "utf8").matchAll(TERM)) {
        const list = (out[m[1]] ??= []);
        if (!list.some((p) => p.href === place.href)) list.push(place);
      }
    }
  }
  return Object.fromEntries(Object.entries(out).sort(([a], [b]) => a.localeCompare(b)));
}

const target = "lib/glossary-places.json";
if (process.argv[1]?.endsWith("glossary-places.mjs")) {
  const fresh = `${JSON.stringify(scan(), null, 2)}\n`;
  if (process.argv.includes("--check")) {
    let current = "";
    try {
      current = readFileSync(target, "utf8");
    } catch {
      // missing counts as out of date
    }
    if (current !== fresh) {
      console.error(`${target} is out of date: run node scripts/glossary-places.mjs`);
      process.exit(1);
    }
  } else {
    writeFileSync(target, fresh);
  }
}
