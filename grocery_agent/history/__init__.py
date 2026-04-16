"""
Analyzes order history across platforms to learn user preferences
for brands, sizes, and quantities when the user hasn't specified them.
"""
from __future__ import annotations

import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Optional

from grocery_agent.config import HISTORY_DIR
from grocery_agent.platforms.base import OrderHistoryItem


class PreferenceAnalyzer:
    """Learn brand / size preferences from past orders."""

    def __init__(self) -> None:
        # item_keyword → list of (brand, quantity, platform)
        self._history: dict[str, list[dict]] = defaultdict(list)
        self._loaded = False

    # ── loading ───────────────────────────────────────────────
    def load_cached_history(self) -> None:
        """Load all cached order history JSONs from disk."""
        if self._loaded:
            return
        for f in HISTORY_DIR.glob("*.json"):
            try:
                raw = json.loads(f.read_text())
                platform = f.stem
                for item in raw:
                    keywords = self._normalise(item.get("name", ""))
                    for kw in keywords:
                        self._history[kw].append(
                            {
                                "name": item.get("name", ""),
                                "brand": item.get("brand", ""),
                                "quantity": item.get("quantity", ""),
                                "price": item.get("price", 0),
                                "platform": platform,
                            }
                        )
            except Exception:
                continue
        self._loaded = True

    def add_history(
        self, items: list[OrderHistoryItem], platform: str
    ) -> None:
        for item in items:
            keywords = self._normalise(item.name)
            for kw in keywords:
                self._history[kw].append(
                    {
                        "name": item.name,
                        "brand": item.brand,
                        "quantity": item.quantity,
                        "price": item.price,
                        "platform": platform,
                    }
                )

    # ── preference lookup ─────────────────────────────────────
    def preferred_brand(self, item_query: str) -> Optional[str]:
        """Return the most-frequently ordered brand for a search term."""
        matches = self._find_matches(item_query)
        brands = [m["brand"] for m in matches if m.get("brand")]
        if not brands:
            return None
        return Counter(brands).most_common(1)[0][0]

    def preferred_quantity(self, item_query: str) -> Optional[str]:
        """Return the most-frequently ordered quantity/size."""
        matches = self._find_matches(item_query)
        qtys = [m["quantity"] for m in matches if m.get("quantity")]
        if not qtys:
            return None
        return Counter(qtys).most_common(1)[0][0]

    def get_preferences(self, item_query: str) -> dict:
        """Return a dict with best-guess brand and quantity."""
        return {
            "brand": self.preferred_brand(item_query),
            "quantity": self.preferred_quantity(item_query),
        }

    # ── internals ─────────────────────────────────────────────
    def _find_matches(self, query: str) -> list[dict]:
        keywords = self._normalise(query)
        results: list[dict] = []
        for kw in keywords:
            results.extend(self._history.get(kw, []))
        return results

    @staticmethod
    def _normalise(text: str) -> list[str]:
        """Break text into lowercase keywords, filtering noise."""
        stop = {
            "the", "a", "an", "of", "and", "or", "with", "in", "for",
            "to", "is", "it", "on", "at", "by", "from", "add",
        }
        words = text.lower().split()
        return [w for w in words if w not in stop and len(w) > 1]
