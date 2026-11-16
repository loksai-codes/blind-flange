// Blind Flange graph schema. Applied once when a store is built.
//
// (:Component)                       every item on the piping: equipment, line, valve, blind
//   + :Equipment | :Line | :Valve | :Blind
//   tag              unique plant tag, e.g. "P-A", "BF-504"
//   kind             pump | compressor | vessel | header | exchanger | strainer | filter
//                    | line | valve | check_valve | control_valve | psv | blind
//   name             human description
//   state            Equipment: in_service | shutdown | removed | unknown
//                    Line:      in_service | removed | unknown
//                    Valve:     open | closed | removed | unknown
//                    Blind:     installed | not_installed | unknown
//                    A missing state is read as unknown.
//   normal           the state the item has in normal operation
//   pressure_source  true if the item holds or generates pressure when in_service
//   integrity        Blind only: rated | temporary (not pressure-tested)
//   service          process_gas, condensate, fuel_gas, nitrogen, instrument_air, ... (default "process")
//   observed_at      when the state was last confirmed (ISO-8601 UTC text)
//   observed_by      who or what confirmed it: an operator, or "scenario"
//   planned_state    the state an approved permit will put it in; not yet observed
//   planned_by       that permit's id;  planned_at  when it was approved
//
// Passability (the one rule; also in queries/exposures.cypher, bound.cypher, reach.cypher):
//   closed, installed   barrier: pressure reaches it and stops
//   removed             open end: pressure reaches it, escapes, and does not continue
//   unknown, stale,     never a barrier; pressure may pass (a POSSIBLE finding, not PROVEN)
//   or planned
//   anything else       passes
//
// (:Component)-[:CONNECTED_TO {flow_from}]-(:Component)
//                physical connection, walked in both directions; flow_from, when set,
//                is the tag pressure flows from (a one-way connection, e.g. a check valve)
//
// (:Permit)
//   id, title, kind, status (requested | active | closed), description, approved_at, closed_at
//   status is authorization only. It never says anything about plant state.
// (:Permit)-[:WORKS_ON]->(:Component)        containment is broken here
// (:Permit)-[:RELIES_ON]->(:Component)       isolation point protecting the work
// (:Permit)-[:ENERGISES]->(:Component)       equipment the permit starts or pressurises
// (:Permit)-[:OPERATES {to}]->(:Component)   state change the permit needs
//
// (:Store)       one per file: revision (bumped by every committed change to plant
//                state or permits), as_of (time of the shift picture),
//                max_age_hours (older observations are stale), eval_seq, plant,
//                tie_ins ('from>to' services a connection may cross on purpose)
// (:Evaluation)  one per assessment, kept for audit and replay:
//                id, at, revision, kind, request_id, assessment_status, conflict_verdict,
//                request, result, snapshot (JSON text: every input needed to replay it)

CREATE CONSTRAINT component_tag IF NOT EXISTS FOR (c:Component) REQUIRE c.tag IS UNIQUE;
CREATE CONSTRAINT permit_id IF NOT EXISTS FOR (p:Permit) REQUIRE p.id IS UNIQUE;
CREATE CONSTRAINT evaluation_id IF NOT EXISTS FOR (e:Evaluation) REQUIRE e.id IS UNIQUE;
CREATE CONSTRAINT store_id IF NOT EXISTS FOR (s:Store) REQUIRE s.id IS UNIQUE;
CREATE FULLTEXT INDEX component_text IF NOT EXISTS FOR (c:Component) ON EACH [c.tag, c.name, c.kind];
