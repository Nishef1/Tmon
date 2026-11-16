import data from "./glossary-places.json";

/** A page of the site where a glossary term is shown as a number or a label. */
export type Place = { label: string; href: string };

const PLACES: Record<string, Place[]> = data;

/** Pages that show a glossary term. The JSON is regenerated from the `term="..."` props of the
 *  source before every build (`scripts/glossary-places.mjs`), so it follows the code. */
export function placesFor(term: string): Place[] {
  return PLACES[term] ?? [];
}

export function allPlaces(): Record<string, Place[]> {
  return PLACES;
}
