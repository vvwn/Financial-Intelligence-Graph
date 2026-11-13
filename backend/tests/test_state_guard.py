"""Unit tests for the state machine, threshold and layer rules (no database)."""

from __future__ import annotations

import pytest
from app.core.errors import AppError, ErrorCode
from app.schemas.enums import ClaimType, EvidenceGrade, RelationshipStatus, RelationshipType
from app.validation.state_guard import (
    LEGAL_TRANSITIONS,
    EvidenceFact,
    assert_can_dispute,
    assert_confidence_cap,
    assert_projectable,
    assert_transition_allowed,
    assert_usable_for_propagation,
    evaluate_review_eligibility,
    evaluate_threshold,
    evaluate_verification,
)

ALL_STATUSES = list(RelationshipStatus)


def _fact(
    grade: EvidenceGrade, origin_key: str, relation: str = "supporting"
) -> EvidenceFact:
    return EvidenceFact(
        evidence_id=f"ev-{origin_key}-{relation}",
        grade=grade,
        origin_key=origin_key,
        relation=relation,
    )


# ---------------------------------------------------------------------------
# Transition matrix
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("src", ALL_STATUSES)
def test_matrix_is_complete(src: RelationshipStatus) -> None:
    assert src in LEGAL_TRANSITIONS


def test_verified_cannot_go_back_to_candidate() -> None:
    with pytest.raises(AppError) as exc:
        assert_transition_allowed("verified", "candidate")
    assert exc.value.code is ErrorCode.STATE_TRANSITION_INVALID
    assert exc.value.status_code == 409


def test_verified_cannot_skip_to_rejected() -> None:
    with pytest.raises(AppError):
        assert_transition_allowed("verified", "rejected")


def test_pending_review_cannot_become_disputed() -> None:
    """Reviewer decision: disputed means a VERIFIED fact was challenged.

    A pending item that runs into conflicting evidence simply stays unverified;
    it does not get to claim the "was challenged" state.
    """
    with pytest.raises(AppError) as exc:
        assert_transition_allowed("pending_review", "disputed")
    assert exc.value.code is ErrorCode.STATE_TRANSITION_INVALID
    assert "disputed" not in exc.value.details["allowed"]


def test_disputed_reachable_from_verified_only() -> None:
    assert_transition_allowed("verified", "disputed")
    assert RelationshipStatus.DISPUTED in LEGAL_TRANSITIONS[RelationshipStatus.VERIFIED]
    for src in ALL_STATUSES:
        if src is RelationshipStatus.VERIFIED:
            continue
        assert RelationshipStatus.DISPUTED not in LEGAL_TRANSITIONS[src], src


def test_disputed_can_return_to_verified_or_be_rejected() -> None:
    assert_transition_allowed("disputed", "verified")
    assert_transition_allowed("disputed", "rejected")
    assert_transition_allowed("disputed", "revoked")


def test_terminal_states_have_no_exit() -> None:
    assert LEGAL_TRANSITIONS[RelationshipStatus.REJECTED] == frozenset()
    assert LEGAL_TRANSITIONS[RelationshipStatus.REVOKED] == frozenset()


def test_happy_path_transitions_allowed() -> None:
    assert_transition_allowed("candidate", "pending_review")
    assert_transition_allowed("pending_review", "verified")
    assert_transition_allowed("verified", "expired")
    assert_transition_allowed("expired", "pending_review")


def test_same_status_is_idempotent() -> None:
    assert_transition_allowed("verified", "verified")


# ---------------------------------------------------------------------------
# Evidence threshold: enters review only, never verifies
# ---------------------------------------------------------------------------


def test_grade_a_meets_threshold() -> None:
    decision = evaluate_threshold("fact_reported", [_fact(EvidenceGrade.A, "o1")])
    assert decision.met is True
    assert decision.best_grade is EvidenceGrade.A


def test_single_grade_c_is_not_enough() -> None:
    decision = evaluate_threshold("fact_reported", [_fact(EvidenceGrade.C, "o1")])
    assert decision.met is False
    assert decision.c_origins == 1


