"""
Retrieval over the season/race insight catalogue ("ask the season").

This is the *retrieval* half of a RAG system, built to run entirely on this
machine with no API key and no extra data source:

  * The corpus is generated from the same locally cached FastF1 lap data the
    rest of the app uses (see insights.py) — one short, self-describing
    passage per insight, plus a results passage per race and season roll-ups.
  * Passages are ranked with BM25 (a standard keyword-relevance function),
    optionally restricted to one season.
  * The "answer" is extractive: the best-matching passages are returned
    verbatim with the race each came from. Nothing is generated, so nothing
    can be invented — every line traces back to a computed statistic.

A language model could be layered on top of these passages to phrase a
prose answer; that is deliberately left out because it needs a paid API key.
"""
from __future__ import annotations

import logging
import math
import re
import threading
from collections import Counter, defaultdict
from typing import Optional

from app.engine import insights

log = logging.getLogger(__name__)

_K1, _B = 1.5, 0.75
_TOKEN = re.compile(r"[a-z0-9]+")
_STOP = {
    "the", "a", "an", "of", "in", "on", "at", "to", "and", "or", "is", "was", "were", "who", "what", "which",
    "how", "did", "do", "does", "for", "with", "by", "me", "show", "tell", "about", "than", "that", "this",
    "it", "its", "be", "been", "are", "from", "as", "into", "there", "any", "most", "much", "many",
}
# Question wording → the vocabulary the passages actually use.
_SYNONYMS = {
    "won": "winner", "win": "winner", "wins": "winner", "victory": "winner", "victories": "winner", "champion": "winner",
    "overtake": "swaps", "overtakes": "swaps", "overtaking": "swaps", "passes": "swaps", "action": "swaps", "battles": "swaps",
    "crash": "retirements", "crashes": "retirements", "dnf": "retirements", "dnfs": "retirements",
    "retire": "retirements", "retired": "retirements", "retirement": "retirements", "failures": "retirements",
    "safety": "neutralised", "vsc": "neutralised", "flag": "neutralised", "caution": "neutralised",
    "pit": "stops", "pits": "stops", "pitstop": "stops", "pitstops": "stops", "stop": "stops",
    "tire": "tyre", "tires": "tyre", "tyres": "tyre", "rubber": "tyre", "degradation": "deg", "wear": "deg",
    "quickest": "fastest", "quick": "fast", "speed": "pace", "speedy": "fast",
    "steady": "consistent", "consistency": "consistent", "smooth": "consistent",
    "strategy": "strategies", "strategic": "strategies", "undercut": "undercut", "undercuts": "undercut",
    "lead": "led", "leader": "led", "leading": "led", "leads": "led",
    "boring": "processional", "dull": "processional",
}


# A question about who won should surface the race-result passage first.
_INTENT_CATEGORY = {"winner": "Result", "podium": "Result"}


def _stem(w: str) -> str:
    for suf in ("ing", "ed", "es", "s"):
        if len(w) > len(suf) + 3 and w.endswith(suf):
            return w[: -len(suf)]
    return w


def tokenize(text: str) -> list[str]:
    out = []
    for w in _TOKEN.findall(text.lower()):
        if w in _STOP:
            continue
        w = _SYNONYMS.get(w, w)
        out.append(_stem(w))
    return out


class _Index:
    def __init__(self, docs: list[dict]):
        self.docs = docs
        self.tf: list[Counter] = []
        self.df: Counter = Counter()
        self.postings: dict[str, list[int]] = defaultdict(list)
        for i, d in enumerate(docs):
            # Passages are searched on their own text *and* their heading, so
            # "Monaco" or "2021" in a query reaches every passage of that race.
            c = Counter(tokenize(d["text"] + " " + d["source"]))
            self.tf.append(c)
            for t in c:
                self.df[t] += 1
                self.postings[t].append(i)
        self.n = len(docs)
        self.len = [sum(c.values()) for c in self.tf]
        self.avg = (sum(self.len) / self.n) if self.n else 1.0

    def search(self, query: str, year: Optional[int], limit: int) -> list[tuple[float, dict]]:
        q = tokenize(query)
        if not q:
            return []
        scores: dict[int, float] = defaultdict(float)
        for t in set(q):
            if t not in self.postings:
                continue
            idf = math.log(1 + (self.n - self.df[t] + 0.5) / (self.df[t] + 0.5))
            for i in self.postings[t]:
                if year is not None and self.docs[i]["year"] != year:
                    continue
                f = self.tf[i][t]
                scores[i] += idf * f * (_K1 + 1) / (f + _K1 * (1 - _B + _B * self.len[i] / self.avg))
        wanted = {_INTENT_CATEGORY[t] for t in q if t in _INTENT_CATEGORY}
        for i in scores:
            if self.docs[i]["category"] in wanted:
                scores[i] *= 1.4
        ranked = sorted(scores.items(), key=lambda kv: -kv[1])[:limit]
        return [(s, self.docs[i]) for i, s in ranked]


