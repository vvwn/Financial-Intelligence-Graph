"""SQLAlchemy models. Every module must be imported here so Alembic sees it."""

from app.models.base import Base
from app.models.claim import Claim, ClaimEvidence, ClaimRelationship, EntityMention
from app.models.entity import CompanyProfile, Entity, EntityAlias, IndustryTaxonomy
from app.models.evidence import Evidence
from app.models.news import (
    CollectRun,
    CollectRunSource,
    DeadLetter,
    NewsEvent,
    NewsRaw,
    NewsRawEvent,
    Source,
)
from app.models.ops import (
    AnalysisRun,
    AppSetting,
    GraphProjectionRun,
    IdempotencyKey,
    ImpactPath,
    QualityIssue,
)
from app.models.relationship import (
    Relationship,
    RelationshipEvidence,
    RelationshipHistory,
)

__all__ = [
    "AnalysisRun",
    "AppSetting",
    "Base",
    "Claim",
    "ClaimEvidence",
    "ClaimRelationship",
    "CollectRun",
    "CollectRunSource",
    "CompanyProfile",
    "DeadLetter",
    "Entity",
    "EntityAlias",
    "EntityMention",
    "Evidence",
    "GraphProjectionRun",
    "IdempotencyKey",
    "ImpactPath",
    "IndustryTaxonomy",
    "NewsEvent",
    "NewsRaw",
    "NewsRawEvent",
    "QualityIssue",
    "Relationship",
    "RelationshipEvidence",
    "RelationshipHistory",
    "Source",
]
