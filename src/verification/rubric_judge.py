# -*- coding: utf-8 -*-
"""rubric-judge — a low-noise scorer that runs on the LOCAL model (zero paid API).

Method from Falck, Sabri et al., "Training AI Scientists to Replicate Research"
(arXiv:2608.13331, 2026). Two stages, both on a local open-weight model:

  1. gen_rubric(task)      A short meta-prompt asks the model to WRITE a rubric
                           specific to this task first: N dimensions, each with
                           concrete 0.0 / 0.5 / 1.0 anchor descriptions.
  2. judge(task, cand)     The model scores the candidate against that rubric,
                           sampled K times and averaged to kill variance.

Why it beats a plain "rate this 1-10" prompt: the per-task rubric forces the
model to decompose WHAT must be true before scoring, and multi-sampling makes it
self-consistent. In the paper, 3 rubric samples matched the noise of 8 plain ones.

verify_fact(claim, sources) is the fact-checking specialisation: the rubric it
generates enumerates the individual checkable assertions inside the claim, so the
judge must confirm each against the sources instead of judging the claim wholesale
(the failure mode that lets even frontier models wave through subtle errors).

Model endpoint via OLLAMA_URL (any local OpenAI/Ollama-compatible endpoint).
Deps: stdlib only.
"""
from __future__ import annotations
import os, json, re, statistics, urllib.request, urllib.error

OLLAMA_URL = os.getenv("OLLAMA_URL", "http://127.0.0.1:11434").rstrip("/")
MODEL      = os.getenv("RUBRIC_MODEL", "qwen3.8:27b-q6_K")
NUM_CTX    = int(os.getenv("RUBRIC_NUM_CTX", "8192"))


