import re
from dataclasses import dataclass

from app.models import (
    ExtractionConfidence,
    ProvenanceConfidence,
    RiskLevel,
    SignalCategory,
    TrustStatus,
)


_RISK_WEIGHT = {RiskLevel.LOW: 1, RiskLevel.MEDIUM: 2, RiskLevel.HIGH: 3}
_CONFIDENCE_WEIGHT = {
    ExtractionConfidence.LOW: 0,
    ExtractionConfidence.MEDIUM: 8,
    ExtractionConfidence.HIGH: 15,
}
_CATEGORY_WEIGHT = {
    SignalCategory.NEW: 4,
    SignalCategory.WORSENING: 12,
    SignalCategory.RECURRING: 7,
    SignalCategory.UNRESOLVED: 9,
    SignalCategory.CONTRADICTED: 12,
    SignalCategory.CONFIRMED: 5,
}


@dataclass(frozen=True)
class DeltaEvaluation:
    risk_level: RiskLevel
    risk_floor_applied: bool
    risk_floor_reason: str | None
    importance_score: int
    importance_reason: str
    trust_status: TrustStatus
    abstained_from_glance: bool
    abstention_reason: str | None


def _risk_floor(text: str, category: SignalCategory) -> tuple[RiskLevel, str | None]:
    if category == SignalCategory.CONTRADICTED or re.search(
        r"(?i)allerg|anaphyl|severe breath|chest pain|suicid|overdose", text
    ):
        return RiskLevel.HIGH, "Safety-critical or contradictory language has a deterministic high-risk floor."
    if category in {SignalCategory.WORSENING, SignalCategory.UNRESOLVED} or re.search(
        r"(?i)worsen|short of breath|missed dose|not yet|pending|follow[- ]?up", text
    ):
        return RiskLevel.MEDIUM, "Worsening symptoms or unresolved care actions have a deterministic medium-risk floor."
    return RiskLevel.LOW, None


def evaluate_signal(
    *,
    text: str,
    category: SignalCategory,
    proposed_risk: RiskLevel,
    extraction_confidence: ExtractionConfidence,
    provenance_confidence: ProvenanceConfidence,
) -> DeltaEvaluation:
    category = SignalCategory(category)
    proposed_risk = RiskLevel(proposed_risk)
    extraction_confidence = ExtractionConfidence(extraction_confidence)
    provenance_confidence = ProvenanceConfidence(provenance_confidence)
    floor, floor_reason = _risk_floor(text, category)
    final_risk = max((proposed_risk, floor), key=_RISK_WEIGHT.__getitem__)
    floor_applied = _RISK_WEIGHT[final_risk] > _RISK_WEIGHT[proposed_risk]

    reasons: list[str] = []
    if extraction_confidence == ExtractionConfidence.LOW:
        reasons.append("low extraction confidence")
    if provenance_confidence == ProvenanceConfidence.LOW:
        reasons.append("low provenance confidence")
    if category == SignalCategory.CONTRADICTED:
        reasons.append("conflicting clinical evidence")

    abstained = bool(reasons)
    trust_status = TrustStatus.NEEDS_REVIEW if abstained else TrustStatus.AI_SUGGESTED
    base = {RiskLevel.LOW: 35, RiskLevel.MEDIUM: 58, RiskLevel.HIGH: 75}[final_risk]
    importance = min(
        100,
        base + _CATEGORY_WEIGHT[category] + _CONFIDENCE_WEIGHT[extraction_confidence],
    )
    importance_reason = (
        f"{final_risk.value.title()} risk base {base} + "
        f"{category.value} category {_CATEGORY_WEIGHT[category]} + "
        f"{extraction_confidence.value} confidence {_CONFIDENCE_WEIGHT[extraction_confidence]}."
    )
    return DeltaEvaluation(
        risk_level=final_risk,
        risk_floor_applied=floor_applied,
        risk_floor_reason=floor_reason if floor_applied else None,
        importance_score=importance,
        importance_reason=importance_reason,
        trust_status=trust_status,
        abstained_from_glance=abstained,
        abstention_reason=(
            "Not promoted to the glance card: " + ", ".join(reasons) + "."
            if reasons
            else None
        ),
    )


def is_glance_eligible(*, trust_status: TrustStatus, abstained: bool) -> bool:
    return trust_status == TrustStatus.CLINICIAN_CONFIRMED or (
        trust_status == TrustStatus.AI_SUGGESTED and not abstained
    )
