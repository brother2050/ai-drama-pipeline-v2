"""多人同框处理"""
from __future__ import annotations
import logging

logger = logging.getLogger(__name__)


class MultiCharacterHandler:
    """多人同框场景处理器"""

    def generate_multi_char_prompt(self, characters: list[dict], layout: str = "side_by_side") -> str:
        """生成多人同框 prompt"""
        if not characters:
            return ""
        if len(characters) <= 1:
            char = characters[0] if characters else {}
            return char.get("appearance_prompt_en", char.get("appearance", ""))

        parts = []
        for i, char in enumerate(characters):
            desc = char.get("appearance_prompt_en", char.get("appearance", ""))
            if layout == "side_by_side":
                pos = "on the left" if i % 2 == 0 else "on the right"
            else:
                pos = f"position {i+1}"
            parts.append(f"{desc}, {pos}")
        return ", ".join(parts)

    def calculate_regions(self, count: int, layout: str = "side_by_side") -> list[dict]:
        if not count or count <= 1:
            return [{"position": "center", "x": 0.5, "y": 0.5}]
        return [{"position": "left" if i % 2 == 0 else "right",
                 "x": 0.25 + 0.5 * (i % 2), "y": 0.5} for i in range(count)]
