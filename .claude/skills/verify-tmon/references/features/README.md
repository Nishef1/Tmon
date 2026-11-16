# Feature map

Each file covers four things: what exists, how a user reaches it, how to drive it, and what
usually lies. Old routes redirect: `/ranking` → `/`, `/screener` → `/industries`,
`/accuracy`, `/calibration` and `/history` → `/model#…`.

| Area | Pages | Main API | File |
| --- | --- | --- | --- |
| Today and ranking | `/` | `/v2/ranking`, `/market/overview` | [today-and-ranking.md](today-and-ranking.md) |
| One symbol | `/instruments/[id]` | `/instruments/{id}/dashboard`, `book`, `entry`, `live`, `agm` | [instrument.md](instrument.md) |
| Market, industries, compare | `/market`, `/industries`, `/compare` | `/market/overview`, `/screener`, `/compare`, `/funds`, `/search` | [market.md](market.md) |
| Model and accuracy | `/model` | `/research/*`, `/metrics/*`, `/signals/history`, `/recommendations` | [model.md](model.md) |
| Portfolios and picks | `/portfolios`, `/portfolios/[id]`, `/picks` | `/portfolios/*`, `/picks` | [portfolios-and-picks.md](portfolios-and-picks.md) |
| Glossary | `/glossary`, `/glossary/[term]` | none (static) | [glossary.md](glossary.md) |

## Sweep order

For a full pass, or when unsure what a change touches, go in this order. Each step needs the one
before it to be healthy: doctor → `/` → one buy-zone symbol and one excluded symbol on
`/instruments/[id]` → `/market` → `/industries` → `/model` → `/portfolios/[id]` → `/picks` →
`/glossary`.
