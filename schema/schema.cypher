// Blind Flange graph schema. Applied once when a store is built.
//
// (:Component)                       every item on the piping: equipment, line, valve, blind
//   + :Equipment | :Line | :Valve | :Blind
//   tag        unique plant tag, e.g. "P-A", "BF-504"
//   kind       pump | vessel | header | exchanger | strainer | line | valve | check_valve | psv | blind
//   name       human description
//   state      Equipment: in_service | shutdown | removed
//              Valve:     open | closed
//              Blind:     installed | removed
//   normal     the state the item has in normal operation
//   source     true if the item holds or generates pressure when in_service
//   integrity  Blind only: rated | temporary (not pressure-tested)
//
// (:Component)-[:CONNECTED_TO]-(:Component)   physical connection, traversed in both directions
//
// (:Permit)
//   id, title, kind, status (requested | active | closed), description, approved_at, closed_at
// (:Permit)-[:WORKS_ON]->(:Component)        containment is broken here
// (:Permit)-[:RELIES_ON]->(:Component)       isolation point protecting the work
// (:Permit)-[:ENERGISES]->(:Component)       equipment the permit starts or pressurises
// (:Permit)-[:OPERATES {to}]->(:Component)   state change the permit needs
//
// Pressure passes through a component unless its state is closed, installed or removed.

CREATE CONSTRAINT component_tag IF NOT EXISTS FOR (c:Component) REQUIRE c.tag IS UNIQUE;
CREATE CONSTRAINT permit_id IF NOT EXISTS FOR (p:Permit) REQUIRE p.id IS UNIQUE;
CREATE FULLTEXT INDEX component_text IF NOT EXISTS FOR (c:Component) ON EACH [c.tag, c.name, c.kind];
