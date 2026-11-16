// Everything pressure could reach from one component if it were live, with the
// path to each item and the unconfirmed components on that path.
// Same hop rule as exposures.cypher with $possible = true.
MATCH (s:Component {tag: $tag})
MATCH path = SHORTEST 1 (s)
  ((a)-[:CONNECTED_TO]-(b)
    WHERE NOT coalesce(a.state, 'unknown') IN ['closed', 'installed', 'removed']
       OR coalesce(a.observed_at, '') < $stale_before
  ){1,__MAX_HOPS__} (x:Component)
RETURN x.tag AS tag, x.kind AS kind, coalesce(x.state, 'unknown') AS state, length(path) AS hops,
       [n IN nodes(path) | n.tag] AS path,
       [n IN nodes(path)[0..-1]
          WHERE coalesce(n.state, 'unknown') = 'unknown' OR coalesce(n.observed_at, '') < $stale_before
          | n.tag] AS uncertain
ORDER BY hops, tag
