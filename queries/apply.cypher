// Apply a permit's state changes: the plant as it will be once the permit is approved.
// Used by a check (inside a transaction that is rolled back) and by approve
// (committed), so what is checked is exactly what is stored.
// Each new state is stamped with $at and with the permit id as its observer.
MATCH (:Permit {id: $id})-[o:OPERATES]->(c:Component)
SET c.state = o.to, c.observed_at = $at, c.observed_by = $id;

MATCH (:Permit {id: $id})-[:ENERGISES]->(c:Component)
SET c.state = 'in_service', c.observed_at = $at, c.observed_by = $id
