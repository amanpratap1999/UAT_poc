"""Provider-agnostic visual grounding integration."""

from __future__ import annotations

import base64
import io
import os
import re
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

from agent.core.logging import get_logger
from agent.perception.models import BoundingBox, GroundingFailure, PerceptionCandidate
from agent.perception.parser import GroundingResponseParser

if TYPE_CHECKING:
    from playwright.async_api import Page

logger = get_logger(__name__)


class GrounderBackend(ABC):
    """Abstract interface for visual grounding providers."""

    @abstractmethod
    async def ground_element(
        self,
        screenshot_bytes: bytes,
        target_description: str,
        threshold: float = 0.8,
        frame_context: str | None = None,
        page: Page | None = None,
    ) -> PerceptionCandidate | None:
        """Locate an element visually.

        Args:
            screenshot_bytes: Raw PNG bytes.
            target_description: Natural language description.
            threshold: Confidence threshold.
            frame_context: Optional frame identifier.
            page: Playwright Page object, if the backend requires live DOM access for overlays.
        """
        pass


class LocalUiTarsBackend(GrounderBackend):
    """Backend for visual grounding via Puter's hosted UI-TARS API."""

    def __init__(self, endpoint_url: str, api_key: str | None = None) -> None:
        if not endpoint_url:
            raise ValueError("endpoint_url is required for LocalUiTarsBackend")
        self.endpoint_url = endpoint_url
        self.api_key = api_key
        self.parser = GroundingResponseParser()

    async def ground_element(
        self,
        screenshot_bytes: bytes,
        target_description: str,
        threshold: float = 0.8,
        frame_context: str | None = None,
        page: Page | None = None,
    ) -> PerceptionCandidate | None:
        import httpx

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
        except Exception as e:
            raise GroundingFailure(f"Puter API error: {e}") from e

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
        try:
            from PIL import Image

            image = Image.open(io.BytesIO(screenshot_bytes))
            out_bytes = io.BytesIO()
            image.save(out_bytes, format="PNG")
            return out_bytes.getvalue()
        except Exception:
            return screenshot_bytes


class MoondreamBackend(GrounderBackend):
    """Backend for Moondream visual grounding."""

    def __init__(self, api_key: str | None = None) -> None:
        self.api_key = api_key or os.environ.get("MOONDREAM_API_KEY")
        if not self.api_key:
            raise ValueError("MOONDREAM_API_KEY is required")
        import moondream as md  # type: ignore[import-untyped]

        self.model = md.vl(api_key=self.api_key)

    async def ground_element(
        self,
        screenshot_bytes: bytes,
        target_description: str,
        threshold: float = 0.8,
        frame_context: str | None = None,
        page: Page | None = None,
    ) -> PerceptionCandidate | None:
        from PIL import Image

        img = Image.open(io.BytesIO(screenshot_bytes)).convert("RGB")
        width, height = img.size

        try:
            encoded = self.model.encode_image(img)

            # Detect
            detect_res = self.model.detect(encoded, target_description)
            if hasattr(detect_res, "objects") and detect_res.objects:
                obj = detect_res.objects[0]
                return PerceptionCandidate(
                    source="moondream",
                    target_description=target_description,
                    confidence=1.0,
                    bounding_box=BoundingBox(
                        x=int(obj.x_min * width),
                        y=int(obj.y_min * height),
                        width=int((obj.x_max - obj.x_min) * width),
                        height=int((obj.y_max - obj.y_min) * height),
                    ),
                    frame_context=frame_context,
                )
            elif isinstance(detect_res, dict) and detect_res.get("objects"):
                obj = detect_res["objects"][0]
                return PerceptionCandidate(
                    source="moondream",
                    target_description=target_description,
                    confidence=1.0,
                    bounding_box=BoundingBox(
                        x=int(obj["x_min"] * width),
                        y=int(obj["y_min"] * height),
                        width=int((obj["x_max"] - obj["x_min"]) * width),
                        height=int((obj["y_max"] - obj["y_min"]) * height),
                    ),
                    frame_context=frame_context,
                )

            # Point Fallback
            point_res = self.model.point(encoded, target_description)
            pt = None
            if hasattr(point_res, "points") and point_res.points:
                pt = point_res.points[0]
                x, y = pt.x, pt.y
            elif isinstance(point_res, dict) and point_res.get("points"):
                x, y = point_res["points"][0]["x"], point_res["points"][0]["y"]

            if pt or (isinstance(point_res, dict) and point_res.get("points")):
                px, py = int(x * width), int(y * height)
                return PerceptionCandidate(
                    source="moondream",
                    target_description=target_description,
                    confidence=1.0,
                    bounding_box=BoundingBox(x=px - 5, y=py - 5, width=10, height=10),
                    frame_context=frame_context,
                )
        except Exception as e:
            raise GroundingFailure(f"Moondream failed: {e}") from e

        return None


