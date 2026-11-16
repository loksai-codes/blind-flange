// Assume a request's state changes have happened: the plant as it will be once
// the work is done. Used only inside the transaction that a check rolls back.
// Approval does not use this: it records the same changes as planned
// (queries/plan.cypher), because approving a permit is not observing a valve.
// Each assumed state is stamped with $at and the request id, and replaces any plan.
MATCH (:Permit {id: $id})-[o:OPERATES]->(c:Component)
SET c.state = o.to, c.observed_at = $at, c.observed_by = $id,
    c.planned_state = null, c.planned_by = null, c.planned_at = null;

MATCH (:Permit {id: $id})-[:ENERGISES]->(c:Component)
SET c.state = 'in_service', c.observed_at = $at, c.observed_by = $id,
    c.planned_state = null, c.planned_by = null, c.planned_at = null
