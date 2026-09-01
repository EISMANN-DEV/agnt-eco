# -*- coding: utf-8 -*-
"""A minimal grounded reference agent over one synthetic place.

It shows the two ideas the framework is about, with nothing proprietary and no model required to run:

  1. The verification tier. Knowledge is held in explicit classes — verified/sourced fact, hypothesis,
     observation. The agent asserts ONLY verified facts (and cites them), labels hypotheses and
     observations as what they are, and refuses what it cannot ground instead of inventing it.

  2. Parallax. A single environmental value is read from every co-located species' standpoint, exposing
     the case where one number is a barrier to one organism and a home to another.

Run:  python examples/reference_agent.py
"""
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "src"))

from parallax import parallax  # noqa: E402

DATA = os.path.join(HERE, "..", "data", "synthetic_sample")


def load(name):
    with open(os.path.join(DATA, name), encoding="utf-8") as f:
        return json.load(f)


class GroundedAgent:
    """Deterministic reference: no LLM, so the *discipline* is visible on its own.
    (In the full system the same tier gates a local-model agent; see src/verification/rubric_judge.py.)"""

    def __init__(self, facts):
        self.facts = facts

    def answer(self, query):
        words = re.findall(r"[a-z]{4,}", query.lower())
        hits = [f for f in self.facts if any(w in f["claim"].lower() for w in words)]
        if not hits:
            return "[unresolved] I cannot ground an answer to that in my sources, so I will not assert one."
        out = []
        for f in sorted(hits, key=lambda f: -f["confidence"]):
            src = "; ".join(s["ref"] for s in f["sources"])
            if f["tier"] == "verified":
                out.append("[fact, conf %.2f] %s  (source: %s)" % (f["confidence"], f["claim"], src))
            elif f["tier"] == "hypothesis":
                out.append("[hypothesis, not asserted as fact] %s  (%s)" % (f["claim"], src))
            else:  # observation
                out.append("[observation / attention only, not truth] %s  (%s)" % (f["claim"], src))
        return "\n".join(out)


def main():
    facts = load("facts.json")["facts"]
    bands = load("species_bands.json")

    print("=== Verification tier — the agent answers only what it can ground ===\n")
    agent = GroundedAgent(facts)
    for q in ["When does the coldwater fish spawn?",
              "Is the mussel affected by the warm spell?",
              "What is the dissolved oxygen concentration right now?"]:
        print("Q:", q)
        print(agent.answer(q), "\n")

    print("=== Parallax — one temperature, read from three standpoints ===\n")
    value = 20  # degC
    result = parallax(bands["readers"], value)
    print("Place: %s   Signal: %s   Value: %s degC\n" % (bands["place"], bands["signal"], value))
    for g in result["unit_groups"]:
        for r in g["readings"]:
            print("  %-45s -> %s" % (r["species"], r["meaning"]))
        print("\n  distinct meanings: %s" % g["distinct_meanings"])
        print("  divergent: %s   hard_divergence: %s" % (g["divergent"], g["hard_divergence"]))
    print("\n  %s" % result["note"])
    print("\n  Reading: at 20 degC the same water is a *barrier* to the coldwater fish and *optimal*")
    print("  for the warmwater fish — the disagreement a single-standpoint summary is built to miss.")


if __name__ == "__main__":
    main()
