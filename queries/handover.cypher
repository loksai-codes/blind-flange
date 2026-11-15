// Shift handover: every active permit with its worksites and isolation points.
MATCH (p:Permit {status: 'active'})
OPTIONAL MATCH (p)-[:WORKS_ON]->(w:Component)
WITH p, collect(DISTINCT w.tag) AS works_on
OPTIONAL MATCH (p)-[:RELIES_ON]->(i:Component)
RETURN p.id AS permit, p.title AS title, works_on,
       collect(DISTINCT i.tag + ' (' + i.state + ')') AS relies_on
ORDER BY permit
