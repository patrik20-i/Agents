"""
Abstract base for every grocery-platform scraper.

Each subclass must implement:
  - _search_items()   → search for a single item and return candidates
  - _fetch_order_history() → pull recent orders for preference learning
"""
from __future__ import annotations

import asyncio
import json
from abc import ABC, abstractmethod
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Optional

from playwright.async_api import async_playwright, Browser, BrowserContext, Page

from grocery_agent.config import SESSION_DIR, HEADLESS, SLOW_MO, SEARCH_TIMEOUT


# ── Data models ───────────────────────────────────────────────
@dataclass
class ProductResult:
    """A single product found on a platform."""
    name: str
    brand: str
    price: float                # final price (after discount)
    mrp: float                  # original MRP
    quantity: str               # e.g. "1 kg", "500 ml", "6 pcs"
    available: bool = True
    image_url: str = ""
    platform: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class SearchResult:
    """All results for one search query on one platform."""
    query: str
    platform: str
    products: list[ProductResult] = field(default_factory=list)
    error: Optional[str] = None

    def best_match(self) -> Optional[ProductResult]:
        """Return cheapest available product."""
        available = [p for p in self.products if p.available]
        return min(available, key=lambda p: p.price) if available else None


@dataclass
class OrderHistoryItem:
    """A single item from a past order."""
    name: str
    brand: str
    quantity: str
    price: float
    order_date: str = ""


# ── Base scraper ──────────────────────────────────────────────
class BaseScraper(ABC):
    PLATFORM_NAME: str = ""

    def __init__(self) -> None:
        self._playwright = None
        self._browser: Optional[Browser] = None
        self._context: Optional[BrowserContext] = None
        self._page: Optional[Page] = None

    # ── lifecycle ─────────────────────────────────────────────
    async def launch(self) -> None:
        self._playwright = await async_playwright().start()
        state_path = self._state_path()

        self._browser = await self._playwright.chromium.launch(
            headless=HEADLESS,
            slow_mo=SLOW_MO,
        )

        if state_path.exists():
            self._context = await self._browser.new_context(
                storage_state=str(state_path),
                viewport={"width": 1280, "height": 800},
                user_agent=(
                    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
                ),
            )
        else:
            self._context = await self._browser.new_context(
                viewport={"width": 1280, "height": 800},
                user_agent=(
                    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
                ),
            )

        self._page = await self._context.new_page()

    async def close(self) -> None:
        if self._context:
            await self._save_session()
            await self._context.close()
        if self._browser:
            await self._browser.close()
        if self._playwright:
            await self._playwright.stop()

    async def __aenter__(self):
        await self.launch()
        return self

    async def __aexit__(self, *exc):
        await self.close()

    # ── session persistence ───────────────────────────────────
    def _state_path(self) -> Path:
        return SESSION_DIR / f"{self.PLATFORM_NAME}_state.json"

    async def _save_session(self) -> None:
        if self._context:
            state = await self._context.storage_state()
            self._state_path().write_text(json.dumps(state))

    async def is_logged_in(self) -> bool:
        """Check if the saved session is still valid. Subclasses override."""
        return self._state_path().exists()

    async def interactive_login(self) -> None:
        """
        Open a visible browser and wait for the user to log in manually.
        After login, the session is saved automatically.
        """
        # Relaunch in headed mode for login
        await self.close()
        self._playwright = await async_playwright().start()
        self._browser = await self._playwright.chromium.launch(
            headless=False, slow_mo=SLOW_MO
        )
        self._context = await self._browser.new_context(
            viewport={"width": 1280, "height": 800},
        )
        self._page = await self._context.new_page()
        await self._page.goto(self._login_url())

        print(f"\n🔐  Please log in to {self.PLATFORM_NAME} in the browser window.")
        print("    Press ENTER here once you are logged in and on the home page…")
        await asyncio.get_event_loop().run_in_executor(None, input)

        await self._save_session()
        print(f"    ✅  {self.PLATFORM_NAME} session saved.\n")
        await self.close()
        await self.launch()  # relaunch in normal mode

    # ── public API ────────────────────────────────────────────
    async def search(self, query: str) -> SearchResult:
        """Search for a grocery item and return parsed results."""
        try:
            products = await self._search_items(query)
            for p in products:
                p.platform = self.PLATFORM_NAME
            return SearchResult(
                query=query,
                platform=self.PLATFORM_NAME,
                products=products,
            )
        except Exception as e:
            return SearchResult(
                query=query,
                platform=self.PLATFORM_NAME,
                error=str(e),
            )

    async def get_order_history(self, limit: int = 50) -> list[OrderHistoryItem]:
        """Fetch recent order history for preference learning."""
        cache_file = Path(f"data/order_history/{self.PLATFORM_NAME}.json")
        try:
            items = await self._fetch_order_history(limit)
            cache_file.parent.mkdir(parents=True, exist_ok=True)
            cache_file.write_text(
                json.dumps([asdict(i) for i in items], indent=2)
            )
            return items
        except Exception:
            # Fall back to cache
            if cache_file.exists():
                raw = json.loads(cache_file.read_text())
                return [OrderHistoryItem(**r) for r in raw]
            return []

    # ── abstract methods ──────────────────────────────────────
    @abstractmethod
    async def _search_items(self, query: str) -> list[ProductResult]:
        ...

    @abstractmethod
    async def _fetch_order_history(self, limit: int) -> list[OrderHistoryItem]:
        ...

    @abstractmethod
    def _login_url(self) -> str:
        ...
