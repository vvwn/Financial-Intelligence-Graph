"""Entity domain: entities, aliases, listed-company profiles, industry taxonomy."""

from __future__ import annotations

import uuid
from datetime import date, datetime

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin

ENTITY_TYPES = (
    "country",
    "policy",
    "macro_event",
    "industry",
    "sector",
    "technology",
    "product",
    "raw_material",
    "equipment",
    "listed_company",
    "private_company",
    "subsidiary",
    "stock",
    "news_event",
    "research_report",
    "evidence_file",
)

ENTITY_STATUSES = ("active", "merged", "deprecated")


class Entity(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "entity"

    entity_type: Mapped[str] = mapped_column(String(32), nullable=False)
    canonical_name: Mapped[str] = mapped_column(Text, nullable=False)
    normalized_name: Mapped[str] = mapped_column(Text, nullable=False)
    stock_code: Mapped[str | None] = mapped_column(String(16))
    exchange: Mapped[str | None] = mapped_column(String(8))
    industry_code: Mapped[str | None] = mapped_column(String(32))
    description: Mapped[str | None] = mapped_column(Text)
    attributes: Mapped[dict] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, server_default=text("'active'")
    )
    merged_into_id: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("entity.id")
    )

    __table_args__ = (
        CheckConstraint(f"entity_type IN {ENTITY_TYPES}", name="entity_type_valid"),
        CheckConstraint(f"status IN {ENTITY_STATUSES}", name="status_valid"),
        CheckConstraint(
            "stock_code IS NULL OR stock_code ~ '^[0-9]{6}$'", name="stock_code_format"
        ),
        # A stock code is unique *within* an entity type, not globally:
        # :Stock and :ListedCompany must not fight over the same code.
        Index(
            "ux_entity_type_stock_code",
            "entity_type",
            "stock_code",
            unique=True,
            postgresql_where=text("stock_code IS NOT NULL"),
        ),
        Index(
            "ux_entity_type_norm_name",
            "entity_type",
            "normalized_name",
            unique=True,
            postgresql_where=text("status = 'active' AND stock_code IS NULL"),
        ),
        Index("ix_entity_type", "entity_type"),
        Index("ix_entity_industry_code", "industry_code"),
        Index(
            "ix_entity_name_trgm",
            "canonical_name",
            postgresql_using="gin",
            postgresql_ops={"canonical_name": "gin_trgm_ops"},
        ),
    )


class EntityAlias(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "entity_alias"

    entity_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("entity.id"), nullable=False
    )
    alias: Mapped[str] = mapped_column(Text, nullable=False)
    alias_type: Mapped[str] = mapped_column(
        String(16), nullable=False, server_default=text("'name'")
    )
    source_id: Mapped[uuid.UUID | None] = mapped_column(PgUUID(as_uuid=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        CheckConstraint(
            "alias_type IN ('name','former_name','abbr','english')", name="alias_type_valid"
        ),
        UniqueConstraint("entity_id", "alias", name="uq_entity_alias_entity_id_alias"),
    )


class CompanyProfile(Base):
    __tablename__ = "company_profile"

    entity_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("entity.id"), primary_key=True
    )
    full_name: Mapped[str | None] = mapped_column(Text)
    former_names: Mapped[list | None] = mapped_column(JSONB)
    main_business: Mapped[str | None] = mapped_column(Text)
    core_products: Mapped[dict | None] = mapped_column(JSONB)
    revenue_mix: Mapped[dict | None] = mapped_column(JSONB)
    chain_position: Mapped[str | None] = mapped_column(String(16))
    listed_at: Mapped[date | None] = mapped_column(Date)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        CheckConstraint(
            "chain_position IS NULL OR chain_position IN ('upstream','midstream','downstream')",
            name="chain_position_valid",
        ),
    )


class IndustryTaxonomy(Base):
    __tablename__ = "industry_taxonomy"

    code: Mapped[str] = mapped_column(String(32), primary_key=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    parent_code: Mapped[str | None] = mapped_column(
        String(32), ForeignKey("industry_taxonomy.code")
    )
    level: Mapped[int] = mapped_column(Integer, nullable=False)
    description: Mapped[str | None] = mapped_column(Text)

    __table_args__ = (CheckConstraint("level >= 1 AND level <= 5", name="level_range"),)


__all__ = ["CompanyProfile", "Entity", "EntityAlias", "IndustryTaxonomy"]
