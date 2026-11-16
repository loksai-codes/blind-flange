// Everything pressure could reach from one component if it were live, with the
// path to each item and the unconfirmed components on that path.
// Same hop rule as exposures.cypher with $possible = true.
MATCH (s:Component {tag: $tag})
MATCH path = SHORTEST 1 (s)
  ((a)-[:CONNECTED_TO]-(b)
    WHERE NOT coalesce(a.state, 'unknown') IN ['closed', 'installed', 'removed']
       OR coalesce(a.observed_at, '') < $stale_before OR a.planned_state IS NOT NULL
  ){1,__MAX_HOPS__} (x:Component)
RETURN x.tag AS tag, x.kind AS kind, coalesce(x.state, 'unknown') AS state, length(path) AS hops,
       [n IN nodes(path) | n.tag] AS path,
       [n IN nodes(path)[0..-1]
          WHERE coalesce(n.state, 'unknown') = 'unknown' OR coalesce(n.observed_at, '') < $stale_before
             OR n.planned_state IS NOT NULL
          | n.tag] AS uncertain,
       [i IN range(0, length(path) - 1)
          WHERE relationships(path)[i].flow_from IS NOT NULL
            AND relationships(path)[i].flow_from <> nodes(path)[i].tag
          | nodes(path)[i].tag + '->' + nodes(path)[i + 1].tag] AS against_flow
ORDER BY hops, tag
