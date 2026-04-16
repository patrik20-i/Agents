"""Zepto scraper using Playwright."""
from __future__ import annotations

import re
from grocery_agent.config import PLATFORMS, SEARCH_TIMEOUT
from grocery_agent.platforms.base import (
    BaseScraper,
    ProductResult,
    OrderHistoryItem,
)


class ZeptoScraper(BaseScraper):
    PLATFORM_NAME = "zepto"

    def _login_url(self) -> str:
        return PLATFORMS["zepto"]["base_url"]

    # ── search ────────────────────────────────────────────────
    async def _search_items(self, query: str) -> list[ProductResult]:
        page = self._page
        url = PLATFORMS["zepto"]["search_url"].format(query=query)
        await page.goto(url, wait_until="domcontentloaded")

        try:
            await page.wait_for_selector(
                'a[data-testid="product-card"], '
                'div[data-testid="product-card"], '
                'div[class*="productCard"], '
                'a[href*="/product/"]',
                timeout=SEARCH_TIMEOUT,
            )
        except Exception:
            await page.wait_for_timeout(3000)

        products: list[ProductResult] = []

        cards = await page.query_selector_all(
            'a[data-testid="product-card"], '
            'div[data-testid="product-card"], '
            'div[class*="productCard"], '
            'a[href*="/product/"]'
        )

        if not cards:
            cards = await page.query_selector_all(
                'div[class*="product"], div[class*="Product"], '
                'div[class*="item-widget"]'
            )

        for card in cards[:10]:
            try:
                product = await self._parse_zepto_card(card)
                if product:
                    products.append(product)
            except Exception:
                continue

        return products

    async def _parse_zepto_card(self, card) -> ProductResult | None:
        text = (await card.inner_text()).strip()
        if not text:
            return None

        lines = [l.strip() for l in text.split("\n") if l.strip()]

        name = ""
        brand = ""
        quantity = ""
        price = 0.0
        mrp = 0.0

        for line in lines:
            qty_match = re.search(
                r"(\d+(?:\.\d+)?\s*(?:kg|g|ml|l|ltr|pc|pcs|pack|unit|no|piece)s?)\b",
                line,
                re.I,
            )
            if qty_match and not quantity:
                quantity = qty_match.group(1)

            price_match = re.search(r"₹\s*([\d,]+(?:\.\d+)?)", line)
            if price_match:
                val = float(price_match.group(1).replace(",", ""))
                if price == 0:
                    price = val
                elif mrp == 0:
                    mrp = val
                continue

            if (
                len(line) > len(name)
                and not re.match(r"^[₹\d,.\s%OFF]+$", line, re.I)
                and "add" not in line.lower()
            ):
                name = line

        if mrp == 0.0:
            mrp = price

        if name:
            parts = name.split()
            if len(parts) >= 2:
                brand = parts[0]

        img_el = await card.query_selector("img")
        image_url = ""
        if img_el:
            image_url = await img_el.get_attribute("src") or ""

        return ProductResult(
            name=name or "Unknown",
            brand=brand,
            price=price,
            mrp=mrp,
            quantity=quantity or "1 unit",
            image_url=image_url,
        )

    # ── order history ─────────────────────────────────────────
    async def _fetch_order_history(self, limit: int) -> list[OrderHistoryItem]:
        page = self._page
        await page.goto(
            PLATFORMS["zepto"]["orders_url"], wait_until="domcontentloaded"
        )

        try:
            await page.wait_for_selector(
                'div[class*="order"], div[class*="Order"]',
                timeout=SEARCH_TIMEOUT,
            )
        except Exception:
            await page.wait_for_timeout(3000)

        items: list[OrderHistoryItem] = []

        order_cards = await page.query_selector_all(
            'div[class*="order-card"], div[class*="OrderCard"], '
            'a[href*="/order"]'
        )

        for card in order_cards[:limit]:
            try:
                text = await card.inner_text()
                lines = [l.strip() for l in text.split("\n") if l.strip()]
                name = lines[0] if lines else ""
                price_match = re.search(r"₹\s*([\d,]+(?:\.\d+)?)", text)
                price = (
                    float(price_match.group(1).replace(",", ""))
                    if price_match
                    else 0.0
                )
                items.append(
                    OrderHistoryItem(
                        name=name, brand="", quantity="", price=price
                    )
                )
            except Exception:
                continue

        return items
