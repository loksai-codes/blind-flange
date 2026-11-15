// The state changes a permit asks for, used as "what if" inputs to exposures.cypher.
MATCH (p:Permit {id: $id})
OPTIONAL MATCH (p)-[:ENERGISES]->(e:Component)
WITH p, collect(DISTINCT e.tag) AS live
OPTIONAL MATCH (p)-[o:OPERATES]->(v:Component)
RETURN live,
       [x IN collect(DISTINCT {tag: v.tag, to: o.to}) WHERE x.to IN ['open', 'removed'] | x.tag] AS open,
       [x IN collect(DISTINCT {tag: v.tag, to: o.to}) WHERE x.to IN ['closed', 'installed'] | x.tag] AS closed
