"""State machine and promotion rules (ADR-0003, owner decisions 2026-11-13).

Three guarantees enforced here, not in documentation:

1. Only legal status transitions are allowed. `verified -> candidate` is impossible.
2. A claim may become a relationship only if it is `fact_reported` and its evidence
   meets the grade threshold. `inferred` / `hypothesis` are permanently barred.
3. Candidate-layer relationship types (POTENTIAL_*) never reach the graph.

The caller is responsible for persisting; this module only decides.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field

from app.core.errors import AppError, ErrorCode
from app.schemas.enums import (
    CANDIDATE_LAYER_RELATIONSHIP_TYPES,
    CONFIDENCE_CAPS,
    PROJECTABLE_STATUSES,
    PROMOTABLE_CLAIM_TYPES,
    VERIFIED_MIN_C_EVIDENCE,
    VERIFIED_REQUIRING_GRADES,
    ClaimType,
    EvidenceGrade,
    RelationshipStatus,
    RelationshipType,
)

# ---------------------------------------------------------------------------
# 1. Transition matrix — the single source of truth
# ---------------------------------------------------------------------------

LEGAL_TRANSITIONS: dict[RelationshipStatus, frozenset[RelationshipStatus]] = {
    RelationshipStatus.CANDIDATE: frozenset(
        {
            RelationshipStatus.PENDING_REVIEW,
            RelationshipStatus.REJECTED,
            RelationshipStatus.REVOKED,
        }
    ),
    RelationshipStatus.PENDING_REVIEW: frozenset(
        {
            RelationshipStatus.VERIFIED,
            RelationshipStatus.DISPUTED,
            RelationshipStatus.REJECTED,
            RelationshipStatus.REVOKED,
        }
    ),
    RelationshipStatus.VERIFIED: frozenset(
        {
            RelationshipStatus.DISPUTED,
            RelationshipStatus.EXPIRED,
            RelationshipStatus.REVOKED,
        }
    ),
    RelationshipStatus.DISPUTED: frozenset(
        {
            RelationshipStatus.VERIFIED,
            RelationshipStatus.REJECTED,
            RelationshipStatus.REVOKED,
        }
    ),
    RelationshipStatus.EXPIRED: frozenset(
        {
            RelationshipStatus.PENDING_REVIEW,
            RelationshipStatus.VERIFIED,
            RelationshipStatus.REVOKED,
        }
    ),
    # Terminal states: no way out. A rejected claim must be re-asserted as a new
    # relationship, otherwise the audit trail would show a resurrection.
    RelationshipStatus.REJECTED: frozenset(),
    RelationshipStatus.REVOKED: frozenset(),
}


def assert_transition_allowed(
    from_status: RelationshipStatus | str,
    to_status: RelationshipStatus | str,
) -> None:
    """Raise STATE_TRANSITION_INVALID unless the move is in the matrix."""
    src = RelationshipStatus(from_status)
    dst = RelationshipStatus(to_status)

    if src == dst:
        # Idempotent no-op is allowed at the API layer; the caller should short-circuit.
        return

    allowed = LEGAL_TRANSITIONS[src]
    if dst not in allowed:
        raise AppError(
            ErrorCode.STATE_TRANSITION_INVALID,
            f"Illegal transition {src.value} -> {dst.value}",
            details={
                "from_status": src.value,
                "to_status": dst.value,
                "allowed": sorted(s.value for s in allowed),
            },
        )


# ---------------------------------------------------------------------------
# 2. Promotion: claim -> verified relationship
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class EvidenceFact:
    """Minimal view of one evidence row, enough to judge a promotion."""

    evidence_id: str
    grade: EvidenceGrade
    content_hash: str
    relation: str = "supporting"  # supporting | contradicting

    def __post_init__(self) -> None:
        # Rows coming out of the DB carry a plain str; normalise once, here,
        # so every downstream comparison works on the enum.
        if not isinstance(self.grade, EvidenceGrade):
            object.__setattr__(self, "grade", EvidenceGrade(self.grade))


@dataclass
class PromotionDecision:
    allowed: bool
    target_status: RelationshipStatus
    reasons: list[str] = field(default_factory=list)
    distinct_supporting: int = 0
    best_grade: EvidenceGrade | None = None
    contradicting: int = 0

    def raise_if_denied(self) -> None:
        if self.allowed:
            return
        if any("claim_type" in r for r in self.reasons):
            raise AppError(
                ErrorCode.CLAIM_TYPE_NOT_PROMOTABLE,
                "This claim type can never be promoted to a verified relationship",
                details={"reasons": self.reasons},
            )
        raise AppError(
            ErrorCode.EVIDENCE_REQUIRED,
            "Evidence does not meet the threshold for verification",
            details={
                "reasons": self.reasons,
                "distinct_supporting": self.distinct_supporting,
                "best_grade": self.best_grade.value if self.best_grade else None,
                "required": "1x A/B or 2 distinct C",
            },
        )


def _dedupe_by_content(evidence: Iterable[EvidenceFact]) -> list[EvidenceFact]:
    """Reposts of the same article are ONE piece of evidence (invariant I-6)."""
    seen: dict[str, EvidenceFact] = {}
    for item in evidence:
        key = f"{item.relation}:{item.content_hash}"
        if key not in seen:
            seen[key] = item
    return list(seen.values())


def evaluate_promotion(
    claim_type: ClaimType | str,
    evidence: Sequence[EvidenceFact],
) -> PromotionDecision:
    """Decide whether a claim may be promoted, and to which status.

    Returns a decision instead of raising, so callers can also use it for
    dry-runs and QA reporting.
    """
    ctype = ClaimType(claim_type)
    distinct = _dedupe_by_content(evidence)

    supporting = [e for e in distinct if e.relation == "supporting"]
    contradicting = [e for e in distinct if e.relation == "contradicting"]

    best: EvidenceGrade | None = None
    for item in supporting:
        # Grades are ordered A < B < C < D lexicographically, so min == strongest.
        if best is None or item.grade.value < best.value:
            best = item.grade

    decision = PromotionDecision(
        allowed=False,
        target_status=RelationshipStatus.PENDING_REVIEW,
        distinct_supporting=len(supporting),
        best_grade=best,
        contradicting=len(contradicting),
    )

    if ctype not in PROMOTABLE_CLAIM_TYPES:
        decision.reasons.append(f"claim_type={ctype.value} is not promotable")
        return decision

    if not supporting:
        decision.reasons.append("no supporting evidence")
        return decision

    if contradicting:
        # Both sides are kept; the relationship parks in DISPUTED, never VERIFIED.
        decision.target_status = RelationshipStatus.DISPUTED
        decision.reasons.append(
            f"{len(contradicting)} contradicting evidence item(s); status=disputed"
        )
        decision.allowed = True
        return decision

    has_strong = best is not None and best in VERIFIED_REQUIRING_GRADES
    c_count = sum(1 for e in supporting if e.grade == EvidenceGrade.C)

    if has_strong or c_count >= VERIFIED_MIN_C_EVIDENCE:
        decision.allowed = True
        decision.target_status = RelationshipStatus.VERIFIED
        return decision

    decision.reasons.append(
        f"weak evidence: best={best.value if best else None}, distinct_C={c_count}, "
        f"need 1x A/B or {VERIFIED_MIN_C_EVIDENCE}x C"
    )
    return decision


# ---------------------------------------------------------------------------
# 3. Layer separation: candidate layer never enters the graph
# ---------------------------------------------------------------------------


def assert_projectable(
    relationship_type: RelationshipType | str,
    status: RelationshipStatus | str,
) -> None:
    """Raise if this (type, status) pair must not be written into Neo4j."""
    rtype = RelationshipType(relationship_type)
    rstatus = RelationshipStatus(status)

    if rtype in CANDIDATE_LAYER_RELATIONSHIP_TYPES:
        raise AppError(
            ErrorCode.STATE_TRANSITION_INVALID,
            f"{rtype.value} is a candidate-layer relation and must never be projected",
            details={"relationship_type": rtype.value, "layer": "candidate"},
        )

    if rstatus not in PROJECTABLE_STATUSES:
        raise AppError(
            ErrorCode.STATE_TRANSITION_INVALID,
            f"status {rstatus.value} is not projectable",
            details={
                "status": rstatus.value,
                "projectable": sorted(s.value for s in PROJECTABLE_STATUSES),
            },
        )


def assert_confidence_cap(claim_type: ClaimType | str, confidence: float) -> None:
    """Inference must not look certain (mirrors the DB CHECK constraints)."""
    ctype = ClaimType(claim_type)
    cap = CONFIDENCE_CAPS.get(ctype)
    if cap is not None and confidence > cap:
        raise AppError(
            ErrorCode.VALIDATION_ERROR,
            f"confidence {confidence} exceeds cap {cap} for claim_type={ctype.value}",
            details={"claim_type": ctype.value, "cap": cap, "confidence": confidence},
        )
