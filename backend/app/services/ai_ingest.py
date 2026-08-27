import json
import re
import socket
from dataclasses import dataclass
from typing import Protocol
from urllib import request

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.models import RiskLevel, SignalCategory


class AISignal(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: str = Field(min_length=1, max_length=300)
    category: SignalCategory
    risk_level: RiskLevel
    risk_reason: str = Field(min_length=1, max_length=500)
    importance_score: int = Field(ge=0, le=100)
    source_snippet: str = Field(min_length=1, max_length=1_000)


class AIExtraction(BaseModel):
    model_config = ConfigDict(extra="forbid")

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
                            "Extract candidate clinical changes. Return only JSON matching "
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
        re.compile(r"(?<!\w)(?:\+?\d{1,3}[\s.-]?)?(?:\(?\d{2,4}\)?[\s.-]?)\d{3,4}[\s.-]?\d{4}(?!\w)"),
    ),
    ("id", re.compile(r"(?i)\b[STFGM]\d{7}[A-Z]\b")),
    (
        "id",
        re.compile(r"(?i)\b(?:patient\s+id|medical\s+record\s+number|mrn|id)\s*[:#-]?\s*[A-Z0-9-]{5,}\b"),
    ),
)


def redact_phi(text: str, patient_name: str) -> RedactionResult:
    redacted = text
    found: set[str] = set()
    if patient_name.strip():
        name_pattern = re.compile(re.escape(patient_name.strip()), re.IGNORECASE)
        redacted, count = name_pattern.subn("[REDACTED_NAME]", redacted)
        if count:
            found.add("name")
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
            re.compile(r"(?i)reliever|inhaler|wheez|breath"),
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
                        source_snippet=sentence[:1_000],
                    )
                )
                break
        if len(signals) == 5:
            break
    if signals:
        return AIExtraction(
            summary=f"Deterministic extractor found {len(signals)} clinical signal(s) for review.",
            signals=signals,
        )
    snippet = (sentences[0] if sentences else sanitized_transcript).strip()[:1_000]
    return AIExtraction(
        summary="Deterministic note signal extracted for review.",
        signals=[
            AISignal(
                text=snippet[:300],
                category=SignalCategory.NEW,
                risk_level=RiskLevel.LOW,
                risk_reason="New AI-scribed information requires human review.",
                importance_score=50,
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
