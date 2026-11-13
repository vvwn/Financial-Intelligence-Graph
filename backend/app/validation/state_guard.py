"""State machine, evidence threshold and layer rules (ADR-0008, ADR-0010, ADR-0011).

Three guarantees enforced here, not in documentation:

1. Only legal transitions are allowed. `verified -> candidate` is impossible.
2. The evidence threshold decides whether a relationship may ENTER REVIEW. It never
   verifies anything by itself: verification additionally requires an explicit approval.
3. `disputed` is only reachable from `verified` — it means "a verified fact was
   challenged by new evidence", not "still checking".

Independence rule: two evidence items are independent only if their `origin_key`
differs. Different `content_hash` is NOT sufficient — reposts, quotations and
abridged copies of one report are one origin.
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
    # NOTE: pending_review -> disputed is intentionally absent.
    # `disputed` means "a verified fact was challenged"; it is not a review outcome.
    RelationshipStatus.PENDING_REVIEW: frozenset(
        {
            RelationshipStatus.VERIFIED,
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

#: Statuses that may feed investment / propagation analysis as established fact.
PROPAGATION_ALLOWED_STATUSES: frozenset[RelationshipStatus] = frozenset(
    {RelationshipStatus.VERIFIED}
)


def assert_transition_allowed(
    from_status: RelationshipStatus | str,
    to_status: RelationshipStatus | str,
) -> None:
    """Raise STATE_TRANSITION_INVALID unless the move is in the matrix."""
    src = RelationshipStatus(from_status)
    dst = RelationshipStatus(to_status)

    if src == dst:
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
# 2. Evidence threshold
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class EvidenceThreshold:
    """Threshold config. Persisted in app_setting, audited in app_setting_history."""

    version: str = "v1"
    required_grades: frozenset[EvidenceGrade] = VERIFIED_REQUIRING_GRADES
    min_c_origins: int = VERIFIED_MIN_C_EVIDENCE
    #: Threshold never verifies on its own; this stays False by design.
    auto_verify: bool = False


DEFAULT_THRESHOLD = EvidenceThreshold()


@dataclass(frozen=True)
class EvidenceFact:
    """Minimal view of one evidence row, enough to judge a promotion."""

    evidence_id: str
    grade: EvidenceGrade
    origin_key: str
    relation: str = "supporting"  # supporting | contradicting

    def __post_init__(self) -> None:
        if not isinstance(self.grade, EvidenceGrade):
            object.__setattr__(self, "grade", EvidenceGrade(self.grade))


@dataclass
class ThresholdDecision:
    met: bool
    distinct_supporting_origins: int = 0
    best_grade: EvidenceGrade | None = None
    c_origins: int = 0
    contradicting_origins: int = 0
    threshold_version: str = DEFAULT_THRESHOLD.version
    reasons: list[str] = field(default_factory=list)


def _split_by_relation(
    evidence: Iterable[EvidenceFact],
) -> tuple[dict[str, EvidenceFact], dict[str, EvidenceFact]]:
    """Collapse to one row per (relation, origin_key). Reposts are one origin."""
    supporting: dict[str, EvidenceFact] = {}
    contradicting: dict[str, EvidenceFact] = {}
    for item in evidence:
        bucket = supporting if item.relation == "supporting" else contradicting
        bucket.setdefault(item.origin_key, item)
    return supporting, contradicting


def evaluate_threshold(
    claim_type: ClaimType | str,
    evidence: Sequence[EvidenceFact],
    threshold: EvidenceThreshold = DEFAULT_THRESHOLD,
) -> ThresholdDecision:
    """Decide whether the evidence clears the bar to enter review.

    Never returns "verified" — the caller must obtain an explicit approval.
    """
    ctype = ClaimType(claim_type)
    supporting, contradicting = _split_by_relation(evidence)

    best: EvidenceGrade | None = None
    for item in supporting.values():
        if best is None or item.grade.value < best.value:
            best = item.grade

    c_origins = sum(1 for e in supporting.values() if e.grade == EvidenceGrade.C)

    decision = ThresholdDecision(
        met=False,
        distinct_supporting_origins=len(supporting),
        best_grade=best,
        c_origins=c_origins,
        contradicting_origins=len(contradicting),
        threshold_version=threshold.version,
    )

    if ctype not in PROMOTABLE_CLAIM_TYPES:
        decision.reasons.append(
            f"claim_type={ctype.value} is not promotable; AI inference stays in the candidate layer"
        )
        return decision

    if not supporting:
        decision.reasons.append("no supporting evidence")
        return decision

    has_strong = best is not None and best in threshold.required_grades
    if has_strong or c_origins >= threshold.min_c_origins:
        decision.met = True
        return decision

    decision.reasons.append(
        f"weak evidence: best={best.value if best else None}, "
        f"independent_C_origins={c_origins}, need 1x A/B or {threshold.min_c_origins}x C "
        f"from different origins (threshold {threshold.version})"
    )
    return decision


# ---------------------------------------------------------------------------
# 3. Review entry and verification
# ---------------------------------------------------------------------------


@dataclass
class ReviewDecision:
    allowed: bool
    target_status: RelationshipStatus = RelationshipStatus.PENDING_REVIEW
    threshold: ThresholdDecision | None = None
    reasons: list[str] = field(default_factory=list)

    def raise_if_denied(self) -> None:
        if self.allowed:
            return
        code = (
            ErrorCode.CLAIM_TYPE_NOT_PROMOTABLE
            if any("not promotable" in r for r in self.reasons)
            else ErrorCode.EVIDENCE_REQUIRED
        )
        raise AppError(code, "Cannot enter review", details={"reasons": self.reasons})


def evaluate_review_eligibility(
    claim_type: ClaimType | str,
    evidence: Sequence[EvidenceFact],
    threshold: EvidenceThreshold = DEFAULT_THRESHOLD,
) -> ReviewDecision:
    """candidate -> pending_review. Threshold only; no approval needed to queue work."""
    decision = evaluate_threshold(claim_type, evidence, threshold)
    return ReviewDecision(
        allowed=decision.met,
        target_status=RelationshipStatus.PENDING_REVIEW,
        threshold=decision,
        reasons=decision.reasons,
    )


@dataclass
class VerificationDecision:
    allowed: bool
    threshold: ThresholdDecision | None = None
    reasons: list[str] = field(default_factory=list)

    def raise_if_denied(self) -> None:
        if self.allowed:
            return
        if any("not promotable" in r for r in self.reasons):
            raise AppError(
                ErrorCode.CLAIM_TYPE_NOT_PROMOTABLE,
                "This claim type can never be verified",
                details={"reasons": self.reasons},
            )
        raise AppError(
            ErrorCode.EVIDENCE_REQUIRED,
            "Cannot verify",
            details={
                "reasons": self.reasons,
                "threshold_version": self.threshold.threshold_version
                if self.threshold
                else None,
            },
        )


AUTOMATED_ACTOR_PREFIXES = ("system:", "auto:", "pipeline:")


def evaluate_verification(
    claim_type: ClaimType | str,
    evidence: Sequence[EvidenceFact],
    *,
    approved_by: str | None,
    threshold: EvidenceThreshold = DEFAULT_THRESHOLD,
) -> VerificationDecision:
    """pending_review -> verified.

    Requires (a) the threshold, (b) an explicit human/QA approval, and
    (c) no unresolved contradicting evidence.
    """
    decision = evaluate_threshold(claim_type, evidence, threshold)
    result = VerificationDecision(
        allowed=False, threshold=decision, reasons=list(decision.reasons)
    )

    if not decision.met:
        return result

    if not approved_by:
        result.reasons.append(
            "threshold met, but verification requires an explicit approval "
            "(approved_by); the threshold never verifies by itself"
        )
        return result

    if approved_by.lower().startswith(AUTOMATED_ACTOR_PREFIXES):
        result.reasons.append(
            f"approved_by={approved_by} is an automated actor; verification must be human or QA"
        )
        return result

    if decision.contradicting_origins:
        result.reasons.append(
            f"{decision.contradicting_origins} contradicting origin(s) unresolved; "
            "cannot verify (conflicts on already-verified facts are recorded as disputed)"
        )
        return result

    result.allowed = True
    return result


def assert_can_dispute(contradicting_evidence_ids: Sequence[str]) -> None:
    """Entering disputed requires at least one contradicting evidence item."""
    if not contradicting_evidence_ids:
        raise AppError(
            ErrorCode.EVIDENCE_REQUIRED,
            "disputed requires at least one contradicting evidence item",
            details={"required": "evidence_ids with relation=contradicting"},
        )


# ---------------------------------------------------------------------------
# 4. Layer separation and propagation
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


def assert_usable_for_propagation(status: RelationshipStatus | str) -> None:
    """Disputed facts must never drive an investment conclusion."""
    rstatus = RelationshipStatus(status)
    if rstatus not in PROPAGATION_ALLOWED_STATUSES:
        raise AppError(
            ErrorCode.STATE_TRANSITION_INVALID,
            f"status {rstatus.value} cannot be used as established fact in propagation",
            details={
                "status": rstatus.value,
                "allowed": sorted(s.value for s in PROPAGATION_ALLOWED_STATUSES),
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
