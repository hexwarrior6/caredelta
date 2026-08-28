import pytest
from fastapi.testclient import TestClient

from app.dependencies import get_asr_adapter, get_repository
from app.main import app
from app.repositories import MemoryRepository
from app.seed import CLINIC_ID, PATIENT_ID, build_seed_record


client = TestClient(app)


class MockASRAdapter:
    def __init__(self) -> None:
        self.received_audio: list[bytes] = []

    def transcribe(self, audio: bytes, audio_format: str) -> str:
        self.received_audio.append(audio)
        assert audio_format == "ogg"
        return "Patient reports wheeze. Clinician recommends follow-up."


def headers(role: str, actor_id: str):
    return {
        "X-Actor-Id": actor_id,
        "X-Actor-Role": role,
        "X-Clinic-Id": CLINIC_ID,
    }


@pytest.fixture(autouse=True)
def isolated_services():
    repository = MemoryRepository([build_seed_record()])
    adapter = MockASRAdapter()
    app.dependency_overrides[get_repository] = lambda: repository
    app.dependency_overrides[get_asr_adapter] = lambda: adapter
    yield adapter
    app.dependency_overrides.clear()


@pytest.mark.parametrize(
    ("role", "actor_id"),
    [
        ("patient", PATIENT_ID),
        ("staff", "staff-syn-chen"),
        ("clinician", "clinician-syn-lim"),
        ("admin", "admin-syn-morgan"),
    ],
)
def test_each_role_can_transcribe_consult_audio(role: str, actor_id: str, isolated_services) -> None:
    response = client.post(
        f"/api/patients/{PATIENT_ID}/audio-transcription",
        headers=headers(role, actor_id),
        files={"audio": ("consult.webm", b"synthetic-audio", "audio/webm")},
    )

    assert response.status_code == 200
    assert response.json()["engine"] == "volcengine_bigmodel_flash"
    assert response.json()["transcript"].startswith("Patient reports")
    assert isolated_services.received_audio[-1] == b"synthetic-audio"


def test_audio_upload_rejects_unsupported_format() -> None:
    response = client.post(
        f"/api/patients/{PATIENT_ID}/audio-transcription",
        headers=headers("clinician", "clinician-syn-lim"),
        files={"audio": ("notes.txt", b"not-audio", "text/plain")},
    )

    assert response.status_code == 415


def test_browser_webm_codec_content_type_is_normalized(isolated_services) -> None:
    response = client.post(
        f"/api/patients/{PATIENT_ID}/audio-transcription",
        headers=headers("clinician", "clinician-syn-lim"),
        files={
            "audio": (
                "consult.webm",
                b"synthetic-opus-audio",
                "audio/webm;codecs=opus",
            )
        },
    )

    assert response.status_code == 200
    assert response.json()["content_type"] == "audio/webm;codecs=opus"
    assert isolated_services.received_audio[-1] == b"synthetic-opus-audio"
