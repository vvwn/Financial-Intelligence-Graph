"""Contract-level enums. Single source of truth for API, DB and frontend types.

Mirrors docs/api-contracts.md section 3. Changing a value requires a contract
change (ADR + changelog), because it is a breaking change for consumers.

State names follow the owner decision of 2026-11-13:
    CANDIDATE -> PENDING_REVIEW -> VERIFIED
    plus REJECTED / EXPIRED / REVOKED
`DISPUTED` is kept in addition (task book section 8 requires both sides of a
conflict to be retained; without this state there is nowhere to put them).
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
    STOCK = "stock"
    NEWS_EVENT = "news_event"
    RESEARCH_REPORT = "research_report"
    EVIDENCE_FILE = "evidence_file"


class NewsEventType(StrEnum):
    POLICY = "policy"
    REGULATION = "regulation"
    EARNINGS = "earnings"
    GUIDANCE = "guidance"
    CAPEX = "capex"
    ORDER = "order"
    CONTRACT = "contract"
    CAPACITY = "capacity"
    TECHNOLOGY = "technology"
    PRODUCT_LAUNCH = "product_launch"
    M_AND_A = "m_and_a"
    SUPPLY_DISRUPTION = "supply_disruption"
    PRICE_CHANGE = "price_change"
    MACRO = "macro"
    GEOPOLITICS = "geopolitics"
    OTHER = "other"


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
    # ---- candidate-layer only: never projected into the verified graph ----
    POTENTIAL_BENEFICIARY = "potential_beneficiary"
    POTENTIAL_LOSER = "potential_loser"
    POTENTIAL_SUPPLIER = "potential_supplier"
    POTENTIAL_CUSTOMER = "potential_customer"


class RelationshipStatus(StrEnum):
    CANDIDATE = "candidate"
    PENDING_REVIEW = "pending_review"
    VERIFIED = "verified"
    DISPUTED = "disputed"
    REJECTED = "rejected"
    EXPIRED = "expired"
    REVOKED = "revoked"


class ClaimType(StrEnum):
    FACT_REPORTED = "fact_reported"
    INFERRED = "inferred"
    HYPOTHESIS = "hypothesis"
    DISPUTED = "disputed"


class ClaimStatus(StrEnum):
    CANDIDATE = "candidate"
    SUPPORTED = "supported"
    REJECTED = "rejected"
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


class ImpactPathStatus(StrEnum):
    VALID = "valid"
    INVALIDATED = "invalidated"
    STALE = "stale"


class VerificationStatus(StrEnum):
    UNVERIFIED = "unverified"
    PARTIALLY_VERIFIED = "partially_verified"
    VERIFIED = "verified"
    DISPUTED = "disputed"


# ---------------------------------------------------------------------------
# Layer separation (owner decision 2026-11-13)
# ---------------------------------------------------------------------------

#: Only these statuses may be projected into Neo4j.
#: candidate / pending_review / rejected stay in PostgreSQL forever.
PROJECTABLE_STATUSES: frozenset[RelationshipStatus] = frozenset(
    {
        RelationshipStatus.VERIFIED,
        RelationshipStatus.DISPUTED,
        RelationshipStatus.EXPIRED,
        RelationshipStatus.REVOKED,
    }
)

#: Relationship types that belong to the candidate layer only (AI inference).
#: They may exist as claims/relationships in PG but must never reach the graph.
CANDIDATE_LAYER_RELATIONSHIP_TYPES: frozenset[RelationshipType] = frozenset(
    {
        RelationshipType.POTENTIAL_BENEFICIARY,
        RelationshipType.POTENTIAL_LOSER,
        RelationshipType.POTENTIAL_SUPPLIER,
        RelationshipType.POTENTIAL_CUSTOMER,
    }
)

#: Statuses that occupy the "active triple" slot, used by the partial unique index.
ACTIVE_TRIPLE_STATUSES: frozenset[RelationshipStatus] = frozenset(
    {
        RelationshipStatus.PENDING_REVIEW,
        RelationshipStatus.VERIFIED,
        RelationshipStatus.DISPUTED,
    }
)

#: Only this claim type may ever be promoted to a verified relationship.
PROMOTABLE_CLAIM_TYPES: frozenset[ClaimType] = frozenset({ClaimType.FACT_REPORTED})

#: Grades that alone can carry a relationship to `verified`.
VERIFIED_REQUIRING_GRADES: frozenset[EvidenceGrade] = frozenset(
    {EvidenceGrade.A, EvidenceGrade.B}
)

#: Minimum count of independent grade-C evidence needed when no A/B exists.
VERIFIED_MIN_C_EVIDENCE: int = 2

#: Claim types whose confidence is capped, to stop inference from looking certain.
CONFIDENCE_CAPS: dict[ClaimType, float] = {
    ClaimType.INFERRED: 0.60,
    ClaimType.HYPOTHESIS: 0.30,
}


__all__ = [
    "ACTIVE_TRIPLE_STATUSES",
    "CANDIDATE_LAYER_RELATIONSHIP_TYPES",
    "CONFIDENCE_CAPS",
    "ClaimStatus",
    "ClaimType",
    "EntityType",
    "EvidenceGrade",
    "ImpactDirection",
    "ImpactPathStatus",
    "NewsEventType",
    "PROJECTABLE_STATUSES",
    "PROMOTABLE_CLAIM_TYPES",
    "RelationshipStatus",
    "RelationshipType",
    "VERIFIED_MIN_C_EVIDENCE",
    "VERIFIED_REQUIRING_GRADES",
    "VerificationStatus",
]
