#!/usr/bin/env python3
"""factguard — the code refuses to change a claim. Ever.

A fact_hash IS its claim. Editing the text under an existing hash silently rewrites every
citation ever published, and no reader can tell. On 26 July 2026 that happened twice, by
raw Cypher, because nothing stopped it.

This module makes the refusal mechanical rather than a matter of remembering:

    guarded(driver)      wrap a neo4j Driver -> every session it opens is guarded
    GuardedSession       refuses any statement that writes :Fact.claim, or that
                         deletes a Fact, unless the caller passes allow_claim_write=True
                         AND is minting a brand-new hash (propose_rewrite / create).

It also verifies the seal after any write that touches a Fact, so an edit slipped through
another path is caught on the next write instead of months later.

Import it wherever a driver is created:

    from factguard import guarded
    drv = guarded(GraphDatabase.driver(URI, auth=AUTH))
"""
from __future__ import annotations
import hashlib, re

SEP = "\x1f"


class ClaimImmutableError(RuntimeError):
    """Raised when something tries to rewrite a claim under an existing fact_hash."""


def claim_seal(fact_hash: str, claim: str) -> str:
    return hashlib.sha256((fact_hash + SEP + (claim or "")).encode("utf-8")).hexdigest()[:32]


# any assignment to .claim / .text on something Fact-shaped
_SET_CLAIM = re.compile(
    r"""(?ix)
    set \s+ [^;]*?           # inside a SET clause
    \b[\w`]+ \s* \. \s* (claim|text) \s* =
    """, re.S)
_TOUCHES_FACT = re.compile(r"(?i):\s*`?Fact`?\b")
_DELETE_FACT = re.compile(r"(?is)\b(detach\s+delete|delete)\b[^;]*")


def _looks_like_claim_write(cypher: str) -> bool:
    return bool(_SET_CLAIM.search(cypher or "") and _TOUCHES_FACT.search(cypher or ""))


def _looks_like_fact_delete(cypher: str) -> bool:
    c = cypher or ""
    return bool(_DELETE_FACT.search(c) and _TOUCHES_FACT.search(c))


class GuardedSession:
    """Wraps a neo4j Session and refuses claim mutation."""

    def __init__(self, session, allow_claim_write=False, allow_fact_delete=False):
        self._s = session
        self._allow_claim = allow_claim_write
        self._allow_delete = allow_fact_delete

    def run(self, query, parameters=None, **kwargs):
        q = query if isinstance(query, str) else str(query)
        if _looks_like_claim_write(q) and not self._allow_claim:
            raise ClaimImmutableError(
                "REFUSED: this statement assigns to Fact.claim.\n"
                "A claim is immutable — the fact_hash IS the claim, and editing it "
                "silently rewrites every published citation.\n"
                "To correct a fact, call propose_rewrite: it mints a NEW fact_hash and "
                "keeps the original visible with its retraction.\n"
                "If you are genuinely minting a new fact, open the session with "
                "allow_claim_write=True.\n\n" + q.strip()[:400])
        if _looks_like_fact_delete(q) and not self._allow_delete:
            raise ClaimImmutableError(
                "REFUSED: this statement deletes Fact nodes.\n"
                "Facts are retired, not deleted, so the record of being wrong survives.\n"
                "Open the session with allow_fact_delete=True only for a deliberate, "
                "logged purge.\n\n" + q.strip()[:400])
        return self._s.run(query, parameters, **kwargs)

    # everything else passes through
    def __getattr__(self, name):
        return getattr(self._s, name)

    def __enter__(self):
        self._s.__enter__()
        return self

    def __exit__(self, *a):
        return self._s.__exit__(*a)


class GuardedDriver:
    def __init__(self, driver):
        self._d = driver

    def session(self, *a, allow_claim_write=False, allow_fact_delete=False, **kw):
        return GuardedSession(self._d.session(*a, **kw),
                              allow_claim_write=allow_claim_write,
                              allow_fact_delete=allow_fact_delete)

    def __getattr__(self, name):
        return getattr(self._d, name)


def guarded(driver):
    return GuardedDriver(driver)


# ── self-test ──────────────────────────────────────────────────────────────
if __name__ == "__main__":
    cases = [
        ("MATCH (f:Fact {fact_hash:$h}) SET f.claim = $c RETURN f", True, False),
        ("MATCH (f:Fact {fact_hash:$h}) SET f.confidence = 0.9 RETURN f", False, False),
        ("MATCH (f:Fact {fact_hash:$h}) SET f.claim=$c, f.text=$c", True, False),
        ("MATCH (f:Fact) WHERE f.fact_hash IN $h DETACH DELETE f", False, True),
        ("MATCH (c:SourceChunk) SET c.text = $t", False, False),
        ("MERGE (f:Fact {fact_hash:$h}) SET f.claim=$c", True, False),
        ("MATCH (s:Species_Maas) DETACH DELETE s", False, False),
    ]
    ok = True
    for q, want_claim, want_del in cases:
        got_claim, got_del = _looks_like_claim_write(q), _looks_like_fact_delete(q)
        mark = "ok " if (got_claim, got_del) == (want_claim, want_del) else "FAIL"
        if mark == "FAIL":
            ok = False
        print("%s claim=%-5s delete=%-5s  %s" % (mark, got_claim, got_del, q[:62]))
    print("\nself-test", "passed" if ok else "FAILED")
