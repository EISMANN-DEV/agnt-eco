#!/usr/bin/env python3
"""Claim seals — tamper-evidence for the one thing that must never change.

A fact_hash IS its claim. Anyone who cites [v:<hash>] is citing those exact words, so
editing the text under a hash silently rewrites every published citation and no reader
can tell. Corrections go through propose_rewrite, which mints a NEW hash and records the
lineage; the wrong fact stays visible with its retraction beside it.

Neo4j community has no triggers, so nothing can physically block a raw Cypher SET. What
this does instead is make the edit undeniable:

    claim_seal = sha256(fact_hash + "\\x1f" + claim)[:32]

Recompute it at any time. If it does not match, the claim moved after the hash was
minted, and the fact is no longer what anything cited.

    python3 claimseal.py --seal       # stamp every unsealed fact (once)
    python3 claimseal.py --check      # verify every seal; exit 1 on any mismatch
    python3 claimseal.py --check --agent <agent>

Config via env: NEO4J_URI (default bolt://localhost:7687), NEO4J_PASSWORD.
"""
from __future__ import annotations
import argparse, hashlib, os, re, sys
from neo4j import GraphDatabase

SEP = "\x1f"


def seal_of(fact_hash: str, claim: str) -> str:
    return hashlib.sha256((fact_hash + SEP + (claim or "")).encode("utf-8")).hexdigest()[:32]


def driver():
    return GraphDatabase.driver(os.getenv("NEO4J_URI", "bolt://localhost:7687"),
                                auth=("neo4j", os.getenv("NEO4J_PASSWORD", "neo4j")))


def do_seal(s, agent=None):
    where = "WHERE f.claim IS NOT NULL AND f.claim_seal IS NULL"
    if agent:
        where += " AND f.agent = $agent"
    rows = s.run(f"MATCH (f:Fact) {where} RETURN f.fact_hash AS h, f.claim AS c",
                 agent=agent).data()
    for r in rows:
        s.run("""MATCH (f:Fact {fact_hash:$h})
                 SET f.claim_seal = $seal, f.claim_sealed_at = datetime(),
                     f.claim_seal_algo = 'sha256(fact_hash 0x1f claim)[:32]'""",
              h=r["h"], seal=seal_of(r["h"], r["c"]))
    print("sealed %d fact(s)" % len(rows))
    return len(rows)


def do_check(s, agent=None):
    where = "WHERE f.claim IS NOT NULL"
    if agent:
        where += " AND f.agent = $agent"
    rows = s.run(f"""MATCH (f:Fact) {where}
        RETURN f.fact_hash AS h, f.claim AS c, f.claim_seal AS seal,
               f.agent AS agent""", agent=agent).data()
    broken, unsealed = [], []
    for r in rows:
        if not r["seal"]:
            unsealed.append(r["h"])
            continue
        if seal_of(r["h"], r["c"]) != r["seal"]:
            broken.append(r)
    print("facts checked : %d" % len(rows))
    print("unsealed      : %d" % len(unsealed))
    print("SEAL BROKEN   : %d" % len(broken))
    for r in broken:
        print("\n  %s  [%s]" % (r["h"], r["agent"]))
        print("    the claim under this hash is not the claim it was minted with.")
        print("    now: %s" % re.sub(r"\s+", " ", r["c"] or "")[:150])
    return len(broken)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seal", action="store_true")
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--agent", default=None)
    a = ap.parse_args()
    if not (a.seal or a.check):
        ap.error("pass --seal or --check")
    with driver().session() as s:
        if a.seal:
            do_seal(s, a.agent)
        if a.check:
            sys.exit(1 if do_check(s, a.agent) else 0)


if __name__ == "__main__":
    main()
