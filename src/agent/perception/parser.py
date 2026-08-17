"""Parser for Puter UI-TARS API responses."""

import re
from typing import Any

from agent.core.logging import get_logger
from agent.perception.models import GroundingFailure, GroundingResult

logger = get_logger(__name__)


class GroundingResponseParser:
    """Parses JSON responses from the Puter API into domain models."""

    @staticmethod
    def parse_response(data: dict[str, Any], threshold: float = 0.8) -> GroundingResult | None:
        """Parse raw JSON data from Puter.

        Expected data format: Standard OpenAI ChatCompletion response.
        The model content should contain: Action: click(point='<point>x y</point>')
        """
        choices = data.get("choices")
        if not choices or not isinstance(choices, list) or not choices[0].get("message"):
            logger.error("invalid_openai_response", data=data)
            raise GroundingFailure("Missing 'choices' or 'message' in response")

        content = choices[0]["message"].get("content")
        if not content:
            logger.error("empty_content", data=data)
            raise GroundingFailure("Response content is empty")

        # Returns coords like: point='<point>123 456</point>' or <|box_start|>(x, y)<|box_end|>
        point_match = re.search(r"<point>(\d+)\s+(\d+)</point>", content)
        if not point_match:
            # Fallback to alternate box format if applicable
            box_match = re.search(r"<\|box_start\|>\((\d+),\s*(\d+)\)<\|box_end\|>", content)
            if not box_match:
                logger.error("no_coordinates_found", content=content)
                raise GroundingFailure("Failed to extract point from action")
            point_match = box_match

        x = int(point_match.group(1))
        y = int(point_match.group(2))

        # We assume None as UI-TARS does not output confidence scores natively here.
        conf = None

        return GroundingResult(
            x=x,
            y=y,
            width=1,  # User approved 1x1 bounding box for point coordinates
            height=1,
            confidence=conf,
            label=content,
        )
