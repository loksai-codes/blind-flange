from pathlib import Path

from blindflange import store

ROOT = Path(__file__).resolve().parents[1]


def test_every_query_file_is_served_from_the_package():
    files = sorted((ROOT / "queries").glob("*.cypher"))
    assert files
    for f in files:
        assert store.query(f.stem) == f.read_text(encoding="utf-8")


def test_schema_is_served_from_the_package():
    assert store.schema() == (ROOT / "schema" / "schema.cypher").read_text(encoding="utf-8")