class GeminiBackend(GrounderBackend):
    """Backend for Gemini Flash visual grounding using Set-of-Mark overlays."""

    def __init__(self, api_key: str | None = None) -> None:
        self.api_key = api_key or os.environ.get("GEMINI_API_KEY")
        if not self.api_key:
            raise ValueError("GEMINI_API_KEY is required")
        import google.generativeai as genai  # type: ignore[import-untyped]

        genai.configure(api_key=self.api_key)
        self.model = genai.GenerativeModel("gemini-2.5-flash")

    async def ground_element(
        self,
        screenshot_bytes: bytes,
        target_description: str,
        threshold: float = 0.8,
        frame_context: str | None = None,
        page: Page | None = None,
    ) -> PerceptionCandidate | None:
        if not page:
            raise GroundingFailure("GeminiBackend requires page object for overlays.")

        # Gather candidate elements via JS
        boxes = await page.evaluate("""() => {
            return Array.from(document.querySelectorAll('button, a, input, select, textarea, [role="button"], [role="link"], [role="tab"], [role="menuitem"]'))
                .map((el, idx) => {
                    const rect = el.getBoundingClientRect();
                    return {id: idx + 1, x: rect.x, y: rect.y, width: rect.width, height: rect.height};
                })
                .filter(b => b.width > 0 && b.height > 0 && b.x >= 0 && b.y >= 0);
        }""")

        if not boxes:
            return None

        from PIL import Image, ImageDraw

        img = Image.open(io.BytesIO(screenshot_bytes)).convert("RGB")
        draw = ImageDraw.Draw(img)

        # Draw overlays
        for b in boxes:
            x, y, w, h = b["x"], b["y"], b["width"], b["height"]
            draw.rectangle([x, y, x + w, y + h], outline="red", width=2)
            draw.rectangle([x, y, x + 22, y + 14], fill="red")
            draw.text((x + 2, y + 1), str(b["id"]), fill="white")

        overlay_bytes = io.BytesIO()
        img.save(overlay_bytes, format="PNG")
        overlay_bytes.seek(0)
        annotated_img = Image.open(overlay_bytes)

        prompt = f"Identify the ID number of the UI element corresponding to '{target_description}'. Respond with ONLY the integer."

        try:
            response = await self.model.generate_content_async([prompt, annotated_img])
            idx_str = response.text.strip()
            m = re.search(r"\d+", idx_str)
            if not m:
                return None

            target_id = int(m.group())
            for b in boxes:
                if b["id"] == target_id:
                    return PerceptionCandidate(
                        source="gemini_overlay",
                        target_description=target_description,
                        confidence=0.9,
                        bounding_box=BoundingBox(
                            x=int(b["x"]),
                            y=int(b["y"]),
                            width=int(b["width"]),
                            height=int(b["height"]),
                        ),
                        frame_context=frame_context,
                    )
        except Exception as e:
            raise GroundingFailure(f"Gemini failed: {e}") from e

        return None


class PerceptionRouter(GrounderBackend):
    """Router that attempts Primary provider, and on failure tries Fallback."""

    def __init__(
        self,
        primary: GrounderBackend,
        fallback: GrounderBackend | None = None,
        local: GrounderBackend | None = None,
    ) -> None:
        self.primary = primary
        self.fallback = fallback
        self.local = local

    async def ground_element(
        self,
        screenshot_bytes: bytes,
        target_description: str,
        threshold: float = 0.8,
        frame_context: str | None = None,
        page: Page | None = None,
    ) -> PerceptionCandidate | None:
        logger.info("routing_grounding_request", target=target_description, provider="primary")
        try:
            res = await self.primary.ground_element(
                screenshot_bytes, target_description, threshold, frame_context, page
            )
            if res:
                logger.info("primary_grounding_success", target=target_description)
                return res
        except Exception as e:
            logger.warning(
                "primary_grounding_failed", error=str(e), fallback_available=bool(self.fallback)
            )

        if self.fallback:
            logger.info("routing_grounding_request", target=target_description, provider="fallback")
            try:
                res = await self.fallback.ground_element(
                    screenshot_bytes, target_description, threshold, frame_context, page
                )
                if res:
                    logger.info("fallback_grounding_success", target=target_description)
                    return res
            except Exception as e:
                logger.warning("fallback_grounding_failed", error=str(e))

        return None
