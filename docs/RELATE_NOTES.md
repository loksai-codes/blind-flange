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

## Verified on 16 Nov 2026 (Windows 11, Python 3.12, relate-db 1.0.1)
- **Single-file mode depends on the name.** `relate.connect("x.rl")` makes one
  file. Any other name (`x.rl.building`, `x.db`, `x`) makes a directory store.
  Builds therefore write to `x.building.rl` and rename it, and the tool refuses
  store paths that do not end in `.rl`.
- **Path bounds must be literals.** `{1,$n}` is a syntax error. The queries use a
  `__MAX_HOPS__` token that Python replaces with a validated integer.
- **Explicit bounds above 500 are refused** with `TraversalDepthExceeded`
  ("a safety limit ... raise it with --max-traversal-depth (up to 2000)").
  `{1,500}` runs.
- **Unbounded `+` is not limited.** On a 700-node chain, `((a)-[:C]-(b))+` walked
  all 700 hops. This is why every walk here is explicitly bounded and
  `queries/bound.cypher` reports when the bound cut a search short.
- `{0,N}` quantifiers work with `SHORTEST 1`: the zero-hop path returns the start
  node itself, so a live source that is also a worksite is found.
- `EXISTS { (:Permit {id: $id})-[:ENERGISES]->(s) }` works inside `WHERE`.
- `coalesce(x.state, 'unknown')` is how a missing property is made explicit;
  without it `NOT x.state IN [...]` is null and a hop would be refused, which
  would treat a component with no state as a barrier.
- ISO-8601 UTC text compares correctly with `<` and `>=`, so staleness is a
  string comparison against `$stale_before`.
- A list of maps is accepted as a parameter (`UNWIND $ops AS op`) but **cannot
  be stored as a property** (`InvalidPropertyType`). Evaluation snapshots are
  stored as JSON text.
- A second `relate.connect` on a file that is open read-write is refused with
  `storage locked`, which is what keeps every write in one process.
- Opening a store read-only and closing it leaves the file bytes unchanged. A
  read-write connection rewrites the file on close even if every transaction
  was rolled back.

- Evaluations share content-addressed `Snapshot` nodes (`MERGE` on the hash). On the
  gas plant, 20 checks of the same plant state store one 41 KB snapshot instead of
  20 copies (about 830 KB). The `.rl` file is allocated in pages, so its size on disk
  did not change over those 20 checks; the saving shows in the data, not yet in the file.
- `replace()` on strings works in `SET`.

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
  relate-db` does not install a `relate` executable, and nothing in the
  `relate` package mentions serve or MCP. What the upstream README and MCP spec
  (github.com/relatedb/relate, read 16 Nov) document, not tried here:
  - Install: `curl -sSfL https://relatedb.ai/install.sh | bash` (macOS, Linux)
    or `irm https://relatedb.ai/install.ps1 | iex` (Windows PowerShell).
  - `relate serve --database PATH --mcp PORT|stdio`, with `--read-only`
    ("no writer lease"). Tools: `get_schema`, `read_cypher`, and
    `write_cypher` unless read-only. HTTP uses Basic auth; stdio has none.
  - The docs give the CLI as 1.0.3; this project pins `relate-db==1.0.1`.
    They do not say whether a 1.0.1 `.rl` opens in the 1.0.3 CLI.
  Blind Flange does not depend on it. `blindflange mcp` is its own stdio
  server, with assessment tools and no write tool. A judge could point
  `relate serve --read-only --mcp stdio` at a committed store to run raw
  Cypher beside it, once someone checks that the file opens.
- Performance beyond a few hundred nodes. The 151-component gas plant takes
  about 40 ms per assessment (eight queries, plus recording) on a laptop.
