// Which worksites, temporary barriers and open ends does pressure reach?
//
// Walk from every live pressure source through the piping. A hop leaves a
// component only if it lets pressure through:
//   closed, installed  barrier: the walk reaches it and stops
//   removed            open end: the walk reaches it and stops (and it is a target)
//   unknown, stale     never a barrier; passable only when $possible is true
//   or planned         (planned = an approved permit says it will change; nobody has seen it)
// A one-way connection (flow_from set, e.g. through a check valve) is passable
// against its declared flow only when $possible is true, so such a route is
// POSSIBLE, never PROVEN; against_flow lists the hops that go against it.
// So the query runs twice. With $possible = false every component the walk
// passes has a known, current state, and a finding is PROVEN. With
// $possible = true the walk may pass components nobody has confirmed, and a
// finding that only appears then is POSSIBLE.
//
// An observation is stale when observed_at < $stale_before (ISO-8601 UTC text).
// $candidate is the request being assessed: its own worksites count, and the
// equipment it energises is live. The request's state changes have already been
// written inside a transaction that is rolled back afterwards.
//
// __MAX_HOPS__ is replaced with a validated integer before the query runs,
// because Relate accepts only a literal path bound. queries/bound.cypher
// reports whether the bound cut the search short.
MATCH (s:Component)
WHERE ( (s.pressure_source = true OR EXISTS { (:Permit {id: $candidate})-[:ENERGISES]->(s) })
        AND s.state = 'in_service'
        AND ($possible OR (coalesce(s.observed_at, '') >= $stale_before AND s.planned_state IS NULL)) )
   OR ( $possible AND s.pressure_source = true AND coalesce(s.state, 'unknown') <> 'removed'
        AND (coalesce(s.state, 'unknown') = 'unknown' OR coalesce(s.observed_at, '') < $stale_before
             OR s.planned_state IS NOT NULL) )
MATCH path = SHORTEST 1 (s)
  ((a)-[e:CONNECTED_TO]-(b)
    WHERE ( NOT coalesce(a.state, 'unknown') IN ['closed', 'installed', 'removed', 'unknown']
            AND coalesce(a.observed_at, '') >= $stale_before AND a.planned_state IS NULL
            AND (e.flow_from IS NULL OR e.flow_from = a.tag OR $possible) )
       OR ( $possible AND (coalesce(a.state, 'unknown') = 'unknown'
                           OR coalesce(a.observed_at, '') < $stale_before
                           OR a.planned_state IS NOT NULL) )
  ){0,__MAX_HOPS__} (x:Component)
OPTIONAL MATCH (q:Permit)-[r:WORKS_ON|RELIES_ON]->(x)
WHERE (q.status = 'active' OR q.id = $candidate)
  AND (type(r) = 'WORKS_ON' OR x.integrity = 'temporary')
WITH s, x, path, q, r
WHERE q IS NOT NULL OR x.state = 'removed'
RETURN coalesce(q.id, '') AS permit, q.title AS title,
       CASE WHEN q IS NULL THEN 'OPEN_END' ELSE type(r) END AS relation,
       x.tag AS target, s.tag AS source, s.service AS source_service, x.service AS target_service,
       [n IN nodes(path) | n.tag] AS path, length(path) AS hops,
       [n IN [s] + nodes(path)[1..-1]
          WHERE coalesce(n.state, 'unknown') = 'unknown' OR coalesce(n.observed_at, '') < $stale_before
             OR n.planned_state IS NOT NULL
          | n.tag] AS uncertain,
       [i IN range(0, length(path) - 1)
          WHERE relationships(path)[i].flow_from IS NOT NULL
            AND relationships(path)[i].flow_from <> nodes(path)[i].tag
          | nodes(path)[i].tag + '->' + nodes(path)[i + 1].tag] AS against_flow
ORDER BY hops, source, target, permit
