import base64
import json
from typing import Protocol
from urllib import request
from uuid import uuid4


class ASRAdapter(Protocol):
    def transcribe(self, audio: bytes, audio_format: str) -> str: ...


class VolcengineASRAdapter:
    """Server-side adapter for Volcengine BigModel flash audio recognition."""

    def __init__(self, *, url: str, api_key: str, timeout: float) -> None:
        self._url = url
        self._api_key = api_key
        self._timeout = timeout

    def transcribe(self, audio: bytes, audio_format: str) -> str:
        body = json.dumps(
            {
                "audio": {
                    "data": base64.b64encode(audio).decode("ascii"),
                    "format": audio_format,
                },
                "request": {
                    "model_name": "bigmodel",
                    "enable_itn": True,
                    "enable_punc": True,
                    "show_utterances": True,
                },
            }
        ).encode("utf-8")
        http_request = request.Request(
            self._url,
            data=body,
            headers={
                "X-Api-Key": self._api_key,
                "X-Api-Resource-Id": "volc.bigasr.auc_turbo",
                "X-Api-Request-Id": str(uuid4()),
                "X-Api-Sequence": "-1",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        with request.urlopen(http_request, timeout=self._timeout) as response:
            api_message = response.headers.get("X-Api-Message")
            payload = json.loads(response.read().decode("utf-8"))
        if api_message and api_message.upper() != "OK":
            raise ValueError(f"Volcengine ASR rejected the request: {api_message}")
        result = payload.get("result")
        if isinstance(result, dict):
            transcript = str(result.get("text", "")).strip()
        elif isinstance(result, list):
            transcript = " ".join(
                str(item.get("text", "")).strip()
                for item in result
                if isinstance(item, dict) and item.get("text")
            ).strip()
        else:
            transcript = ""
        if not transcript:
            raise ValueError("Volcengine returned no transcript")
        return transcript
