// FIG Neo4j constraints — frozen with docs/graph-schema.md v1.0 (2026-11-13).
// Apply: backend/.venv/Scripts/python.exe scripts/apply_neo4j_schema.py
//
// stock_code is constrained on :Entity, not on :ListedCompany.
// Reason: the projector MERGEs (n:Entity {uid}) first and adds the sub-label after.
// A constraint on the sub-label alone lets two unlabelled :Entity nodes share a
// stock code without being caught. Neo4j uniqueness ignores null properties, so
// non-company entities (stock_code = null) are unaffected.

// Drop the pre-freeze constraint that was attached to the wrong label (:ListedCompany).
// Kept as an idempotent statement so re-applying this file converges any environment.
DROP CONSTRAINT stock_code IF EXISTS;

CREATE CONSTRAINT entity_uid IF NOT EXISTS
FOR (n:Entity) REQUIRE n.uid IS UNIQUE;

CREATE CONSTRAINT entity_stock_code IF NOT EXISTS
FOR (n:Entity) REQUIRE n.stock_code IS UNIQUE;

CREATE CONSTRAINT industry_code IF NOT EXISTS
FOR (n:Industry) REQUIRE n.industry_code IS UNIQUE;

CREATE CONSTRAINT news_event_uid IF NOT EXISTS
FOR (n:NewsEvent) REQUIRE n.uid IS UNIQUE;