# ── corpus ────────────────────────────────────────────────────────────────────

def _race_docs(r: dict) -> list[dict]:
    ev, yr = r["event_name"], r["year"]
    head = f"{yr} {ev}"
    source = f"{head} · round {r['round']} · {r['circuit']}"
    docs = []
    f = r["facts"]
    if f:
        docs.append({
            "kind": "race", "year": yr, "race_id": r["race_id"], "source": source, "category": "Result",
            "text": (f"{head} result: race winner {f['winner']} ({f['winner_team']}), won the race; podium {', '.join(f['podium'])}. "
                     f"{f['finishers']} of {f['starters']} cars finished. Fastest lap by {f['fastest_lap_driver']}."),
        })
    for i in r["insights"]:
        docs.append({
            "kind": "race", "year": yr, "race_id": r["race_id"], "source": source, "category": i["category"],
            "text": f"{head}: {i['title']} — {i['value']}. {i['detail']}".strip(),
        })
    return docs


def _season_docs(s: dict) -> list[dict]:
    yr = s["year"]
    docs = []
    for i in s["insights"]:
        docs.append({
            "kind": "season", "year": yr, "race_id": None,
            "source": f"{yr} season · {s['races_analysed']} races analysed", "category": "Season",
            "text": f"{yr} season: {i['title']} — {i['value']}. {i['detail']}".strip(),
        })
    return docs


_lock = threading.Lock()
_state: dict = {"sig": None, "index": None, "coverage": {}}


def _signature() -> tuple:
    return tuple(insights.cached_race_ids())


def _build() -> None:
    ids = insights.cached_race_ids()
    docs: list[dict] = []
    coverage: dict[int, dict] = {}
    years = sorted({int(i[:4]) for i in ids})
    for y in years:
        analysed = 0
        for rid in (i for i in ids if i.startswith(f"{y}-")):
            try:
                r = insights.race_insights(rid)
            except Exception as exc:
                log.warning("RAG: skipping %s: %s", rid, exc)
                continue
            if r["facts"]:
                analysed += 1
                docs.extend(_race_docs(r))
        season = insights.season_insights(y)
        docs.extend(_season_docs(season))
        coverage[y] = {"year": y, "races_indexed": analysed}
    _state.update(sig=tuple(ids), index=_Index(docs), coverage=coverage)
    log.info("RAG index built: %d passages over %d seasons", len(docs), len(years))


def _ensure() -> _Index:
    with _lock:
        if _state["index"] is None or _state["sig"] != _signature():
            _build()
        return _state["index"]


def coverage() -> dict:
    """Per-season count of races searchable, against the calendar's total."""
    _ensure()
    from app.engine.data_loader import list_available_races
    totals = Counter(r["year"] for r in list_available_races())
    rows = [{**c, "races_in_calendar": totals.get(y, 0)} for y, c in sorted(_state["coverage"].items())]
    return {"passages": _state["index"].n, "seasons": rows}


def search(query: str, year: Optional[int] = None, limit: int = 8) -> dict:
    index = _ensure()
    if year is None:                       # "in 2021, who ..." names the season itself
        m = re.search(r"\b(20[12]\d)\b", query)
        if m and int(m.group(1)) in _state["coverage"]:
            year = int(m.group(1))
    hits = index.search(query, year, limit)
    return {
        "query": query, "year": year,
        "mode": "retrieval-only (extractive, no language model)",
        "results": [{"score": round(s, 3), **{k: d[k] for k in ("text", "source", "year", "race_id", "kind", "category")}}
                    for s, d in hits],
    }