# ── model call ──────────────────────────────────────────────────────
def _chat(messages, temperature=0.2, num_ctx=None, timeout=600):
    if num_ctx is None:
        num_ctx = NUM_CTX
    body = {
        "model": MODEL, "messages": messages, "stream": False,
        "think": False,  # Qwen3.8 is a thinking model; off keeps JSON clean
        "options": {"temperature": temperature, "num_ctx": num_ctx},
    }
    req = urllib.request.Request(
        OLLAMA_URL + "/api/chat",
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.load(r)["message"]["content"]


def _json(txt):
    """Pull the first balanced JSON object/array out of a model reply."""
    txt = re.sub(r"<think>.*?</think>", "", txt, flags=re.S).strip()
    m = re.search(r"```(?:json)?\s*(.*?)```", txt, re.S)
    if m:
        txt = m.group(1).strip()
    starts = [i for i in (txt.find("{"), txt.find("[")) if i >= 0]
    if not starts:
        raise ValueError("no JSON found in reply: " + txt[:200])
    s = min(starts)
    opener = txt[s]
    closer = "}" if opener == "{" else "]"
    depth = 0
    for i in range(s, len(txt)):
        if txt[i] == opener:
            depth += 1
        elif txt[i] == closer:
            depth -= 1
            if depth == 0:
                return json.loads(txt[s:i + 1])
    return json.loads(txt[s:])  # unbalanced -> let json raise a clear error


# ── stage 1: rubric ─────────────────────────────────────────────────
_META = """You are designing a grading rubric to judge how well a CANDIDATE accomplishes a TASK.

Write exactly {n} scoring dimensions that together cover what a correct, honest answer must get right.
Each dimension is an object with:
  "name": a short criterion name,
  "0.0":  one concrete sentence describing an answer that plainly fails this criterion,
  "0.5":  one concrete sentence describing a partially-right / half-supported answer,
  "1.0":  one concrete sentence describing an answer that fully satisfies this criterion.
Anchors must be SPECIFIC to this task, not generic boilerplate. Do not state the answer; describe qualities.

Return ONLY JSON: {{"dimensions": [{{"name": "...", "0.0": "...", "0.5": "...", "1.0": "..."}}]}}

TASK:
{task}"""


def gen_rubric(task, n=4):
    out = _chat([{"role": "user", "content": _META.format(n=n, task=task)}], temperature=0.2)
    r = _json(out)
    dims = r["dimensions"] if isinstance(r, dict) else r
    return [d for d in dims if isinstance(d, dict) and d.get("name")]


# ── stage 2: judge ──────────────────────────────────────────────────
_JUDGE = """You are a strict, well-calibrated judge. Score the CANDIDATE on each rubric dimension
from 0.0 to 1.0, using the anchor descriptions as reference points. Reserve 1.0 for answers that
clearly meet the 1.0 anchor; when evidence is missing or ambiguous, score low, do not give benefit
of the doubt. Judge only what the CANDIDATE actually shows.

Return ONLY JSON: {{"scores": [{{"name": "...", "score": 0.0, "why": "one short clause"}}]}}

TASK:
{task}

RUBRIC:
{rubric}

CANDIDATE:
{candidate}"""


def judge(task, candidate, n_dims=4, samples=3, rubric=None):
    """Return {overall, dimensions:{name:score}, rubric, draws} — averaged over `samples`."""
    if rubric is None:
        rubric = gen_rubric(task, n_dims)
    rubric_txt = "\n".join(
        "- %s\n    0.0 %s\n    0.5 %s\n    1.0 %s"
        % (d.get("name"), d.get("0.0", ""), d.get("0.5", ""), d.get("1.0", ""))
        for d in rubric
    )
    per_dim = {}
    draws = []
    for _ in range(samples):
        try:
            out = _chat([{"role": "user", "content": _JUDGE.format(
                task=task, rubric=rubric_txt, candidate=candidate)}], temperature=0.3)
            sc = _json(out)
            rows = sc["scores"] if isinstance(sc, dict) else sc
            draw = {}
            for row in rows:
                if isinstance(row, dict) and row.get("name") is not None:
                    try:
                        draw[row["name"]] = max(0.0, min(1.0, float(row["score"])))
                    except (TypeError, ValueError):
                        pass
            if draw:
                draws.append(draw)
                for k, v in draw.items():
                    per_dim.setdefault(k, []).append(v)
        except (urllib.error.URLError, ValueError, KeyError):
            continue
    dims = {k: round(statistics.mean(v), 3) for k, v in per_dim.items()}
    overall = round(statistics.mean(list(dims.values())), 3) if dims else None
    return {"overall": overall, "dimensions": dims, "rubric": rubric,
            "n_draws": len(draws), "draws": draws}


# ── fact-checking specialisation ────────────────────────────────────
def verify_fact(claim, sources, samples=3, n_dims=5):
    """Judge whether every assertion in `claim` is supported by `sources`.
    Returns the judge() result plus a mapped verdict + confidence."""
    src = sources if isinstance(sources, str) else "\n".join(
        ("- " + str(s)) for s in (sources or []))
    task = (
        "A fact-checker must decide whether the CLAIM below is fully supported by the SOURCES. "
        "Break the claim into its individual checkable assertions (species names, locations, "
        "dates, quantities, causal or status claims) and make each a rubric dimension: a claim is "
        "only correct if EVERY assertion is backed by the sources. Unsupported or contradicted "
        "assertions must score low.\n\nCLAIM:\n" + str(claim) + "\n\nSOURCES:\n" + (src or "(none provided)")
    )
    candidate = "CLAIM (as asserted): " + str(claim) + "\n\nSOURCES AVAILABLE:\n" + (src or "(none provided)")
    res = judge(task, candidate, n_dims=n_dims, samples=samples)
    ov = res["overall"]
    if ov is None:
        verdict = "unscored"
    elif ov >= 0.85:
        verdict = "confirmed_by_source"
    elif ov >= 0.6:
        verdict = "partially_supported"
    else:
        verdict = "needs_review"
    res["verdict"] = verdict
    res["confidence"] = ov
    return res


# ── CALIBRATED fact-checking (move A: looser bar + few-shot from the frontier bank) ──
_FACT_META = """You are designing a grading rubric to fact-check a CLAIM against SOURCES.
List {n} dimensions, one per distinct checkable assertion in the claim (species/taxon, place,
date, quantity, status, causal link). Each dimension: "name" and concrete "0.0"/"0.5"/"1.0" anchors.
KEY RULE: an assertion is supported (1.0) when the SOURCES state it OR clearly imply it together with
standard domain knowledge -- it need NOT be quoted verbatim. Score 0.0 only when the sources
contradict the assertion or offer no relevant basis at all.
Return ONLY JSON: {{"dimensions": [{{"name": "...", "0.0": "...", "0.5": "...", "1.0": "..."}}]}}

CLAIM:
{claim}

SOURCES:
{sources}"""

_FACT_JUDGE = """You are a fair, well-calibrated fact-checker. Score the CLAIM on each rubric dimension
from 0.0 to 1.0. Confirm (high score) an assertion the SOURCES support directly OR by reasonable
inference from what they state plus standard domain knowledge; do NOT demand the exact words. Score
low only for assertions the sources contradict or do not address at all.

Calibration for the intended bar:
- HIGH example: claim "the Arctic char is a cold-water salmonid in Lake X"; sources say "Salvelinus
  alpinus persists in the deep cold layer of Lake X" -> all parts supported (Salvelinus being a
  salmonid is standard knowledge). Score ~1.0.
- LOW example: claim "Species Y was introduced in 1957"; sources describe Species Y's ecology but
  never mention any introduction or date -> that assertion is unsupported. Score ~0.0.

Return ONLY JSON: {{"scores": [{{"name": "...", "score": 0.0, "why": "one short clause"}}]}}

CLAIM:
{claim}

RUBRIC:
{rubric}

SOURCES:
{sources}"""


def verify_fact_calibrated(claim, sources, samples=3, n_dims=5):
    """Move-A calibrated verifier: per-claim rubric with a looser 'evidence + reasonable
    inference' bar and baked-in calibration examples. Returns overall + mapped verdict."""
    src = sources if isinstance(sources, str) else "\n".join("- " + str(s) for s in (sources or []))
    src = src or "(no sources provided)"
    # stage 1: claim-specific rubric under the looser rule
    try:
        rb = _json(_chat([{"role": "user", "content": _FACT_META.format(n=n_dims, claim=claim, sources=src)}],
                         temperature=0.2))
        rubric = rb["dimensions"] if isinstance(rb, dict) else rb
        rubric = [d for d in rubric if isinstance(d, dict) and d.get("name")]
    except Exception:
        rubric = []
    rubric_txt = "\n".join("- %s\n    0.0 %s\n    0.5 %s\n    1.0 %s"
                           % (d.get("name"), d.get("0.0", ""), d.get("0.5", ""), d.get("1.0", ""))
                           for d in rubric) or "(judge the claim holistically against the sources)"
    # stage 2: judge, multi-sample
    per_dim = {}
    for _ in range(samples):
        try:
            out = _chat([{"role": "user", "content": _FACT_JUDGE.format(
                claim=claim, rubric=rubric_txt, sources=src)}], temperature=0.3)
            sc = _json(out)
            rows = sc["scores"] if isinstance(sc, dict) else sc
            for row in rows:
                if isinstance(row, dict) and row.get("name") is not None:
                    try:
                        per_dim.setdefault(row["name"], []).append(max(0.0, min(1.0, float(row["score"]))))
                    except (TypeError, ValueError):
                        pass
        except (urllib.error.URLError, ValueError, KeyError):
            continue
    dims = {k: round(statistics.mean(v), 3) for k, v in per_dim.items()}
    ov = round(statistics.mean(list(dims.values())), 3) if dims else None
    if ov is None:
        verdict = "unscored"
    elif ov >= 0.80:
        verdict = "confirmed_by_source"
    elif ov >= 0.55:
        verdict = "partially_supported"
    else:
        verdict = "needs_review"
    return {"overall": ov, "verdict": verdict, "confidence": ov, "dimensions": dims, "rubric": rubric}


if __name__ == "__main__":
    import sys
    # smoke test: verify one claim from argv or a built-in example
    claim = sys.argv[1] if len(sys.argv) > 1 else (
        "The Arctic char (Salvelinus alpinus) is a glacial-relict salmonid that survives in "
        "the cold deep water of Lac Leman.")
    srcs = sys.argv[2] if len(sys.argv) > 2 else (
        "Salvelinus alpinus is a cold-water salmonid; in Lake Geneva (Lac Leman) it persists as a "
        "glacial relict in the deep hypolimnion.")
    r = verify_fact(claim, srcs, samples=3)
    print(json.dumps({k: v for k, v in r.items() if k != "draws"}, indent=2, ensure_ascii=False))
