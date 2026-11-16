// Record an approved permit's state changes as PLANNED, not observed.
// Approval says what should happen; it does not say anyone has seen it happen.
// The component's observed state, observed_at and observed_by are left alone.
// Every walk treats a component with a planned_state as unconfirmed until an
// observation (`blindflange set ... --by <observer>`) records the real state
// and clears the plan.
MATCH (:Permit {id: $id})-[o:OPERATES]->(c:Component)
SET c.planned_state = o.to, c.planned_by = $id, c.planned_at = $at;

MATCH (:Permit {id: $id})-[:ENERGISES]->(c:Component)
SET c.planned_state = 'in_service', c.planned_by = $id, c.planned_at = $at
