/** The page address of an instrument: ``/instruments/<industry>/symbol/<symbol>``.
 *
 *  The Latin word between the two Persian names is on purpose: the address bar lays out two
 *  Persian segments joined by "/" as one right-to-left run and shows the symbol before the
 *  industry. A left-to-right word between them keeps the industry first. */
export function slugPath(s: { sector: string; symbol: string }): string {
  return `/instruments/${encodeURIComponent(s.sector)}/symbol/${encodeURIComponent(s.symbol)}`;
}
