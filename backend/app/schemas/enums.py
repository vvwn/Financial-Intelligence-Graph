"""Contract-level enums. Mirrors docs/api-contracts.md section 3.

This file is the single source of truth for enums used by API, DB and frontend
types. Changing a value requires a contract change (ADR + changelog).
"""

from __future__ import annotations

from enum import StrEnum


class EntityType(StrEnum):
    COUNTRY = "country"
    POLICY = "policy"
    MACRO_EVENT = "macro_event"
    INDUSTRY = "industry"
    SECTOR = "sector"
    TECHNOLOGY = "technology"
    PRODUCT = "product"
    RAW_MATERIAL = "raw_material"
    EQUIPMENT = "equipment"
    LISTED_COMPANY = "listed_company"
    PRIVATE_COMPANY = "private_company"
    SUBSIDIARY = "subsidiary"
    CUSTOMER = "customer"
    SUPPLIER = "supplier"
    COMPETITOR = "competitor"
    STOCK = "stock"
    NEWS_EVENT = "news_event"
    RESEARCH_REPORT = "research_report"
    EVIDENCE_FILE = "evidence_file"


class RelationshipType(StrEnum):
    BELONGS_TO_INDUSTRY = "belongs_to_industry"
    UPSTREAM_OF = "upstream_of"
    DOWNSTREAM_OF = "downstream_of"
    SUPPLIES_TO = "supplies_to"
    PURCHASES_FROM = "purchases_from"
    CONTROLS = "controls"
    HOLDS_STAKE_IN = "holds_stake_in"
    SUBSIDIARY_OF = "subsidiary_of"
    CUSTOMER_OF = "customer_of"
    COMPETES_WITH = "competes_with"
    APPLIES_TECHNOLOGY = "applies_technology"
    DEPENDS_ON_PRODUCT = "depends_on_product"
    AFFECTED_BY_POLICY = "affected_by_policy"
    AFFECTED_BY_EVENT = "affected_by_event"
    DEMAND_TRANSMITS_TO = "demand_transmits_to"
    POTENTIAL_BENEFICIARY = "potential_beneficiary"
    POTENTIAL_LOSER = "potential_loser"


class RelationshipStatus(StrEnum):
    CANDIDATE = "candidate"
    PENDING_VERIFICATION = "pending_verification"
    VERIFIED = "verified"
    REFUTED = "refuted"
    EXPIRED = "expired"
    RETRACTED = "retracted"
    DISPUTED = "disputed"


#: Relations in these states are allowed to be projected into Neo4j.
PROJECTABLE_STATUSES: frozenset[RelationshipStatus] = frozenset(
    {
        RelationshipStatus.VERIFIED,
        RelationshipStatus.DISPUTED,
        RelationshipStatus.EXPIRED,
        RelationshipStatus.RETRACTED,
    }
)


class ClaimType(StrEnum):
    FACT_REPORTED = "fact_reported"
    INFERRED = "inferred"
    HYPOTHESIS = "hypothesis"
    DISPUTED = "disputed"


#: Only these claim types may ever be promoted to a verified relationship.
PROMOTABLE_CLAIM_TYPES: frozenset[ClaimType] = frozenset({ClaimType.FACT_REPORTED})


class ClaimStatus(StrEnum):
    CANDIDATE = "candidate"
    SUPPORTED = "supported"
    REFUTED = "refuted"
    DISPUTED = "disputed"


class EvidenceGrade(StrEnum):
    A = "A"
    B = "B"
    C = "C"
    D = "D"


class ImpactDirection(StrEnum):
    POSITIVE = "positive"
    NEGATIVE = "negative"
    UNCERTAIN = "uncertain"


class VerificationStatus(StrEnum):
    UNVERIFIED = "unverified"
    PARTIALLY_VERIFIED = "partially_verified"
    VERIFIED = "verified"
    DISPUTED = "disputed"


__all__ = [
    "ClaimStatus",
    "ClaimType",
    "EntityType",
    "EvidenceGrade",
    "ImpactDirection",
    "PROJECTABLE_STATUSES",
    "PROMOTABLE_CLAIM_TYPES",
    "RelationshipStatus",
    "RelationshipType",
    "VerificationStatus",
]
