// One-hop conflicts between the request $id and the permits already active.
// The request's state changes have been written (inside a rolled-back transaction).
// Each row carries the graph edges that prove it, as text.
MATCH (p:Permit {id: $id})-[o:OPERATES]->(v:Component)<-[:RELIES_ON]-(q:Permit {status: 'active'})
WHERE q.id <> p.id AND NOT o.to IN ['closed', 'installed', 'unknown']
RETURN 'ISOLATION_REMOVED' AS code, q.id AS permit, q.title AS title, v.tag AS target, false AS uncertain,
       [p.id + ' OPERATES ' + v.tag + ' to ' + o.to, q.id + ' RELIES_ON ' + v.tag] AS evidence
UNION
MATCH (p:Permit {id: $id})-[:ENERGISES]->(v:Component)<-[:WORKS_ON]-(q:Permit {status: 'active'})
WHERE q.id <> p.id
RETURN 'ENERGISES_WORKSITE' AS code, q.id AS permit, q.title AS title, v.tag AS target, false AS uncertain,
       [p.id + ' ENERGISES ' + v.tag, q.id + ' WORKS_ON ' + v.tag] AS evidence
UNION
MATCH (p:Permit {id: $id})-[o:OPERATES {to: 'in_service'}]->(v:Component)<-[:WORKS_ON]-(q:Permit {status: 'active'})
WHERE q.id <> p.id
RETURN 'ENERGISES_WORKSITE' AS code, q.id AS permit, q.title AS title, v.tag AS target, false AS uncertain,
       [p.id + ' OPERATES ' + v.tag + ' to in_service', q.id + ' WORKS_ON ' + v.tag] AS evidence
UNION
MATCH (p:Permit {id: $id})-[:RELIES_ON]->(v:Component)<-[:RELIES_ON]-(q:Permit {status: 'active'})
WHERE q.id <> p.id
RETURN 'SHARED_ISOLATION' AS code, q.id AS permit, q.title AS title, v.tag AS target, false AS uncertain,
       [p.id + ' RELIES_ON ' + v.tag, q.id + ' RELIES_ON ' + v.tag] AS evidence
UNION
MATCH (p:Permit {id: $id})-[:RELIES_ON]->(v:Component)
WHERE NOT coalesce(v.state, 'unknown') IN ['closed', 'installed']
   OR coalesce(v.observed_at, '') < $stale_before OR v.planned_state IS NOT NULL
RETURN 'ISOLATION_NOT_IN_PLACE' AS code, '' AS permit, null AS title, v.tag AS target,
       (coalesce(v.state, 'unknown') = 'unknown' OR coalesce(v.observed_at, '') < $stale_before
        OR v.planned_state IS NOT NULL) AS uncertain,
       [p.id + ' RELIES_ON ' + v.tag,
        v.tag + ' is ' + coalesce(v.state, 'unknown') + ', observed ' + coalesce(v.observed_at, 'never')
        + CASE WHEN v.planned_state IS NULL THEN ''
               ELSE '; planned ' + v.planned_state + ' by ' + v.planned_by + ', not yet observed' END] AS evidence
