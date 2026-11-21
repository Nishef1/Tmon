/** The page address of an instrument: ``/instruments/<industry>/symbol/<symbol>``.
 *
 *  The Latin word between the two Persian names is on purpose: the address bar lays out two
 *  Persian segments joined by "/" as one right-to-left run and shows the symbol before the
 *  industry. A left-to-right word between them keeps the industry first. */
/** A member symbol's page address; the id address still works but goes through a redirect. */
export function memberPath(
  d: { slug: string },
  m: { instrument_id: number; symbol_slug: string },
): string {
  return d.slug && m.symbol_slug
    ? slugPath({ sector: d.slug, symbol: m.symbol_slug })
    : `/instruments/${m.instrument_id}`;
}

export function slugPath(s: { sector: string; symbol: string }): string {
  return `/instruments/${encodeURIComponent(s.sector)}/symbol/${encodeURIComponent(s.symbol)}`;
}
