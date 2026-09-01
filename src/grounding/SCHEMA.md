# Grounding schema

The full system holds each place's knowledge in a property graph (Neo4j-compatible). This document
describes the model so the verification tier and Parallax can be wired to a real graph; the reference
agent in `examples/` uses a small in-memory stand-in over synthetic JSON instead.

## Nodes

- **Species** — one taxon at one place (`scientific_name`, `place`).
- **Source** — a document (`title`, `doi`/`ref`, `year`).
- **Passage** — a verbatim quotable span extracted from a Source (`text`, `chip`).
- **Fact** — a claim held in the verification tier. Its identity is a hash of the claim text itself
  (`fact_hash`; see `../verification/claimseal.py`), plus `confidence`, `status`, and a `tier`
  (`verified` | `hypothesis` | `observation`).
- **MeaningBand** — a species' sourced physiological band for one signal (`signal`, `unit`,
  `bands_json`, `source`, `confidence`). Consumed by `../parallax/`.

## Edges

- `(:Species)-[:DOCUMENTED_IN]->(:Source)` — the proof link: this species is recorded in this source.
- `(:Fact)-[:GROUNDED_IN]->(:Passage)` — a fact resolves to a specific verbatim passage.
- `(:Passage)-[:FROM]->(:Source)` — provenance of a passage.
- `(:Species)-[:SENSES]->(:MeaningBand)` — the species' sourced tolerance for a signal.
- `(:Fact)-[:SUPERSEDES]->(:Fact)` — a correction: a new fact overturns an earlier one, kept visible
  (see `../verification/lineage.py`).

## The tier as a query

An agent answering a question retrieves candidate passages, and only a `Fact` whose `tier = "verified"`
and whose `confidence` is at or above the bar may license an assertion — and it is asserted with its
`GROUNDED_IN` passage as the citation. Everything else is returned labelled as hypothesis or observation,
or named unresolved. That single rule is what makes grounding mechanical rather than a matter of trust.
