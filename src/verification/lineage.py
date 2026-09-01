#!/usr/bin/env python3
"""Make rewrite lineage visible in the number a reader sees.

Known limitation this addresses: a broken claim is corrected by minting a NEW fact with a fresh
hash and a fresh score, so systematic correction shows up in the aggregate as rising confidence.
A corpus-level average cannot, on its own, distinguish a claim that was always right from one that
is the third attempt at saying something. The lineage is recorded on every rewritten fact (each
carries `derived_from`), but a consumer has to walk it explicitly — it is not reflected in the
confidence number by default.

This computes, for every fact, how far it sits from an original claim, and stores it:

    generation        0 = original, 1 = first rewrite, 2 = a rewrite of a rewrite ...
    lineage_root      the hash of the original claim at the top of the chain
    lineage_chain     every hash between the root and this fact
    supersedes_count  how many claims were retired to arrive at this one

Nothing is penalised automatically — a rewrite is a correction, and correcting well should
not look like failing. But a reader opening a mark should be able to see that the sentence
in front of them is the third attempt at saying something, and no reader could see that
before.

    python3 lineage.py            report only
    python3 lineage.py --write    stamp the properties

Config via env: NEO4J_URI (default bolt://localhost:7687), NEO4J_PASSWORD.
"""
import os, re, sys
from neo4j import GraphDatabase

WRITE = "--write" in sys.argv
drv = GraphDatabase.driver(os.getenv("NEO4J_URI", "bolt://localhost:7687"),
                           auth=("neo4j", os.getenv("NEO4J_PASSWORD", "neo4j")))

with drv.session() as s:
    rows = s.run("""MATCH (f:Fact)
        RETURN f.fact_hash AS h, f.derived_from AS parent, f.agent AS agent,
               f.confidence AS conf""").data()

parent = {r["h"]: r["parent"] for r in rows}
conf = {r["h"]: r["conf"] for r in rows}


def chain_of(h, seen=None):
    """Walk back to the original claim. Guards against a cycle."""
    seen = seen or set()
    out = []
    cur = parent.get(h)
    while cur and cur not in seen:
        seen.add(cur)
        out.append(cur)
        cur = parent.get(cur)
    return out


stamped = 0
dist = {}
with drv.session() as s:
    for r in rows:
        h = r["h"]
        chain = chain_of(h)
        gen = len(chain)
        dist[gen] = dist.get(gen, 0) + 1
        if not WRITE or gen == 0:
            continue
        s.run("""MATCH (f:Fact {fact_hash:$h})
                 SET f.generation = $g, f.lineage_root = $root,
                     f.lineage_chain = $chain, f.supersedes_count = $n,
                     f.lineage_computed = date()""",
              h=h, g=gen, root=chain[-1], chain=chain, n=gen)
        stamped += 1

print("facts: %d" % len(rows))
for g in sorted(dist):
    label = "original" if g == 0 else ("rewrite" if g == 1 else "rewrite of a rewrite")
    print("  generation %d  %-22s %d" % (g, label, dist[g]))

if WRITE:
    print("\nstamped %d derived facts" % stamped)
    with drv.session() as s:
        print("\n== the deepest chains ==")
        for r in s.run("""MATCH (f:Fact) WHERE f.generation >= 1
            RETURN f.fact_hash AS h, f.generation AS g, f.lineage_root AS root,
                   f.confidence AS c, left(f.claim,66) AS claim
            ORDER BY f.generation DESC, f.confidence DESC LIMIT 12"""):
            print("  gen %d  %s  %.2f  from %s" % (r["g"], r["h"], r["c"] or 0, r["root"]))
            print("         %s…" % re.sub(r"\s+", " ", r["claim"]))
else:
    print("\nreport only — pass --write to stamp")
