// Which permit worksites and temporary barriers does pressure reach?
//
// Walk from every live pressure source through the piping. A hop is allowed
// only if the component being left lets pressure through. The walk therefore
// stops AT the first closed valve, installed blind or removed item.
// One shortest path per (source, target) pair is returned as evidence.
//
// Parameters let the same query answer "what if":
//   $assume_live    tags to treat as live sources (equipment a permit energises)
//   $assume_open    tags to treat as passable     (valve opened, blind removed)
//   $assume_closed  tags to treat as blocking     (valve closed, blind installed)
//   $candidate      id of a requested permit to include, or ''
MATCH (s:Component)
WHERE (s.source = true AND s.state = 'in_service') OR s.tag IN $assume_live
MATCH path = SHORTEST 1 (s)
  ((a)-[:CONNECTED_TO]-(b)
    WHERE a.tag IN $assume_open
       OR (NOT a.state IN ['closed', 'installed', 'removed'] AND NOT a.tag IN $assume_closed)
  )+ (x:Component)
MATCH (q:Permit)-[r:WORKS_ON|RELIES_ON]->(x)
WHERE (q.status = 'active' OR q.id = $candidate)
  AND (type(r) = 'WORKS_ON' OR x.integrity = 'temporary')
RETURN q.id AS permit, q.title AS title, type(r) AS relation,
       x.tag AS target, s.tag AS source,
       [n IN nodes(path) | n.tag] AS path, length(path) AS hops
ORDER BY hops
