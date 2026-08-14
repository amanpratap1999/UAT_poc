"""Puter-backed visual grounding integration for UI-TARS."""

from __future__ import annotations

import base64
import io

from agent.core.logging import get_logger
from agent.perception.models import BoundingBox, GroundingFailure, PerceptionCandidate
from agent.perception.parser import GroundingResponseParser

logger = get_logger(__name__)


class PuterUiTarsBackend:
    """Backend for visual grounding via Puter's hosted UI-TARS API."""

    def __init__(self, endpoint_url: str, api_key: str | None = None) -> None:
        if not endpoint_url:
            raise ValueError("endpoint_url is required for PuterUiTarsBackend")
        self.endpoint_url = endpoint_url
        self.api_key = api_key
        self.parser = GroundingResponseParser()

    async def ground_element(
        self,
        screenshot_bytes: bytes,
        target_description: str,
        threshold: float = 0.8,
        frame_context: str | None = None,
    ) -> PerceptionCandidate | None:
        """Locate an element using the Puter UI-TARS endpoint.

        Returns None if no candidate meets the threshold.
        Raises GroundingFailure if the API request fails critically.
        """
        import httpx

        # (Optional) Annotation step if Puter UI-TARS requires grid annotations.
        annotated_bytes = self._annotate_screenshot(screenshot_bytes)
        b64_image = base64.b64encode(annotated_bytes).decode("utf-8")

        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        payload = {
            "model": "bytedance/ui-tars-1.5-7b",
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": target_description},
                        {
                            "type": "image_url",
                            "image_url": {"url": f"data:image/png;base64,{b64_image}"},
                        },
                    ],
                }
            ],
            "temperature": 0.1,
            "max_tokens": 1024,
        }

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(self.endpoint_url, json=payload, headers=headers)
                response.raise_for_status()
                data = response.json()
        except httpx.RequestError as e:
            logger.error("puter_api_unavailable", error=str(e), url=self.endpoint_url)
            raise GroundingFailure(f"Puter API connection failed: {e}") from e
        except httpx.HTTPStatusError as e:
            logger.error("puter_api_http_error", status_code=e.response.status_code)
            raise GroundingFailure(f"Puter API HTTP error: {e.response.status_code}") from e
        except Exception as e:
            logger.error("puter_api_unknown_error", error=str(e))
            raise GroundingFailure(f"Puter API unknown error: {e}") from e

        # Parse the raw Puter data
        result = self.parser.parse_response(data, threshold=threshold)
        if not result:
            return None

        return PerceptionCandidate(
            source="vision",
            target_description=target_description,
            confidence=result.confidence,
            bounding_box=BoundingBox(
                x=result.x,
                y=result.y,
                width=result.width,
                height=result.height,
            ),
            frame_context=frame_context,
            label=result.label,
        )

    def _annotate_screenshot(self, screenshot_bytes: bytes) -> bytes:
        """Annotate the screenshot if required by UI-TARS 1.5."""
        try:
            from PIL import Image
        except ImportError:
            logger.warning("pillow_not_installed_skipping_annotation")
            return screenshot_bytes

        try:
            image = Image.open(io.BytesIO(screenshot_bytes))
            out_bytes = io.BytesIO()
            image.save(out_bytes, format="PNG")
            return out_bytes.getvalue()
        except Exception as e:
            logger.error("screenshot_annotation_failed", error=str(e))
            return screenshot_bytes
