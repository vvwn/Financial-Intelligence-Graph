"""Quality control: state guards, evidence rules, layer separation.

This module is the single gate between "the model said so" and "the graph says so".
Every rule here is pure (no I/O) so it can be unit-tested without a database.
"""

from app.validation.state_guard import (
    LEGAL_TRANSITIONS,
    PromotionDecision,
    assert_confidence_cap,
    assert_projectable,
    assert_transition_allowed,
    evaluate_promotion,
)

__all__ = [
    "LEGAL_TRANSITIONS",
    "PromotionDecision",
    "assert_confidence_cap",
    "assert_projectable",
    "assert_transition_allowed",
    "evaluate_promotion",
]
