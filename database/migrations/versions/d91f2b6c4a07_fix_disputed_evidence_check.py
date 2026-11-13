"""fix disputed evidence check (array_length -> cardinality)

Revision ID: d91f2b6c4a07
Revises: c7d1e4a92f10
Create Date: 2026-11-13 18:25:00.000000

The original CHECK was:

    to_status <> 'disputed' OR array_length(evidence_ids, 1) >= 1

`array_length('{}'::uuid[], 1)` returns NULL, not 0, and PostgreSQL treats a NULL
CHECK expression as satisfied. So an empty evidence_ids array slipped through —
the constraint looked present but never fired. Found by
`scripts/verify_invariants.py` (I-12), which pokes the database with raw SQL
instead of going through the ORM.

`cardinality()` returns 0 for an empty array, so the guard actually holds.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "d91f2b6c4a07"
down_revision: str | None = "c7d1e4a92f10"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Bare name: the naming convention prefixes ck_<table>_ again.
    op.drop_constraint("disputed_requires_evidence", "relationship_history", type_="check")
    op.create_check_constraint(
        "disputed_requires_evidence",
        "relationship_history",
        "to_status <> 'disputed' OR cardinality(evidence_ids) >= 1",
    )


def downgrade() -> None:
    # Bare name: the naming convention prefixes ck_<table>_ again.
    op.drop_constraint("disputed_requires_evidence", "relationship_history", type_="check")
    op.create_check_constraint(
        "disputed_requires_evidence",
        "relationship_history",
        "to_status <> 'disputed' OR array_length(evidence_ids, 1) >= 1",
    )
