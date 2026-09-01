# AGNT ECO

**Place-based ecological reasoning agents whose defining property is that groundedness is a hard
constraint.** Each agent is bound to a real place — a river, an estuary, a lake, a forest, a sea —
reasons over a species knowledge graph, reads that place's live sensors, and may assert *only what it can
trace to a source*. Everything else is labelled as hypothesis, as attention, or as unresolved.

Project: [agnt.eco](https://agnt.eco) · Embedding module: [RUNA](https://runa.agnt.eco)

Most conversational agents are built to pass as human. AGNT ECO is built the other way around: an agent
is a *standpoint* — a place speaking from within itself — and the point is not that it is fluent but that
it is constrained. Every claim it makes as fact is tied to a verifiable source; a correction to a
published claim is a first-class, logged event rather than a hidden edit.

## What is in this repository

This repo holds the **reusable method layer** — the parts meant to be adopted and built on. It does **not**
contain the live deployment (the nine running place-agents, their accumulated data and corpus, the
ingestion pipelines, and the web interface); that is described as a reference deployment, not released here.

| Path | What it is |
|------|------------|
| [`src/verification/`](src/verification/) | The **verification tier** — the framework's central method. `rubric_judge.py` (a local-model verifier that decomposes a claim into checkable assertions and scores each against its sources), plus `claimseal.py` / `factguard.py` / `lineage.py` (a fact's identity is a hash of the claim, edits/deletes are refused, and a correction *supersedes* the old fact while staying visible). |
| [`src/parallax/`](src/parallax/) | **Parallax** — reads one environmental value through many co-located species' sourced physiological bands, surfacing the case where the same number is a *barrier* to one organism and a *home* to another. |
| [`src/grounding/`](src/grounding/SCHEMA.md) | The property-graph schema (species → `DOCUMENTED_IN` → source; fact → `GROUNDED_IN` → passage) that makes grounding mechanical. |
| [`examples/reference_agent.py`](examples/reference_agent.py) | A minimal, runnable agent over one synthetic place — demonstrates the tier discipline and Parallax with no model and no external data. |
| [`data/synthetic_sample/`](data/synthetic_sample/) | Fictional species, bands, and facts so the example runs standalone. |

## Quickstart

```bash
python examples/reference_agent.py
```

No installation and no model are required to run the example — the core is Python standard library only.
It prints (1) the agent answering only what it can ground, labelling hypotheses and observations and
refusing the unresolved; and (2) a Parallax reading in which 20 °C is simultaneously a *barrier*, an
*optimal*, and a *safe* value to three co-located species.

## The verification tier

Knowledge is held in three explicit classes:

- **Verified, sourced facts** at or above a confidence bar — the only claims an agent may assert as fact,
  and the only ones that carry a citation.
- **Hypotheses** — model-derived relational predictions and trait inferences — held separately, never
  asserted as fact.
- **Observations** — citizen-science and proxy signals — treated as *attention*, a reason to look, not truth.

`rubric_judge.py` runs on a **local open-weight model at zero paid-API cost** (set `OLLAMA_URL` to any
OpenAI/Ollama-compatible endpoint). For a claim it first writes a task-specific rubric enumerating the
individual checkable assertions inside the claim, then scores each against the provided sources across
several samples — the method that stops a fluent model from waving a subtly-wrong claim through whole.

## Parallax

```python
from parallax import parallax
result = parallax(readers, value=20)   # readers: species, each with its sourced meaning-bands
result["hard_divergence"]              # True when a value is severe to one reader and benign to another
```

Species are compared only within the same unit, so incommensurable measurements never form a false
divergence. Parallax is deliberately inert without sourced per-species bands — the value is in the data,
not the code.

## Related deposits

- **RUNA-2** — typed biosemiotic knowledge-graph embedding. [doi:10.5281/zenodo.21182367](https://doi.org/10.5281/zenodo.21182367) · CC-BY-4.0
- **Parallax** — divergence between Umwelten. [doi:10.5281/zenodo.21390486](https://doi.org/10.5281/zenodo.21390486)
- **Nine waters, one drought** — a fact-audited multi-agent account. [doi:10.5281/zenodo.22176502](https://doi.org/10.5281/zenodo.22176502)
- **State of the system** — [doi:10.5281/zenodo.22176512](https://doi.org/10.5281/zenodo.22176512)

## Citation & licence

Please cite via [`CITATION.cff`](CITATION.cff). Released under the [MIT License](LICENSE). RUNA's deposited
artifact is CC-BY-4.0.
