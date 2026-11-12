/** Text matcher that ignores the invisible bidi isolates numbers carry (lib/format.ts `ltr`). */
export const text = (want: string) => (content: string) => content.replace(/[⁦⁩]/g, "") === want;
