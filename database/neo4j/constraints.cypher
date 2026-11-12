// FIG Neo4j constraints — provisional until docs/graph-schema.md is frozen (TASK-004).
// Apply: python scripts/apply_neo4j_schema.py

CREATE CONSTRAINT entity_uid IF NOT EXISTS
FOR (n:Entity) REQUIRE n.uid IS UNIQUE;

CREATE CONSTRAINT industry_code IF NOT EXISTS
FOR (n:Industry) REQUIRE n.industry_code IS UNIQUE;

CREATE CONSTRAINT stock_code IF NOT EXISTS
FOR (n:ListedCompany) REQUIRE n.stock_code IS UNIQUE;

CREATE CONSTRAINT news_event_uid IF NOT EXISTS
FOR (n:NewsEvent) REQUIRE n.uid IS UNIQUE;
