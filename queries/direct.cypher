// One-hop conflicts between the candidate permit and active permits.
MATCH (p:Permit {id: $id})-[o:OPERATES]->(v:Component)<-[:RELIES_ON]-(q:Permit {status: 'active'})
WHERE q.id <> p.id AND o.to IN ['open', 'removed']
RETURN 'ISOLATION_REMOVED' AS code, q.id AS permit, q.title AS title, v.tag AS target
UNION
MATCH (p:Permit {id: $id})-[:ENERGISES]->(v:Component)<-[:WORKS_ON]-(q:Permit {status: 'active'})
WHERE q.id <> p.id
RETURN 'ENERGISES_WORKSITE' AS code, q.id AS permit, q.title AS title, v.tag AS target
UNION
MATCH (p:Permit {id: $id})-[:RELIES_ON]->(v:Component)<-[:RELIES_ON]-(q:Permit {status: 'active'})
WHERE q.id <> p.id
RETURN 'SHARED_ISOLATION' AS code, q.id AS permit, q.title AS title, v.tag AS target
UNION
MATCH (p:Permit {id: $id})-[:RELIES_ON]->(v:Component)
WHERE NOT v.state IN ['closed', 'installed'] AND NOT v.tag IN $assume_closed
RETURN 'ISOLATION_NOT_IN_PLACE' AS code, p.id AS permit, p.title AS title, v.tag AS target
