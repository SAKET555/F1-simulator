"""Insight catalogue + retrieval tests. They read the locally cached races, so
they skip on a machine that hasn't loaded any."""
import pytest

from app.engine import insights, rag

CACHED = insights.cached_race_ids()
pytestmark = pytest.mark.skipif(not CACHED, reason="no locally cached races")


def _race():
    return next(r for r in CACHED if insights.race_insights(r)["facts"])


def test_race_has_about_forty_insights_in_known_categories():
    r = insights.race_insights(_race())
    assert len(r["insights"]) >= 40
    assert {i["category"] for i in r["insights"]} <= set(insights.CATEGORIES)
    ids = [i["id"] for i in r["insights"]]
    assert len(ids) == len(set(ids))


def test_consecutive_pit_in_laps_count_as_one_stop():
    assert insights._dedupe_stops([7, 8, 30, 41, 42, 43]) == [7, 30, 41]
    assert insights._dedupe_stops([]) == []


def test_ranges_formatting():
    assert insights._ranges([3, 4, 5, 9]) == "3–5, 9"


def test_season_rollup_counts_races():
    year = int(_race()[:4])
    s = insights.season_insights(year)
    assert s["races_analysed"] >= 1 and s["insights"]


def test_search_finds_winner_and_respects_year():
    rid = _race()
    year = int(rid[:4])
    res = rag.search("who won the most races", year=year)
    assert res["results"] and all(h["year"] == year for h in res["results"])
    other = rag.search("fastest lap", year=1999)
    assert other["results"] == []


def test_search_infers_year_from_query():
    year = int(_race()[:4])
    res = rag.search(f"most retirements {year}")
    assert res["year"] == year


def test_tokenizer_maps_question_words():
    assert "winner" in rag.tokenize("who won")
    assert rag.tokenize("the of a") == []
