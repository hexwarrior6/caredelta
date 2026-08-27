from datetime import datetime, timezone

from app.models import Highlight, InteractionEvent, RiskLevel, SignalCategory


MAX_LEARNING_BOOST = 12
MAX_LEARNING_REDUCTION = 8
EVENT_WEIGHTS = {
    "pin": 4,
    "comment": 2,
    "edit": 3,
    "highlight": 1,
    "less_relevant": -2,
}


def event_matches_highlight(event: InteractionEvent, highlight: Highlight) -> bool:
    # Direct UI feedback belongs only to the card that was acted on. Topic-level
    # matching made every card in the same category move together.
    return event.highlight_id == highlight.id


def apply_bounded_learning(
    highlight: Highlight,
    events: list[InteractionEvent],
    *,
    now: datetime | None = None,
) -> Highlight:
    relevant = [event for event in events if event_matches_highlight(event, highlight)]
    positive = sum(max(0, EVENT_WEIGHTS.get(event.event_type, 0)) for event in relevant)
    negative = sum(min(0, EVENT_WEIGHTS.get(event.event_type, 0)) for event in relevant)
    event_types = {event.event_type for event in relevant}
    reasons = [
        label
        for event_type, label in (
            ("pin", "boosted_by_prior_pins"),
            ("comment", "boosted_by_prior_comments"),
            ("edit", "boosted_by_prior_edits"),
            ("highlight", "boosted_by_prior_highlight_views"),
            ("less_relevant", "reduced_by_less_relevant_feedback"),
        )
        if event_type in event_types
    ]

    current_time = now or datetime.now(timezone.utc)
    age_days = max(0, (current_time - highlight.created_at).days)
    safety_protected = (
        highlight.risk_level == RiskLevel.HIGH
        or highlight.category in {SignalCategory.CONTRADICTED, SignalCategory.UNRESOLVED}
    )
    if safety_protected:
        net = positive + negative
        adjustment = max(0, min(MAX_LEARNING_BOOST, net))
        if net < 0:
            reasons.append("safety_protected_from_negative_learning")
    else:
        adjustment = max(
            -MAX_LEARNING_REDUCTION,
            min(MAX_LEARNING_BOOST, positive + negative),
        )
    decay = 0
    decay_reason = None
    if not safety_protected and age_days >= 365:
        decay = -12
        decay_reason = "Older than 365 days; retained as a summarized historical signal."
    elif not safety_protected and age_days >= 180:
        decay = -6
        decay_reason = "Older than 180 days; reduced in routine ranking, with source preserved."
    elif safety_protected and age_days >= 180:
        decay_reason = "Safety-protected signal: age decay is not applied."

    base = highlight.base_importance_score or highlight.importance_score
    effective = max(0, min(100, base + adjustment + decay))
    return highlight.model_copy(
        update={
            "importance_score": effective,
            "base_importance_score": base,
            "learning_adjustment": adjustment,
            "learning_reason": ", ".join(reasons) if reasons else None,
            "decay_adjustment": decay,
            "decay_reason": decay_reason,
        }
    )
