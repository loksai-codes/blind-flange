// Everything a component would pressurise if it were live, with the path to each item.
MATCH path = SHORTEST 1 (s:Component {tag: $tag})
  ((a)-[:CONNECTED_TO]-(b) WHERE NOT a.state IN ['closed', 'installed', 'removed'])+ (x:Component)
RETURN x.tag AS tag, x.kind AS kind, x.state AS state, length(path) AS hops,
       [n IN nodes(path) | n.tag] AS path
ORDER BY hops, tag
