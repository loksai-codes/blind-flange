// Store plumbing: loading, writing, revisions, evaluations and snapshots.
// The checks themselves are in the other files in this folder.
// Each statement starts with a line `// :name` and is run by that name from
// src/blindflange/store.py. Every value is a parameter.

// :store_create
// tie_ins: declared service tie-ins as 'from>to' text, e.g. 'nitrogen>process_gas'.
// mode: 'snapshot' (assessed at as_of, the time of the picture) or 'live' (assessed now).
CREATE (s:Store {id: 'store', revision: $revision, eval_seq: 0, as_of: $as_of, mode: $mode,
                 max_age_hours: $max_age_hours, plant: $plant, built_at: $as_of, tie_ins: $tie_ins})

// :store_info
MATCH (s:Store)
RETURN s.revision AS revision, s.as_of AS as_of, s.max_age_hours AS max_age_hours,
       s.plant AS plant, s.eval_seq AS eval_seq, coalesce(s.tie_ins, []) AS tie_ins,
       coalesce(s.mode, 'snapshot') AS mode

// :store_go_live
// Start a shift: from now on the store is assessed at the current time.
MATCH (s:Store)
SET s.mode = 'live', s.as_of = $as_of, s.max_age_hours = coalesce($max_age_hours, s.max_age_hours)

// :stale
MATCH (c:Component)
WHERE c.observed_at IS NOT NULL AND c.observed_at < $stale_before
RETURN c.tag AS tag, c.kind AS kind, coalesce(c.state, 'unknown') AS state,
       c.observed_at AS observed_at, c.observed_by AS observed_by
ORDER BY c.observed_at, c.tag

// :store_bump
MATCH (s:Store) SET s.revision = s.revision + 1 RETURN s.revision AS revision

// :load_equipment
UNWIND $rows AS r WITH r WHERE r.label = 'Equipment' CREATE (c:Component:Equipment) SET c = r.props

// :load_line
UNWIND $rows AS r WITH r WHERE r.label = 'Line' CREATE (c:Component:Line) SET c = r.props

// :load_valve
UNWIND $rows AS r WITH r WHERE r.label = 'Valve' CREATE (c:Component:Valve) SET c = r.props

// :load_blind
UNWIND $rows AS r WITH r WHERE r.label = 'Blind' CREATE (c:Component:Blind) SET c = r.props

// :load_connections
// flow_from: the tag pressure may flow from on a one-way connection (null = both ways).
UNWIND $pairs AS p
MATCH (a:Component {tag: p.a}), (b:Component {tag: p.b})
CREATE (a)-[:CONNECTED_TO {flow_from: p.flow_from}]->(b)

// :component
MATCH (c:Component {tag: $tag})
RETURN c.tag AS tag, c.kind AS kind, c.name AS name, coalesce(c.state, 'unknown') AS state,
       c.observed_at AS observed_at, c.observed_by AS observed_by,
       c.planned_state AS planned_state, c.planned_by AS planned_by

// :component_kinds
MATCH (c:Component) WHERE c.tag IN $tags RETURN c.tag AS tag, c.kind AS kind

// :set_state
// An observation. It makes the state verified and replaces any plan.
MATCH (c:Component {tag: $tag})
SET c.state = $state, c.observed_at = $at, c.observed_by = $by,
    c.planned_state = null, c.planned_by = null, c.planned_at = null

// :permit_exists
MATCH (p:Permit {id: $id}) RETURN p.status AS status

// :permit_create
CREATE (p:Permit {id: $id, title: $title, kind: $kind, status: $status,
                  description: $description, approved_at: $approved_at})

// :permit_works_on
MATCH (p:Permit {id: $id}), (c:Component) WHERE c.tag IN $tags CREATE (p)-[:WORKS_ON]->(c)

// :permit_relies_on
MATCH (p:Permit {id: $id}), (c:Component) WHERE c.tag IN $tags CREATE (p)-[:RELIES_ON]->(c)

// :permit_energises
MATCH (p:Permit {id: $id}), (c:Component) WHERE c.tag IN $tags CREATE (p)-[:ENERGISES]->(c)

// :permit_operates
UNWIND $ops AS op
MATCH (p:Permit {id: $id}), (c:Component {tag: op.tag})
CREATE (p)-[:OPERATES {to: op.to}]->(c)

// :permit_activate
MATCH (p:Permit {id: $id}) SET p.status = 'active', p.approved_at = $at

