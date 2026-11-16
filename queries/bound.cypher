// Did the search bound cut the walk short?
//
// exposures.cypher walks at most __MAX_HOPS__ hops. Walk one hop further, with
// every unconfirmed component treated as passable, and count components whose
// shortest route from a possible source is longer than the bound. Any such
// component means the bounded walk may have missed a target, so the assessment
// is INCOMPLETE. Same source and hop rules as exposures.cypher with $possible = true.
MATCH (s:Component)
WHERE ( (s.pressure_source = true OR EXISTS { (:Permit {id: $candidate})-[:ENERGISES]->(s) })
        AND coalesce(s.state, 'unknown') IN ['in_service', 'unknown'] )
   OR ( s.pressure_source = true AND coalesce(s.state, 'unknown') <> 'removed'
        AND coalesce(s.observed_at, '') < $stale_before )
MATCH path = SHORTEST 1 (s)
  ((a)-[:CONNECTED_TO]-(b)
    WHERE NOT coalesce(a.state, 'unknown') IN ['closed', 'installed', 'removed']
       OR coalesce(a.observed_at, '') < $stale_before
  ){1,__PROBE_HOPS__} (x:Component)
WITH x, min(length(path)) AS hops
WHERE hops > __MAX_HOPS__
RETURN count(x) AS beyond
