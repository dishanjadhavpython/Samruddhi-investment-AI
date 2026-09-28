"""
Unit tests for ingest v2's pure functions (no AWS calls).

    uv run test_ingest_v2.py
"""

import sys
from datetime import datetime, timezone

import ingest_s3vectors as ing

NOW = datetime(2026, 9, 28, tzinfo=timezone.utc).timestamp()


def doc(text="The RBI kept the repo rate at 5.5% on 26 September.", **meta):
    base = {
        "title": "RBI policy",
        "source_name": "Reserve Bank of India",
        "source_url": "https://rbi.org.in/press/1",
        "published_at": "2026-09-26",
        "doc_type": "regulator",
    }
    return {"text": text, "metadata": {**base, **meta}}


def rejected(document, fragment):
    try:
        ing.prepare(document, NOW)
    except ing.IngestError as e:
        assert fragment in str(e), str(e)
        return
    raise AssertionError(f"expected a rejection mentioning {fragment!r}")


def test_same_source_same_keys():
    a = ing.prepare(doc(), NOW)
    b = ing.prepare(doc(text="The RBI kept the repo rate at 5.5% on 26 September. Updated."), NOW)
    assert a["vectors"][0]["key"] == b["vectors"][0]["key"], "re-ingesting a source overwrites it"
    other = ing.prepare(doc(source_url="https://rbi.org.in/press/2"), NOW)
    assert other["vectors"][0]["key"] != a["vectors"][0]["key"]


def test_documents_without_a_url_are_keyed_by_id_or_text():
    digest = {"text": "Nifty 50 closed at 23,140.50 points.", "metadata": {"title": "Digest", "source_name": "Samruddhi AI market digest", "published_at": "2026-09-25", "doc_type": "market_digest", "doc_id": "market-digest/2026-09-25"}}
    first = ing.prepare(digest, NOW)["vectors"][0]["key"]
    digest["text"] = "Nifty 50 closed at 23,200.00 points."
    assert ing.prepare(digest, NOW)["vectors"][0]["key"] == first, "a re-run of the same day overwrites"
    rejected(doc(source_url=""), "source_url is required")


def test_metadata_split_between_filterable_and_not():
    v = ing.prepare(doc(symbols=["niftybees", "bad ticker!", "GOLDBEES"]), NOW)["vectors"][0]
    meta = v["metadata"]
    assert meta["symbols"] == ["GOLDBEES", "NIFTYBEES"]
    assert meta["published_ts"] == int(datetime(2026, 9, 26, tzinfo=timezone.utc).timestamp())
    assert meta["expires_ts"] - meta["published_ts"] == 365 * ing.DAY
    assert meta["text"] and meta["title"] == "RBI policy" and meta["source_url"].startswith("https://")
    assert "symbols" not in ing.prepare(doc(), NOW)["vectors"][0]["metadata"], "no empty lists"


def test_dated_and_sourced():
    rejected(doc(published_at=None), "published_at is required")
    rejected(doc(published_at="26/09/2026"), "ISO date")
    rejected(doc(published_at="2026-10-05"), "future")
    rejected(doc(published_at="2026-07-01", doc_type="news"), "older than the 30-day limit")
    rejected(doc(source_name=""), "source_name")
    rejected(doc(doc_type="tip"), "doc_type must be one of")
    rejected(doc(source_url="ftp://x"), "http(s)")


def test_sell_side_sentences_are_dropped():
    text = (
        "Brokerage X has a target price of 300 on NIFTYBEES. The index rose 1.2% this week. "
        "Analysts recommend buying the dip. Our top picks are A and B. It carries a BUY rating. "
        "Volumes were 8% above average."
    )
    prepared = ing.prepare(doc(text=text), NOW)
    stored = " ".join(v["text"] for v in prepared["vectors"])
    assert prepared["dropped_sentences"] == 4, prepared["dropped_sentences"]
    assert stored == "The index rose 1.2% this week. Volumes were 8% above average."
    rejected(doc(text="Top picks for the week: A, B and C."), "nothing left")


def test_chunks_are_about_200_words():
    sentence = "The index moved within a narrow range during the session today. "  # 11 words
    prepared = ing.prepare(doc(text=sentence * 60), NOW)
    sizes = [len(v["text"].split()) for v in prepared["vectors"]]
    assert all(s <= ing.CHUNK_WORDS for s in sizes) and sum(sizes) == 660, sizes
    assert [v["metadata"]["chunk"] for v in prepared["vectors"]] == list(range(len(sizes)))
    long_sentence = " ".join(["word"] * 450)
    assert [len(c.split()) for c in ing.chunk([long_sentence])] == [200, 200, 50]


def main():
    tests = [(name, fn) for name, fn in globals().items() if name.startswith("test_") and callable(fn)]
    failures = 0
    for name, fn in tests:
        try:
            fn()
            print(f"PASS {name}")
        except AssertionError as e:
            failures += 1
            print(f"FAIL {name}: {e}")
    print(f"\n{len(tests) - failures}/{len(tests)} passed")
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
