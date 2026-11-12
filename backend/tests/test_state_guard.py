"""Unit tests for the state machine and promotion rules (no database needed)."""

from __future__ import annotations

import pytest
from app.core.errors import AppError, ErrorCode
from app.schemas.enums import ClaimType, EvidenceGrade, RelationshipStatus, RelationshipType
from app.validation.state_guard import (
    LEGAL_TRANSITIONS,
    EvidenceFact,
    assert_confidence_cap,
    assert_projectable,
    assert_transition_allowed,
    evaluate_promotion,
)

ALL_STATUSES = list(RelationshipStatus)


def _fact(grade: EvidenceGrade, content_hash: str, relation: str = "supporting") -> EvidenceFact:
    return EvidenceFact(
        evidence_id=content_hash, grade=grade, content_hash=content_hash, relation=relation
    )


# ---------------------------------------------------------------------------
# Transition matrix
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("src", ALL_STATUSES)
def test_matrix_is_complete(src: RelationshipStatus) -> None:
    """Every status must have an entry, otherwise a transition silently KeyErrors."""
    assert src in LEGAL_TRANSITIONS


def test_verified_cannot_go_back_to_candidate() -> None:
    """The core anti-hallucination rule: a verified fact cannot be demoted silently."""
    with pytest.raises(AppError) as exc:
        assert_transition_allowed("verified", "candidate")
    assert exc.value.code is ErrorCode.STATE_TRANSITION_INVALID
    assert exc.value.status_code == 409


def test_verified_cannot_skip_to_rejected() -> None:
    """Rejection goes through disputed, so the evidence trail is not erased."""
    with pytest.raises(AppError):
        assert_transition_allowed("verified", "rejected")


def test_terminal_states_have_no_exit() -> None:
    assert LEGAL_TRANSITIONS[RelationshipStatus.REJECTED] == frozenset()
    assert LEGAL_TRANSITIONS[RelationshipStatus.REVOKED] == frozenset()
    for target in ALL_STATUSES:
        if target in (RelationshipStatus.REJECTED, RelationshipStatus.REVOKED):
            continue
        with pytest.raises(AppError):
            assert_transition_allowed("rejected", target)
        with pytest.raises(AppError):
            assert_transition_allowed("revoked", target)


def test_happy_path_transitions_allowed() -> None:
    assert_transition_allowed("candidate", "pending_review")
    assert_transition_allowed("pending_review", "verified")
    assert_transition_allowed("verified", "revoked")
    assert_transition_allowed("verified", "expired")
    assert_transition_allowed("expired", "pending_review")


def test_same_status_is_idempotent() -> None:
    assert_transition_allowed("verified", "verified")


def test_unknown_status_raises_value_error() -> None:
    with pytest.raises(ValueError):
        assert_transition_allowed("verified", "not_a_status")


# ---------------------------------------------------------------------------
# Promotion: claim -> verified relationship
# ---------------------------------------------------------------------------


def test_fact_with_grade_a_is_promotable() -> None:
    decision = evaluate_promotion("fact_reported", [_fact(EvidenceGrade.A, "h1")])
    assert decision.allowed is True
    assert decision.target_status is RelationshipStatus.VERIFIED


def test_inferred_claim_can_never_be_promoted() -> None:
    """Even with grade-A evidence, an AI inference must not become a verified fact."""
    decision = evaluate_promotion("inferred", [_fact(EvidenceGrade.A, "h1")])
    assert decision.allowed is False
    with pytest.raises(AppError) as exc:
        decision.raise_if_denied()
    assert exc.value.code is ErrorCode.CLAIM_TYPE_NOT_PROMOTABLE


def test_hypothesis_can_never_be_promoted() -> None:
    decision = evaluate_promotion("hypothesis", [_fact(EvidenceGrade.A, "h1")])
    assert decision.allowed is False


def test_single_grade_c_is_not_enough() -> None:
    decision = evaluate_promotion("fact_reported", [_fact(EvidenceGrade.C, "h1")])
    assert decision.allowed is False
    assert "weak evidence" in decision.reasons[-1]


def test_two_distinct_grade_c_is_enough() -> None:
    decision = evaluate_promotion(
        "fact_reported", [_fact(EvidenceGrade.C, "h1"), _fact(EvidenceGrade.C, "h2")]
    )
    assert decision.allowed is True


def test_reposts_do_not_count_twice() -> None:
    """Invariant I-6: same content_hash from five outlets is ONE evidence item."""
    reposts = [_fact(EvidenceGrade.C, "same-hash") for _ in range(5)]
    decision = evaluate_promotion("fact_reported", reposts)
    assert decision.distinct_supporting == 1
    assert decision.allowed is False


def test_contradicting_evidence_forces_disputed() -> None:
    decision = evaluate_promotion(
        "fact_reported",
        [_fact(EvidenceGrade.A, "h1"), _fact(EvidenceGrade.A, "h2", relation="contradicting")],
    )
    assert decision.allowed is True
    assert decision.target_status is RelationshipStatus.DISPUTED


def test_no_evidence_denied() -> None:
    decision = evaluate_promotion("fact_reported", [])
    assert decision.allowed is False
    with pytest.raises(AppError) as exc:
        decision.raise_if_denied()
    assert exc.value.code is ErrorCode.EVIDENCE_REQUIRED


# ---------------------------------------------------------------------------
# Layer separation
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "rtype",
    [
        RelationshipType.POTENTIAL_BENEFICIARY,
        RelationshipType.POTENTIAL_LOSER,
        RelationshipType.POTENTIAL_SUPPLIER,
        RelationshipType.POTENTIAL_CUSTOMER,
    ],
)
def test_candidate_layer_types_never_project(rtype: RelationshipType) -> None:
    """Owner decision 2026-11-13: POTENTIAL_* stays out of the verified graph."""
    with pytest.raises(AppError):
        assert_projectable(rtype, RelationshipStatus.VERIFIED)


@pytest.mark.parametrize("status", ["candidate", "pending_review", "rejected"])
def test_unverified_statuses_never_project(status: str) -> None:
    with pytest.raises(AppError):
        assert_projectable(RelationshipType.SUPPLIES_TO, status)


def test_verified_fact_relationship_projects() -> None:
    assert_projectable(RelationshipType.SUPPLIES_TO, RelationshipStatus.VERIFIED)


# ---------------------------------------------------------------------------
# Confidence caps
# ---------------------------------------------------------------------------


def test_inferred_confidence_capped() -> None:
    with pytest.raises(AppError):
        assert_confidence_cap(ClaimType.INFERRED, 0.9)
    assert_confidence_cap(ClaimType.INFERRED, 0.6)


def test_hypothesis_confidence_capped() -> None:
    with pytest.raises(AppError):
        assert_confidence_cap(ClaimType.HYPOTHESIS, 0.5)
    assert_confidence_cap(ClaimType.HYPOTHESIS, 0.3)
