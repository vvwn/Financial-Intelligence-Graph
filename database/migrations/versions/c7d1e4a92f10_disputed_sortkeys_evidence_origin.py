"""disputed semantics, sort keys, evidence origin

Revision ID: c7d1e4a92f10
Revises: bdaf9a0511cb
Create Date: 2026-11-13 08:40:00.000000

Implements the reviewer decisions of 2026-11-13:

1. `disputed` means "a verified fact was challenged by new evidence".
   - relationship_evidence gains `relation` (supporting / contradicting) so both
     sides survive; the primary key must include it.
   - relationship_history gains `trigger`; entering `disputed` requires evidence.
2. locale=C stays; ordering moves to the application.
   - entity.name_sort_key / name_sort_key_version + change history table.
3. The evidence threshold only decides whether a relationship may enter review.
   - app_setting gains a `version` column; app_setting_history records changes.
   - evidence.origin_key distinguishes independent sources from reposts.
4. I-5: evidence rows are immutable.
   - trigger blocks UPDATE of content columns and any DELETE.
   - supersedes_id may only point at an existing row with the same origin_key.

Hand-written because autogenerate cannot express triggers, views or a PK change.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "c7d1e4a92f10"
down_revision: str | None = "bdaf9a0511cb"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # ------------------------------------------------------------------
    # 2. Sort keys (locale=C stays, ordering decided in the application)
    # ------------------------------------------------------------------
    op.add_column(
        "entity",
        sa.Column("name_sort_key", sa.Text(), server_default=sa.text("''"), nullable=False),
    )
    op.add_column(
        "entity",
        sa.Column(
            "name_sort_key_version", sa.String(length=8), server_default=sa.text("'v1'"), nullable=False
        ),
    )
    op.create_index("ix_entity_name_sort_key", "entity", ["name_sort_key"], unique=False)

    op.create_table(
        "entity_sort_key_history",
        sa.Column("entity_id", sa.UUID(), nullable=False),
        sa.Column("old_key", sa.Text(), nullable=True),
        sa.Column("new_key", sa.Text(), nullable=False),
        sa.Column("old_version", sa.String(length=8), nullable=True),
        sa.Column("new_version", sa.String(length=8), nullable=False),
        sa.Column("reason", sa.String(length=64), nullable=False),
        sa.Column("actor", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.ForeignKeyConstraint(
            ["entity_id"], ["entity.id"], name=op.f("fk_entity_sort_key_history_entity_id_entity")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_entity_sort_key_history")),
    )
    op.create_index(
        "ix_entity_sort_key_history_entity",
        "entity_sort_key_history",
        ["entity_id", "created_at"],
        unique=False,
    )

    # ------------------------------------------------------------------
    # 3. Evidence origin (independence is about the original report)
    # ------------------------------------------------------------------
    op.add_column(
        "evidence",
        sa.Column("origin_key", sa.String(length=64), server_default=sa.text("''"), nullable=False),
    )
    op.add_column("evidence", sa.Column("syndicated_from_id", sa.UUID(), nullable=True))
    op.create_foreign_key(
        op.f("fk_evidence_syndicated_from_id_evidence"),
        "evidence",
        "evidence",
        ["syndicated_from_id"],
        ["id"],
    )
    op.create_index("ix_evidence_origin_key", "evidence", ["origin_key"], unique=False)
    op.create_check_constraint("origin_key_present", "evidence", "origin_key <> ''")
    op.create_check_constraint(
        "syndication_not_self", "evidence", "syndicated_from_id IS NULL OR syndicated_from_id <> id"
    )
    op.create_check_constraint(
        "supersedes_not_self", "evidence", "supersedes_id IS NULL OR supersedes_id <> id"
    )

    # ------------------------------------------------------------------
    # 3b. Settings versioning + audit
    # ------------------------------------------------------------------
    op.add_column(
        "app_setting",
        sa.Column("version", sa.Integer(), server_default=sa.text("1"), nullable=False),
    )
    op.create_table(
        "app_setting_history",
        sa.Column("key", sa.String(length=64), nullable=False),
        sa.Column("old_value", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("new_value", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("old_version", sa.Integer(), nullable=True),
        sa.Column("new_version", sa.Integer(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("actor", sa.String(length=64), nullable=False),
        sa.Column("effective_from", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_app_setting_history")),
    )
    op.create_index(
        "ix_app_setting_history_key", "app_setting_history", ["key", "created_at"], unique=False
    )

    # ------------------------------------------------------------------
    # 1. disputed semantics: both sides of the evidence, auditable trigger
    # ------------------------------------------------------------------
    op.add_column(
        "relationship_evidence",
        sa.Column(
            "relation", sa.String(length=16), server_default=sa.text("'supporting'"), nullable=False
        ),
    )
    # relation joins the primary key: one evidence item may argue both ways
    # (different sources quoting it differently), and both rows must survive.
    op.drop_constraint("pk_relationship_evidence", "relationship_evidence", type_="primary")
    op.create_primary_key(
        "pk_relationship_evidence",
        "relationship_evidence",
        ["relationship_id", "evidence_id", "relation"],
    )
    op.create_check_constraint(
        "relation_valid", "relationship_evidence", "relation IN ('supporting','contradicting')"
    )

    op.add_column(
        "relationship_history",
        sa.Column("trigger", sa.String(length=32), server_default=sa.text("'manual'"), nullable=False),
    )
    op.create_check_constraint(
        "trigger_valid",
        "relationship_history",
        "trigger IN ('claim_promotion','evidence_threshold','manual_approval',"
        "'new_evidence','rule','migration','manual')",
    )
    op.create_check_constraint(
        "disputed_requires_evidence",
        "relationship_history",
        "to_status <> 'disputed' OR array_length(evidence_ids, 1) >= 1",
    )

    # ------------------------------------------------------------------
    # predicate is now constrained to the relationship-type enum (D-14)
    # ------------------------------------------------------------------
    predicates = (
        "belongs_to_industry",
        "upstream_of",
        "downstream_of",
        "supplies_to",
        "purchases_from",
        "controls",
        "holds_stake_in",
        "subsidiary_of",
        "customer_of",
        "competes_with",
        "applies_technology",
        "depends_on_product",
        "affected_by_policy",
        "affected_by_event",
        "demand_transmits_to",
        "potential_beneficiary",
        "potential_loser",
        "potential_supplier",
        "potential_customer",
    )
    op.create_check_constraint("predicate_valid", "claim", f"predicate IN {predicates}")

    # ------------------------------------------------------------------
    # Views: independence is counted on origin_key, not content_hash
    # ------------------------------------------------------------------
    op.execute(
        """
        CREATE VIEW v_evidence_origin AS
        SELECT origin_key,
               count(*)             AS evidence_rows,
               count(DISTINCT content_hash) AS distinct_texts,
               min(evidence_grade)  AS best_grade,
               min(collected_at)    AS first_collected_at
        FROM evidence
        GROUP BY origin_key
        """
    )

    # ------------------------------------------------------------------
    # I-5: evidence is immutable. Corrections are new rows via supersedes_id.
    # ------------------------------------------------------------------
    op.execute(
        """
        CREATE OR REPLACE FUNCTION forbid_evidence_mutation() RETURNS trigger AS $$
        BEGIN
            IF TG_OP = 'DELETE' THEN
                RAISE EXCEPTION 'evidence is append-only (I-5): insert a new row with supersedes_id';
            END IF;

            IF NEW.original_excerpt  IS DISTINCT FROM OLD.original_excerpt
               OR NEW.content_hash    IS DISTINCT FROM OLD.content_hash
               OR NEW.origin_key      IS DISTINCT FROM OLD.origin_key
               OR NEW.source_type     IS DISTINCT FROM OLD.source_type
               OR NEW.source_name     IS DISTINCT FROM OLD.source_name
               OR NEW.source_url      IS DISTINCT FROM OLD.source_url
               OR NEW.title           IS DISTINCT FROM OLD.title
               OR NEW.evidence_grade  IS DISTINCT FROM OLD.evidence_grade
               OR NEW.published_at    IS DISTINCT FROM OLD.published_at
               OR NEW.collected_at    IS DISTINCT FROM OLD.collected_at
               OR NEW.supersedes_id   IS DISTINCT FROM OLD.supersedes_id
               OR NEW.syndicated_from_id IS DISTINCT FROM OLD.syndicated_from_id
            THEN
                RAISE EXCEPTION
                  'evidence content is immutable (I-5): insert a new row with supersedes_id';
            END IF;

            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_evidence_immutable
        BEFORE UPDATE OR DELETE ON evidence
        FOR EACH ROW EXECUTE FUNCTION forbid_evidence_mutation()
        """
    )

    # supersedes_id / syndicated_from_id must reference an existing row of the
    # same origin, and must point backwards in time (controlled append).
    op.execute(
        """
        CREATE OR REPLACE FUNCTION check_evidence_linkage() RETURNS trigger AS $$
        DECLARE
            ref_origin text;
            ref_collected timestamptz;
        BEGIN
            IF NEW.supersedes_id IS NOT NULL THEN
                SELECT origin_key, collected_at INTO ref_origin, ref_collected
                FROM evidence WHERE id = NEW.supersedes_id;
                IF ref_origin IS NULL THEN
                    RAISE EXCEPTION 'supersedes_id does not reference an existing evidence row';
                END IF;
                IF ref_origin <> NEW.origin_key THEN
                    RAISE EXCEPTION 'supersedes_id must share origin_key (correction of the same report)';
                END IF;
                IF NEW.collected_at < ref_collected THEN
                    RAISE EXCEPTION 'superseding evidence cannot predate the row it supersedes';
                END IF;
            END IF;

            IF NEW.syndicated_from_id IS NOT NULL THEN
                SELECT origin_key INTO ref_origin
                FROM evidence WHERE id = NEW.syndicated_from_id;
                IF ref_origin IS NULL THEN
                    RAISE EXCEPTION 'syndicated_from_id does not reference an existing evidence row';
                END IF;
                IF ref_origin <> NEW.origin_key THEN
                    RAISE EXCEPTION 'a repost must carry the origin_key of its source';
                END IF;
            END IF;

            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_evidence_linkage
        BEFORE INSERT ON evidence
        FOR EACH ROW EXECUTE FUNCTION check_evidence_linkage()
        """
    )

    # ------------------------------------------------------------------
    # Threshold settings carry a version so history is interpretable
    # ------------------------------------------------------------------
    op.execute(
        """
        INSERT INTO app_setting (key, value, version, updated_by) VALUES
          ('evidence.threshold_version', '"v1"'::jsonb,  1, 'migration'),
          ('evidence.required_grades',   '["A","B"]'::jsonb, 1, 'migration'),
          ('evidence.min_c_origins',     '2'::jsonb,     1, 'migration'),
          ('evidence.auto_verify',       'false'::jsonb, 1, 'migration')
        ON CONFLICT (key) DO NOTHING
        """
    )
    op.execute(
        """
        INSERT INTO app_setting_history
          (id, key, old_value, new_value, old_version, new_version, reason, actor)
        SELECT gen_random_uuid(), key, NULL, value, NULL, version,
               'initial threshold seeded by migration c7d1e4a92f10', 'migration'
        FROM app_setting
        WHERE key LIKE 'evidence.%'
        """
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS trg_evidence_linkage ON evidence")
    op.execute("DROP FUNCTION IF EXISTS check_evidence_linkage()")
    op.execute("DROP TRIGGER IF EXISTS trg_evidence_immutable ON evidence")
    op.execute("DROP FUNCTION IF EXISTS forbid_evidence_mutation()")
    op.execute("DROP VIEW IF EXISTS v_evidence_origin")

    op.drop_constraint("predicate_valid", "claim", type_="check")

    op.drop_constraint("disputed_requires_evidence", "relationship_history", type_="check")
    op.drop_constraint("trigger_valid", "relationship_history", type_="check")
    op.drop_column("relationship_history", "trigger")

    op.drop_constraint("relation_valid", "relationship_evidence", type_="check")
    op.drop_constraint("pk_relationship_evidence", "relationship_evidence", type_="primary")
    op.create_primary_key(
        "pk_relationship_evidence", "relationship_evidence", ["relationship_id", "evidence_id"]
    )
    op.drop_column("relationship_evidence", "relation")

    op.drop_index("ix_app_setting_history_key", table_name="app_setting_history")
    op.drop_table("app_setting_history")
    op.drop_column("app_setting", "version")

    op.drop_constraint("supersedes_not_self", "evidence", type_="check")
    op.drop_constraint("syndication_not_self", "evidence", type_="check")
    op.drop_constraint("origin_key_present", "evidence", type_="check")
    op.drop_index("ix_evidence_origin_key", table_name="evidence")
    op.drop_constraint(
        op.f("fk_evidence_syndicated_from_id_evidence"), "evidence", type_="foreignkey"
    )
    op.drop_column("evidence", "syndicated_from_id")
    op.drop_column("evidence", "origin_key")

    op.drop_index("ix_entity_sort_key_history_entity", table_name="entity_sort_key_history")
    op.drop_table("entity_sort_key_history")
    op.drop_index("ix_entity_name_sort_key", table_name="entity")
    op.drop_column("entity", "name_sort_key_version")
    op.drop_column("entity", "name_sort_key")
