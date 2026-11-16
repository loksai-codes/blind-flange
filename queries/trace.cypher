// The route between two components, read one of three ways ($mode):
//   physical  any connection, whatever the states; the barriers on it are listed
//   possible  the hop rule of exposures.cypher with $possible = true
//   proven    the hop rule of exposures.cypher with $possible = false
// Read-only. Used by the agent tool trace_path so an agent can explore the graph,
// not only receive a verdict.
MATCH (s:Component {tag: $from}), (t:Component {tag: $to})
MATCH path = SHORTEST 1 (s)
  ((a)-[e:CONNECTED_TO]-(b)
    WHERE $mode = 'physical'
       OR ( NOT coalesce(a.state, 'unknown') IN ['closed', 'installed', 'removed', 'unknown']
            AND coalesce(a.observed_at, '') >= $stale_before AND a.planned_state IS NULL
            AND (e.flow_from IS NULL OR e.flow_from = a.tag OR $mode = 'possible') )
       OR ( $mode = 'possible' AND (coalesce(a.state, 'unknown') = 'unknown'
                                    OR coalesce(a.observed_at, '') < $stale_before
                                    OR a.planned_state IS NOT NULL) )
  ){0,__MAX_HOPS__} (t)
RETURN [n IN nodes(path) | {tag: n.tag, kind: n.kind, state: coalesce(n.state, 'unknown'),
                            observed_at: n.observed_at, planned_state: n.planned_state}] AS nodes,
       length(path) AS hops,
       [n IN nodes(path)[1..-1] WHERE coalesce(n.state, 'unknown') IN ['closed', 'installed', 'removed']
          | {tag: n.tag, state: n.state}] AS barriers,
       [n IN nodes(path)
          WHERE coalesce(n.state, 'unknown') = 'unknown' OR coalesce(n.observed_at, '') < $stale_before
             OR n.planned_state IS NOT NULL
          | n.tag] AS uncertain,
       [i IN range(0, length(path) - 1)
          WHERE relationships(path)[i].flow_from IS NOT NULL
            AND relationships(path)[i].flow_from <> nodes(path)[i].tag
          | nodes(path)[i].tag + '->' + nodes(path)[i + 1].tag] AS against_flow
