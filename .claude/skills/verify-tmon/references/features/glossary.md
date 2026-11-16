# Glossary (`/glossary`, `/glossary/[term]`)

**What exists:** one entry per term in `docs/glossary.md` (`frontend/lib/glossary.ts` and
`glossary-reference.ts`). Pages are static (`dynamicParams = false`). Numbers across the site link
to their entry.

**How a user reaches it:** the navigation, or the ⓘ next to any number.

**How to drive:** after adding a term, open `/glossary/<key>` and one page where the term appears,
and check that the link lands on the right entry. `frontend/tests/glossary.test.ts` checks
coverage, not wording.

**What usually lies:** a new term in the UI with no entry. The test catches terms that are in
`docs/glossary.md`, but not a term that is only in a component.
