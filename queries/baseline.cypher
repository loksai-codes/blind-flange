// The naive check used as a baseline: does the request name any component that
// an active permit also names? No path walk.
MATCH (p:Permit {id: $id})-[]->(c:Component)<-[]-(q:Permit {status: 'active'})
WHERE q.id <> p.id
RETURN q.id AS permit, collect(DISTINCT c.tag) AS tags
ORDER BY permit
