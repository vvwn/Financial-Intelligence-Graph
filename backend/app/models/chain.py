"""Industry-chain graph from iFinD (产业节点级, not company-level).

Kept in its own tables rather than mixed into `industry_taxonomy` or `entity`:
iFinD's node codes are a different taxonomy from our 15 AI-compute segments, and
merging them would make `/industries` unreadable.

`mapped_segment` records the mapping back to our segment when one exists, so a
company's segment can be walked into the iFinD chain.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, UUIDPrimaryKeyMixin

CHAIN_RELATIONS = ("upstream", "downstream", "replace", "complement", "contains")


class IndustryChainNode(Base):
    __tablename__ = "industry_chain_node"

    code: Mapped[str] = mapped_column(String(32), primary_key=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    level: Mapped[int | None] = mapped_column(Integer)
    parent_code: Mapped[str | None] = mapped_column(
        String(32), ForeignKey("industry_chain_node.code")
    )
    source: Mapped[str] = mapped_column(String(16), nullable=False, server_default=text("'ifind'"))
    #: Our AI-COMPUTE-* segment this node was mapped to, if any.
    mapped_segment: Mapped[str | None] = mapped_column(String(32))
    attributes: Mapped[dict] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        Index("ix_chain_node_name", "name"),
        Index("ix_chain_node_segment", "mapped_segment"),
    )


class IndustryChainEdge(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "industry_chain_edge"

    src_code: Mapped[str] = mapped_column(
        String(32), ForeignKey("industry_chain_node.code"), nullable=False
    )
    dst_code: Mapped[str] = mapped_column(
        String(32), ForeignKey("industry_chain_node.code"), nullable=False
    )
    relation: Mapped[str] = mapped_column(String(16), nullable=False)
    source: Mapped[str] = mapped_column(String(16), nullable=False, server_default=text("'ifind'"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        CheckConstraint(f"relation IN {CHAIN_RELATIONS}", name="relation_valid"),
        UniqueConstraint("src_code", "dst_code", "relation", name="uq_chain_edge_triple"),
        Index("ix_chain_edge_src", "src_code", "relation"),
        Index("ix_chain_edge_dst", "dst_code", "relation"),
    )


__all__ = ["CHAIN_RELATIONS", "IndustryChainEdge", "IndustryChainNode"]
