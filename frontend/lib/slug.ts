/** The page address of an instrument: ``/instruments/<industry>/<symbol>``. */
export function slugPath(s: { sector: string; symbol: string }): string {
  return `/instruments/${encodeURIComponent(s.sector)}/${encodeURIComponent(s.symbol)}`;
}
