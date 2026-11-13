"""Quality control: state guards, evidence threshold, layer separation."""

from app.validation.state_guard import (
    DEFAULT_THRESHOLD,
    LEGAL_TRANSITIONS,
    PROPAGATION_ALLOWED_STATUSES,
    EvidenceFact,
    EvidenceThreshold,
    ReviewDecision,
    ThresholdDecision,
    VerificationDecision,
    assert_can_dispute,
    assert_confidence_cap,
    assert_projectable,
    assert_transition_allowed,
    assert_usable_for_propagation,
    evaluate_review_eligibility,
    evaluate_threshold,
    evaluate_verification,
)

__all__ = [
    "DEFAULT_THRESHOLD",
    "LEGAL_TRANSITIONS",
    "PROPAGATION_ALLOWED_STATUSES",
    "EvidenceFact",
    "EvidenceThreshold",
    "ReviewDecision",
    "ThresholdDecision",
    "VerificationDecision",
    "assert_can_dispute",
    "assert_confidence_cap",
    "assert_projectable",
    "assert_transition_allowed",
    "assert_usable_for_propagation",
    "evaluate_review_eligibility",
    "evaluate_threshold",
    "evaluate_verification",
]
