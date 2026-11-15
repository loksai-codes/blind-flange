# Relate notes

Verified on 15 Nov 2026 with `relate-db` 1.0.1 from PyPI, Python 3.13, Linux,
and again on Windows 11 with Python 3.12. Not yet verified on macOS.

## Works as used in this repo
- `relate.connect("path.rl")` creates and opens a single-file store.
  `relate.connect(":memory:")` gives an in-memory graph (used by tests and eval).
- `conn.execute(cypher, params).data()` returns a list of dicts.
- Uniqueness constraints: `CREATE CONSTRAINT ... REQUIRE c.tag IS UNIQUE`.
- Quantified path patterns with a filter on every hop:
  `((a)-[:CONNECTED_TO]-(b) WHERE NOT a.state IN [...])+`
- `SHORTEST 1` returns one shortest path per (start, end) pair when the end
  node is unbound.
- A `MATCH` after the path pattern can join the end node to other nodes.
- List parameters inside the per-hop filter (`a.tag IN $assume_open`), which is
  how "what if this valve were open" is answered without changing the store.
- Transactions: `conn.autocommit = False`, then `conn.commit()` or
  `conn.rollback()`. Reads inside the transaction see its own writes. A
  rollback leaves the store unchanged.
- `UNION` across four `MATCH` branches (see `queries/direct.cypher`).
- Full-text index and `CALL db.index.fulltext.queryNodes(...)`.
- Vector index and the `SEARCH` clause. Tested with 3-dimensional vectors:
  ```
  CREATE VECTOR INDEX comp_vec IF NOT EXISTS FOR (c:Component) ON (c.embedding)
  OPTIONS {indexConfig: {`vector.dimensions`: 3, `vector.similarity_function`: 'cosine'}}

  MATCH (c:Component)
  SEARCH c IN (VECTOR INDEX comp_vec FOR $q LIMIT 2) SCORE AS score
  RETURN c.tag, score
  ```
- `relate.connect(path, read_only=True)` refuses autocommit writes.

## Windows (Windows 11, Python 3.12, relate-db 1.0.1)
- `pip install relate-db` installs a wheel; no compiler needed. Every test,
  the eval and the headline check pass.
- While one connection has a `.rl` file open, a second `relate.connect` on the
  same file is refused with `OperationalError: storage locked`, whether or not
  it asks for `read_only=True`. So `reach` or `handover` cannot run while
  another process holds the store open. Each CLI command opens the store and
  closes it before exiting.
- After `close()` the file can be deleted or overwritten straight away.
- On machines with Windows Application Control, the `blindflange.exe` launcher
  that pip generates can be blocked as unsigned. `python -m blindflange` runs
  the same code and is what the Makefile uses.

## Observed but not relied on
- A read-only connection accepted writes inside an explicit transaction that
  was then rolled back. This is not documented, so `check` opens the store
  read-write and rolls back.

## Limits from the Relate docs (not re-tested here)
- One writing process per store. A second writer is refused.
- The WebAssembly build cannot open a `.rl` file. It takes an in-memory or
  OPFS store only.
- No cross-graph queries. No TLS, no roles, one shared credential on the server.
- The whole graph lives in memory.

## Not yet verified
- The `relate` command-line tool and `relate serve --mcp`. `pip install
  relate-db` does not install a `relate` executable. Find the documented
  install route before planning around it.
- Performance beyond a few hundred nodes.
