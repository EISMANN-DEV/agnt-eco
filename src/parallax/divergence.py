# -*- coding: utf-8 -*-
"""Parallax — reading one environmental value through many species' Umwelten.

The instrument holds co-located species apart and asks what a single measurement *means* to each,
by resolving that value against each species' own sourced physiological "meaning bands". The same
number can be a home to one organism and a barrier to another; Parallax surfaces exactly that
divergence — a value that is harmful (lethal / barrier) to one reader and fine (safe / optimal) to
another sharing the place. That disagreement is a human blind spot: a single-standpoint summary is
built to miss it.

This module is the meaning logic only. It operates on plain Python data — a list of species, each
with its sourced bands — so it is deliberately inert without that sourced data. Wire it to your own
knowledge graph, or feed it the example in `examples/`.

A "meaning band" is a dict:  {"range": "12 to 18", "meaning": "optimal"}   (range may also be
"<= 4", ">= 20", "2-5", or a non-numeric state string). A "reader" is one species at a place:
    {"species": "...", "unit": "degC", "bands": [ ...bands... ], "source": "<doi>", "confidence": 0.9}
"""
from __future__ import annotations
import re

_NUM = r"[-+]?\d+(?:\.\d+)?"

# a value is a barrier/lethal to a reader, or benign — used to detect a "hard" divergence
SEVERE = {"lethal", "barrier"}
BENIGN = {"safe", "optimal", "abundant", "refuge", "suboptimal"}


def _pred(rng):
    """Parse a band range string -> ('range', a, b) | (op, x) | None (non-numeric)."""
    s = str(rng).replace("≤", "<=").replace("≥", ">=").replace("–", "-").replace("—", "-")
    m = re.search(r"(%s)\s+to\s+(%s)" % (_NUM, _NUM), s)      # "10 to 15" word form
    if m and "<" not in s and ">" not in s:
        return ("range", float(m.group(1)), float(m.group(2)))
    m = re.search(r"(%s)\s*-\s*(%s)" % (_NUM, _NUM), s)       # "10-15" / "10 - 15" dash form
    if m and "<" not in s and ">" not in s:
        return ("range", float(m.group(1)), float(m.group(2)))
    m = re.search(r"(<=|>=|<|>)\s*(%s)" % _NUM, s)
    if m:
        return (m.group(1), float(m.group(2)))
    return None


def _num(value):
    try:
        return float(re.search(_NUM, str(value)).group(0))
    except Exception:
        return None


def resolve(bands, value):
    """Return the band that `value` falls in, or None.

    Numeric path: collect ALL inclusively-matching bands, then the highest lower-bound wins. Inclusive
    matching avoids gaps at shared endpoints (strained 10-12 + barrier >12 -> 12 resolves to strained);
    highest-lower-bound resolves shared-endpoint overlaps toward the upper band (barrier 2-5 + safe >=5
    -> 5 resolves to safe). No substring fall-through on a numeric value.
    """
    v = _num(value)
    if v is not None:
        matches = []
        for b in bands:
            p = _pred(b.get("range", ""))
            if not p:
                continue
            ok, lo = False, float("-inf")
            if p[0] == "range":
                a, b2 = (p[1], p[2]) if p[1] <= p[2] else (p[2], p[1])  # ranges may be descending (e.g. MPa)
                if a <= v <= b2:
                    ok, lo = True, a
            elif p[0] == "<" and v < p[1]:
                ok, lo = True, float("-inf")
            elif p[0] == "<=" and v <= p[1]:
                ok, lo = True, float("-inf")
            elif p[0] == ">" and v > p[1]:
                ok, lo = True, p[1]
            elif p[0] == ">=" and v >= p[1]:
                ok, lo = True, p[1]
            if ok:
                matches.append((lo, b))
        if matches:
            matches.sort(key=lambda x: x[0])
            return matches[-1][1]
        return None
    # state path — non-numeric values only: match the value string against band range/meaning text
    val = str(value).strip().lower()
    for b in bands:
        rng = str(b.get("range", "")).lower()
        if val and (val in rng or rng in val or val == str(b.get("meaning", "")).lower()):
            return b
    return None


def parallax(readers, value):
    """Interpret `value` from every co-located reader's standpoint and report divergence.

    Species are compared ONLY within the same unit: a value read in degC and a value read in mg/L are
    not commensurable, so they never form a false divergence. Within one unit, `divergent` means the
    readers disagree on meaning at all; `hard_divergence` means the value is severe (lethal/barrier) to
    at least one reader and benign (safe/optimal/...) to at least one other — the blind-spot case.

    `readers`: list of {species, unit, bands, source?, confidence?}. Returns a dict of per-unit groups.
    """
    by_unit = {}
    for r in readers:
        by_unit.setdefault((r.get("unit") or "").strip(), []).append(r)

    groups = []
    any_hard = False
    for unit, rs in by_unit.items():
        readings = []
        for r in rs:
            band = resolve(r.get("bands", []), value)
            readings.append({
                "species": r.get("species"),
                "meaning": band.get("meaning") if band else None,
                "resolved": band is not None,
                "confidence": r.get("confidence"),
                "source": r.get("source"),
            })
        meanings = {x["meaning"] for x in readings if x["resolved"]}
        split = bool(meanings & SEVERE) and bool(meanings & BENIGN)
        any_hard = any_hard or split
        groups.append({
            "unit": unit or "(unitless/state)",
            "readings": readings,
            "distinct_meanings": sorted(m for m in meanings if m),
            "divergent": len(meanings) > 1,
            "hard_divergence": split,
        })

    return {
        "value": value,
        "unit_groups": groups,
        "comparable": len(by_unit) <= 1,
        "hard_divergence": any_hard,
        "note": ("Species are compared only within the same unit. Multiple unit_groups = same signal, "
                 "different units -> not comparable (not a divergence). hard_divergence = within one "
                 "unit, a value is harmful to one reader and fine to another — a human blind spot."),
    }
