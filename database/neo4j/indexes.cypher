// FIG Neo4j indexes — provisional until docs/graph-schema.md is frozen (TASK-004).
// Relationship property indexes require an explicit type in Neo4j 5.

CREATE INDEX entity_name IF NOT EXISTS FOR (n:Entity) ON (n.name);
CREATE INDEX entity_normalized_name IF NOT EXISTS FOR (n:Entity) ON (n.normalized_name);
CREATE INDEX entity_type IF NOT EXISTS FOR (n:Entity) ON (n.entity_type);
CREATE INDEX entity_industry IF NOT EXISTS FOR (n:Entity) ON (n.industry_code);

CREATE INDEX rel_supplies_status IF NOT EXISTS FOR ()-[r:SUPPLIES_TO]-() ON (r.status);
CREATE INDEX rel_supplies_rid IF NOT EXISTS FOR ()-[r:SUPPLIES_TO]-() ON (r.rid);
CREATE INDEX rel_upstream_status IF NOT EXISTS FOR ()-[r:UPSTREAM_OF]-() ON (r.status);
CREATE INDEX rel_belongs_rid IF NOT EXISTS FOR ()-[r:BELONGS_TO_INDUSTRY]-() ON (r.rid);
CREATE INDEX rel_affected_event_rid IF NOT EXISTS FOR ()-[r:AFFECTED_BY_EVENT]-() ON (r.rid);