def test_two_independent_grade_c_is_enough() -> None:
    decision = evaluate_threshold(
        "fact_reported", [_fact(EvidenceGrade.C, "o1"), _fact(EvidenceGrade.C, "o2")]
    )
    assert decision.met is True
    assert decision.distinct_supporting_origins == 2


def test_reposts_of_one_origin_do_not_count_twice() -> None:
    """Different content_hash is NOT independence; same origin_key is one source."""
    reposts = [_fact(EvidenceGrade.C, "same-origin") for _ in range(5)]
    decision = evaluate_threshold("fact_reported", reposts)
    assert decision.distinct_supporting_origins == 1
    assert decision.c_origins == 1
    assert decision.met is False


def test_inferred_claim_never_meets_threshold() -> None:
    decision = evaluate_threshold("inferred", [_fact(EvidenceGrade.A, "o1")])
    assert decision.met is False
    assert "not promotable" in decision.reasons[0]


def test_threshold_only_grants_review_not_verification() -> None:
    """Threshold queues work; it never approves it."""
    facts = [_fact(EvidenceGrade.A, "o1")]
    review = evaluate_review_eligibility("fact_reported", facts)
    assert review.allowed is True
    assert review.target_status is RelationshipStatus.PENDING_REVIEW

    no_approval = evaluate_verification("fact_reported", facts, approved_by=None)
    assert no_approval.allowed is False
    assert any("explicit approval" in r for r in no_approval.reasons)


def test_automated_actor_cannot_approve() -> None:
    facts = [_fact(EvidenceGrade.A, "o1")]
    decision = evaluate_verification("fact_reported", facts, approved_by="system:pipeline")
    assert decision.allowed is False
    assert any("automated actor" in r for r in decision.reasons)


def test_human_approval_with_threshold_verifies() -> None:
    facts = [_fact(EvidenceGrade.A, "o1")]
    decision = evaluate_verification("fact_reported", facts, approved_by="human:kevin")
    assert decision.allowed is True


def test_contradicting_evidence_blocks_verification() -> None:
    facts = [
        _fact(EvidenceGrade.A, "o1"),
        _fact(EvidenceGrade.A, "o2", relation="contradicting"),
    ]
    decision = evaluate_verification("fact_reported", facts, approved_by="human:kevin")
    assert decision.allowed is False
    assert decision.threshold is not None
    assert decision.threshold.contradicting_origins == 1


def test_dispute_requires_contradicting_evidence() -> None:
    with pytest.raises(AppError) as exc:
        assert_can_dispute([])
    assert exc.value.code is ErrorCode.EVIDENCE_REQUIRED
    assert_can_dispute(["ev-1"])


# ---------------------------------------------------------------------------
# Layer separation and propagation
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
    with pytest.raises(AppError):
        assert_projectable(rtype, RelationshipStatus.VERIFIED)


@pytest.mark.parametrize("status", ["candidate", "pending_review", "rejected"])
def test_unverified_statuses_never_project(status: str) -> None:
    with pytest.raises(AppError):
        assert_projectable(RelationshipType.SUPPLIES_TO, status)


def test_verified_fact_relationship_projects() -> None:
    assert_projectable(RelationshipType.SUPPLIES_TO, RelationshipStatus.VERIFIED)


def test_disputed_projects_but_cannot_drive_propagation() -> None:
    """Disputed edges stay visible in the graph, but never as established fact."""
    assert_projectable(RelationshipType.SUPPLIES_TO, RelationshipStatus.DISPUTED)
    with pytest.raises(AppError) as exc:
        assert_usable_for_propagation("disputed")
    assert exc.value.code is ErrorCode.STATE_TRANSITION_INVALID


@pytest.mark.parametrize(
    "status", ["candidate", "pending_review", "disputed", "expired", "revoked", "rejected"]
)
def test_only_verified_drives_propagation(status: str) -> None:
    with pytest.raises(AppError):
        assert_usable_for_propagation(status)


def test_verified_can_drive_propagation() -> None:
    assert_usable_for_propagation("verified")


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