// :permit_still_needed
MATCH (:Permit {id: $id})-[:RELIES_ON]->(v:Component)<-[:RELIES_ON]-(q:Permit {status: 'active'})
WHERE q.id <> $id
RETURN v.tag AS tag, collect(q.id) AS permits ORDER BY tag

// :permit_close
MATCH (p:Permit {id: $id}) SET p.status = 'closed', p.closed_at = $at

// :stats
MATCH (c:Component) WITH count(c) AS components
OPTIONAL MATCH ()-[r:CONNECTED_TO]->() WITH components, count(r) AS connections
OPTIONAL MATCH (p:Permit {status: 'active'})
RETURN components, connections, count(p) AS active_permits

// :not_normal
MATCH (c:Component) WHERE coalesce(c.state, 'unknown') <> coalesce(c.normal, c.state, 'unknown')
RETURN c.tag AS tag, c.name AS name, coalesce(c.state, 'unknown') AS state, c.normal AS normal
ORDER BY tag

// :uncertain
MATCH (c:Component)
WHERE coalesce(c.state, 'unknown') = 'unknown' OR coalesce(c.observed_at, '') < $stale_before
   OR c.planned_state IS NOT NULL
RETURN c.tag AS tag, coalesce(c.state, 'unknown') AS state, c.observed_at AS observed_at,
       c.observed_by AS observed_by,
       CASE WHEN coalesce(c.state, 'unknown') = 'unknown' THEN 'unknown'
            WHEN c.planned_state IS NOT NULL THEN 'planned ' + c.planned_state + ' by ' + c.planned_by
            ELSE 'stale' END AS reason
ORDER BY tag

// :find
CALL db.index.fulltext.queryNodes('component_text', $q) YIELD node, score
RETURN node.tag AS tag, node.name AS name, score ORDER BY score DESC LIMIT 5

// :snapshot_components
MATCH (c:Component)
RETURN c.tag AS tag, c.kind AS kind, c.name AS name, c.state AS state, c.normal AS normal,
       c.pressure_source AS pressure_source, c.integrity AS integrity, c.service AS service,
       c.observed_at AS observed_at, c.observed_by AS observed_by,
       c.planned_state AS planned_state, c.planned_by AS planned_by, c.planned_at AS planned_at
ORDER BY tag

// :snapshot_connections
MATCH (a:Component)-[r:CONNECTED_TO]->(b:Component)
RETURN a.tag AS a, b.tag AS b, r.flow_from AS flow_from ORDER BY a, b

// :snapshot_permits
MATCH (p:Permit) WHERE p.status = 'active'
OPTIONAL MATCH (p)-[:WORKS_ON]->(w:Component)
WITH p, collect(w.tag) AS works_on
OPTIONAL MATCH (p)-[:RELIES_ON]->(i:Component)
WITH p, works_on, collect(i.tag) AS relies_on
OPTIONAL MATCH (p)-[:ENERGISES]->(e:Component)
WITH p, works_on, relies_on, collect(e.tag) AS energises
OPTIONAL MATCH (p)-[o:OPERATES]->(v:Component)
RETURN p.id AS id, p.title AS title, p.kind AS kind, p.description AS description,
       p.approved_at AS approved_at, works_on, relies_on, energises,
       [x IN collect({tag: v.tag, to: o.to}) WHERE x.tag IS NOT NULL] AS operates
ORDER BY id

// :evaluation_record
MATCH (s:Store) SET s.eval_seq = s.eval_seq + 1
WITH s
CREATE (e:Evaluation {id: 'EVAL-' + toString(s.eval_seq), at: $at, revision: s.revision,
                      kind: $kind, request_id: $request_id,
                      assessment_status: $assessment_status, conflict_verdict: $conflict_verdict,
                      request: $request, result: $result, snapshot: $snapshot})
RETURN e.id AS id

// :evaluation_get
MATCH (e:Evaluation {id: $id})
RETURN e.id AS id, e.at AS at, e.revision AS revision, e.kind AS kind, e.request_id AS request_id,
       e.assessment_status AS assessment_status, e.conflict_verdict AS conflict_verdict,
       e.request AS request, e.result AS result, e.snapshot AS snapshot

// :evaluation_list
MATCH (e:Evaluation)
RETURN e.id AS id, e.at AS at, e.revision AS revision, e.kind AS kind, e.request_id AS request_id,
       e.assessment_status AS assessment_status, e.conflict_verdict AS conflict_verdict
ORDER BY e.at, e.id
