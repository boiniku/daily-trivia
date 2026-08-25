import html
import os
from collections.abc import Iterable

import requests


class AivisTTSClient:
    """Small client for Aivis Cloud API's synchronous speech endpoint."""

    def __init__(
        self,
        api_key: str | None = None,
        *,
        base_url: str | None = None,
        session=requests,
    ):
        self.api_key = (api_key or os.getenv("AIVIS_API_KEY", "")).strip()
        self.base_url = (
            base_url or os.getenv("AIVIS_API_BASE_URL", "https://api.aivis-project.com/v1")
        ).rstrip("/")
        self.session = session

    def synthesize(
        self,
        text: str,
        *,
        style_name: str | None = None,
        model_uuid: str | None = None,
        speaker_uuid: str | None = None,
    ) -> bytes:
        if not self.api_key:
            raise RuntimeError("AIVIS_API_KEY is not configured")
        model_uuid = (model_uuid or os.getenv("AIVIS_MODEL_UUID", "")).strip()
        if not model_uuid:
            raise RuntimeError("AIVIS_MODEL_UUID is not configured")
        value = str(text or "").strip()
        if not value:
            raise ValueError("Narration is empty")

        payload = {
            "model_uuid": model_uuid,
            "text": value,
            "use_ssml": True,
            "use_volume_normalizer": True,
            "language": "ja",
            "speaking_rate": _float_env("AIVIS_SPEAKING_RATE", 1.08, 0.5, 2.0),
            "emotional_intensity": _float_env(
                "AIVIS_EMOTIONAL_INTENSITY", 1.0, 0.0, 2.0
            ),
            "tempo_dynamics": _float_env("AIVIS_TEMPO_DYNAMICS", 1.05, 0.0, 2.0),
            "pitch": _float_env("AIVIS_PITCH", 0.0, -1.0, 1.0),
            "volume": _float_env("AIVIS_VOLUME", 1.0, 0.0, 2.0),
            "leading_silence_seconds": 0.05,
            "trailing_silence_seconds": 0.12,
            "line_break_silence_seconds": 0.25,
            "output_format": "mp3",
            "output_bitrate": 128,
            "output_sampling_rate": 44100,
            "output_audio_channels": "mono",
        }
        selected_speaker = (speaker_uuid or os.getenv("AIVIS_SPEAKER_UUID", "")).strip()
        selected_style = (style_name or os.getenv("AIVIS_STYLE_NAME", "")).strip()
        dictionary_uuid = os.getenv("AIVIS_USER_DICTIONARY_UUID", "").strip()
        if selected_speaker:
            payload["speaker_uuid"] = selected_speaker
        if selected_style:
            payload["style_name"] = selected_style
        if dictionary_uuid:
            payload["user_dictionary_uuid"] = dictionary_uuid

        response = self.session.post(
            f"{self.base_url}/tts/synthesize",
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            json=payload,
            timeout=(10, 180),
        )
        try:
            response.raise_for_status()
        except requests.HTTPError as exc:
            status_code = getattr(response, "status_code", None)
            reason = {
                401: "API key was rejected",
                402: "credit balance is insufficient",
                404: "voice model was not found",
                422: "voice model, style, or synthesis settings are invalid",
                429: "rate limit was reached",
                503: "service is temporarily unavailable",
            }.get(status_code, "request failed")
            detail = _safe_error_detail(response)
            suffix = f" ({detail})" if detail else ""
            raise RuntimeError(
                f"Aivis speech generation failed: {reason}{suffix}"
            ) from exc
        if not response.content:
            raise RuntimeError("Aivis speech generation returned empty audio")
        return response.content


def build_narration_ssml(lines: Iterable[str], *, style_name: str | None = None) -> str:
    """Keep scene boundaries audible without generating one paid request per scene."""
    values = [str(line).strip() for line in lines if str(line).strip()]
    if not values:
        raise ValueError("Narration is empty")
    sentences = []
    for index, value in enumerate(values):
        escaped = html.escape(value, quote=False)
        if index == 0 and style_name:
            escaped_style = html.escape(style_name, quote=True)
            escaped = (
                f'<aivis:emotion style="{escaped_style}" intensity="1.1">'
                f"{escaped}</aivis:emotion>"
            )
        sentences.append(f"<s>{escaped}</s>")
    return "<speak>" + '<break time="180ms"/>'.join(sentences) + "</speak>"


def generate_aivis_narration(
    lines: Iterable[str],
    *,
    client: AivisTTSClient | None = None,
    style_name: str | None = None,
) -> bytes:
    client = client or AivisTTSClient()
    hook_style = style_name or os.getenv("AIVIS_HOOK_STYLE_NAME", "").strip() or None
    return client.synthesize(
        build_narration_ssml(lines, style_name=hook_style),
        style_name=style_name,
    )


def _float_env(name: str, default: float, minimum: float, maximum: float) -> float:
    try:
        value = float(os.getenv(name, str(default)))
    except ValueError:
        value = default
    return max(minimum, min(value, maximum))


def _safe_error_detail(response) -> str:
    """Return API validation detail while never echoing request headers or keys."""
    try:
        payload = response.json()
    except (ValueError, TypeError):
        return ""
    if not isinstance(payload, dict):
        return ""
    detail = payload.get("detail")
    if isinstance(detail, str):
        return detail[:300]
    if isinstance(detail, list):
        messages = []
        for item in detail[:3]:
            if isinstance(item, dict):
                location = ".".join(str(part) for part in item.get("loc", []))
                message = str(item.get("msg", "invalid value"))
                messages.append(f"{location}: {message}" if location else message)
        return "; ".join(messages)[:300]
    return ""
