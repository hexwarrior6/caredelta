import json
import re
import socket
from dataclasses import dataclass
from typing import Protocol
from urllib import request

import phonenumbers
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.models import ExtractionConfidence, RiskLevel, SignalCategory


class AISignal(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: str = Field(min_length=1, max_length=300)
    category: SignalCategory
    risk_level: RiskLevel
    risk_reason: str = Field(min_length=1, max_length=500)
    importance_score: int = Field(ge=0, le=100)
    extraction_confidence: ExtractionConfidence
    confidence_reason: str = Field(min_length=1, max_length=500)
    source_snippet: str = Field(min_length=1, max_length=1_000)


class AIExtraction(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1, max_length=160)
    summary: str = Field(min_length=1, max_length=1_000)
    signals: list[AISignal] = Field(min_length=1, max_length=10)


class LLMAdapter(Protocol):
    def extract(self, sanitized_transcript: str) -> AIExtraction: ...


class MockLLMAdapter:
    """Deterministic adapter for tests without network access or API keys."""

    def __init__(
        self, response: AIExtraction | None = None, error: Exception | None = None
    ) -> None:
        self.response = response
        self.error = error
        self.received_transcripts: list[str] = []

    def extract(self, sanitized_transcript: str) -> AIExtraction:
        self.received_transcripts.append(sanitized_transcript)
        if self.error is not None:
            raise self.error
        if self.response is None:
            raise ValueError("Mock response is not configured")
        return self.response


class DeepSeekAdapter:
    def __init__(
        self,
        base_url: str,
        model: str,
        api_key: str,
        timeout: float,
        max_tokens: int = 1_200,
    ) -> None:
        self._url = f"{base_url.rstrip('/')}/chat/completions"
        self._model = model
        self._api_key = api_key
        self._timeout = timeout
        self._max_tokens = max_tokens

    def extract(self, sanitized_transcript: str) -> AIExtraction:
        schema = AIExtraction.model_json_schema()
        body = json.dumps(
            {
                "model": self._model,
                "temperature": 0,
                "thinking": {"type": "disabled"},
                "max_tokens": self._max_tokens,
                "response_format": {"type": "json_object"},
                "messages": [
                    {
                        "role": "system",
                        "content": (
                            "Generate a concise clinical timeline title and extract candidate "
                            "clinical changes. The title must summarize the interaction without "
                            "including PHI. Return only JSON matching "
                            f"this schema: {json.dumps(schema)}. Every source_snippet must be "
                            "an exact substring of the supplied redacted transcript. Do not "
                            "infer missing facts."
                        ),
                    },
                    {"role": "user", "content": sanitized_transcript},
                ],
            }
        ).encode("utf-8")
        http_request = request.Request(
            self._url,
            data=body,
            headers={
                "Authorization": f"Bearer {self._api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        with request.urlopen(http_request, timeout=self._timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
        content = payload["choices"][0]["message"]["content"].strip()
        if content.startswith("```"):
            content = re.sub(r"^```(?:json)?\s*|\s*```$", "", content)
        return AIExtraction.model_validate_json(content)


@dataclass(frozen=True)
class RedactionResult:
    text: str
    redacted_phi_types: list[str]


_PHI_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("email", re.compile(r"(?i)\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b")),
    (
        "phone",
        re.compile(
            r"(?<!\w)(?:\+?65[\s.-]?)?[3689]\d{3}[\s.-]?\d{4}(?!\w)"
        ),
    ),
    ("id", re.compile(r"(?i)\b[STFGM]\d{7}[A-Z]\b")),
    (
        "id",
        re.compile(r"(?i)\b(?:patient\s+id|medical\s+record\s+number|mrn|id)\s*[:#-]?\s*[A-Z0-9-]{5,}\b"),
    ),
)

_CONTEXTUAL_NAME_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(
        r"(?i)(?P<prefix>\b(?:my name is|patient(?:'s)? name(?: is)?|name)\s*[:=-]?\s*)"
        r"(?P<value>[A-Z][A-Za-z'’-]+(?:\s+[A-Z][A-Za-z'’-]+){1,4})"
    ),
    re.compile(
        r"(?i)\b(?:Dr|Doctor|Nurse|Mr|Mrs|Ms|Miss)\.?\s+"
        r"[A-Z][A-Za-z'’-]+(?:\s+[A-Z][A-Za-z'’-]+){1,4}"
    ),
)


def _redact_phone_numbers(text: str) -> tuple[str, bool]:
    matches = list(phonenumbers.PhoneNumberMatcher(text, "SG"))
    if not matches:
        return text, False
    redacted = text
    for match in reversed(matches):
        redacted = (
            redacted[: match.start]
            + "[REDACTED_PHONE]"
            + redacted[match.end :]
        )
    return redacted, True


def _redact_contextual_names(text: str) -> tuple[str, bool]:
    redacted = text
    found = False
    for pattern in _CONTEXTUAL_NAME_PATTERNS:
        if "prefix" in pattern.groupindex:
            redacted, count = pattern.subn(
                lambda match: f"{match.group('prefix')}[REDACTED_NAME]", redacted
            )
        else:
            redacted, count = pattern.subn("[REDACTED_NAME]", redacted)
        found = found or count > 0
    return redacted, found


def redact_phi(text: str, patient_name: str) -> RedactionResult:
    redacted = text
    found: set[str] = set()
    if patient_name.strip():
        name_pattern = re.compile(re.escape(patient_name.strip()), re.IGNORECASE)
        redacted, count = name_pattern.subn("[REDACTED_NAME]", redacted)
        if count:
            found.add("name")
    redacted, contextual_name_found = _redact_contextual_names(redacted)
    if contextual_name_found:
        found.add("name")
    redacted, phone_found = _redact_phone_numbers(redacted)
    if phone_found:
        found.add("phone")
    for phi_type, pattern in _PHI_PATTERNS:
        redacted, count = pattern.subn(f"[REDACTED_{phi_type.upper()}]", redacted)
        if count:
            found.add(phi_type)
    return RedactionResult(text=redacted, redacted_phi_types=sorted(found))


def validate_grounded_extraction(
    extraction: AIExtraction, sanitized_transcript: str
) -> AIExtraction:
    grounded = [
        signal
        for signal in extraction.signals
        if signal.source_snippet in sanitized_transcript
    ]
    if not grounded:
        raise ValueError("AI extraction contains no source-grounded signals")
    return extraction.model_copy(update={"signals": grounded})


def fallback_extract(sanitized_transcript: str) -> AIExtraction:
    sentences = [
        sentence.strip()
        for sentence in re.split(r"(?<=[.!?])\s+|\n+", sanitized_transcript)
        if sentence.strip()
    ]
    rules = (
        (
            re.compile(r"(?i)reliever|inhaler|wheez|breath|worsen"),
            SignalCategory.WORSENING,
            RiskLevel.HIGH,
            "Respiratory symptom or reliever-use language needs clinical review.",
            90,
        ),
        (
            re.compile(r"(?i)allerg|reaction|conflict|contradic"),
            SignalCategory.CONTRADICTED,
            RiskLevel.HIGH,
            "Potential allergy or record discrepancy needs reconciliation.",
            88,
        ),
        (
            re.compile(r"(?i)not yet|pending|follow[- ]?up|unresolved|await"),
            SignalCategory.UNRESOLVED,
            RiskLevel.MEDIUM,
            "An outstanding action may require care-team follow-up.",
            76,
        ),
        (
            re.compile(r"(?i)again|recur|returned|repeated|another episode"),
            SignalCategory.RECURRING,
            RiskLevel.MEDIUM,
            "A recurring clinical pattern may need longitudinal review.",
            72,
        ),
        (
            re.compile(r"(?i)confirmed|verified|clinician agrees|test shows"),
            SignalCategory.CONFIRMED,
            RiskLevel.LOW,
            "The source explicitly confirms a previously uncertain fact.",
            60,
        ),
    )
    signals: list[AISignal] = []
    for sentence in sentences:
        for pattern, category, risk, reason, score in rules:
            if category == SignalCategory.WORSENING and re.search(
                r"(?i)comfortable at rest|no (?:severe )?breathlessness|no urgent symptoms",
                sentence,
            ):
                continue
            if pattern.search(sentence):
                signals.append(
                    AISignal(
                        text=sentence[:300],
                        category=category,
                        risk_level=risk,
                        risk_reason=reason,
                        importance_score=score,
                        extraction_confidence=ExtractionConfidence.MEDIUM,
                        confidence_reason="Deterministic keyword rule matched an exact source sentence.",
                        source_snippet=sentence[:1_000],
                    )
                )
                break
        if len(signals) == 5:
            break
    if signals:
        title_by_category = {
            SignalCategory.WORSENING: "Worsening symptoms requiring review",
            SignalCategory.CONTRADICTED: "Clinical discrepancy requiring review",
            SignalCategory.UNRESOLVED: "Outstanding follow-up action",
            SignalCategory.RECURRING: "Recurring clinical pattern",
            SignalCategory.CONFIRMED: "Confirmed clinical update",
            SignalCategory.NEW: "New clinical update",
        }
        primary_signal = max(signals, key=lambda signal: signal.importance_score)
        return AIExtraction(
            title=title_by_category[primary_signal.category],
            summary=f"Deterministic extractor found {len(signals)} clinical signal(s) for review.",
            signals=signals,
        )
    snippet = (sentences[0] if sentences else sanitized_transcript).strip()[:1_000]
    return AIExtraction(
        title="New clinical update",
        summary="Deterministic note signal extracted for review.",
        signals=[
            AISignal(
                text=snippet[:300],
                category=SignalCategory.NEW,
                risk_level=RiskLevel.LOW,
                risk_reason="New AI-scribed information requires human review.",
                importance_score=50,
                extraction_confidence=ExtractionConfidence.LOW,
                confidence_reason="No specific deterministic clinical rule matched this text.",
                source_snippet=snippet,
            )
        ],
    )


def extract_with_fallback(
    adapter: LLMAdapter | None, sanitized_transcript: str
) -> tuple[AIExtraction, str, str | None]:
    if adapter is None:
        return fallback_extract(sanitized_transcript), "fallback", "llm_unavailable"
    try:
        extraction = adapter.extract(sanitized_transcript)
    except (TimeoutError, socket.timeout):
        return fallback_extract(sanitized_transcript), "fallback", "timeout"
    except (json.JSONDecodeError, ValidationError, KeyError, IndexError, TypeError, ValueError):
        return fallback_extract(sanitized_transcript), "fallback", "invalid_json"
    except Exception:
        return fallback_extract(sanitized_transcript), "fallback", "llm_unavailable"
    try:
        grounded = validate_grounded_extraction(extraction, sanitized_transcript)
    except ValueError:
        return fallback_extract(sanitized_transcript), "fallback", "provenance_unresolved"
    return grounded, "deepseek", None
