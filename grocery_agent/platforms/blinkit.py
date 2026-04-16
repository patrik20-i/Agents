"""Blinkit scraper using Playwright."""
from __future__ import annotations

import re
from grocery_agent.config import PLATFORMS, SEARCH_TIMEOUT
from grocery_agent.platforms.base import (
    BaseScraper,
    ProductResult,
    OrderHistoryItem,
)


class BlinkitScraper(BaseScraper):
    PLATFORM_NAME = "blinkit"

    def _login_url(self) -> str:
        return PLATFORMS["blinkit"]["base_url"]

    # ── search ────────────────────────────────────────────────
    async def _search_items(self, query: str) -> list[ProductResult]:
        page = self._page
        url = PLATFORMS["blinkit"]["search_url"].format(query=query)
        await page.goto(url, wait_until="domcontentloaded")

        try:
            await page.wait_for_selector(
                'div[class*="Product__UpdatedPlpProductContainer"], '
                'a[class*="Product__UpdatedPlpProductContainer"], '
                'div[class*="plp-product"], '
                'div[role="listitem"]',
                timeout=SEARCH_TIMEOUT,
            )
        except Exception:
            await page.wait_for_timeout(3000)

        products: list[ProductResult] = []

        cards = await page.query_selector_all(
            'div[class*="Product__UpdatedPlpProductContainer"], '
            'a[class*="Product__UpdatedPlpProductContainer"], '
            'div[class*="plp-product"], '
            'div[role="listitem"]'
        )

        if not cards:
            cards = await page.query_selector_all(
                'div[class*="product"], div[class*="Product"], '
                'div[class*="item-card"]'
            )

        for card in cards[:10]:
            try:
                product = await self._parse_blinkit_card(card)
                if product:
                    products.append(product)
            except Exception:
                continue

        return products

    async def _parse_blinkit_card(self, card) -> ProductResult | None:
        text = (await card.inner_text()).strip()
        if not text:
            return None

        lines = [l.strip() for l in text.split("\n") if l.strip()]

        # Blinkit typically shows: quantity, name, price, mrp
        name = ""
        brand = ""
        quantity = ""
        price = 0.0
        mrp = 0.0

        for line in lines:
            # Quantity: "500 g", "1 kg", "1 L", etc.
            qty_match = re.search(
                r"^(\d+(?:\.\d+)?\s*(?:kg|g|ml|l|ltr|pc|pcs|pack|unit|no)s?)$",
                line,
                re.I,
            )
            if qty_match and not quantity:
                quantity = qty_match.group(1)
                continue

            # Price with ₹
            price_match = re.search(r"₹\s*([\d,]+(?:\.\d+)?)", line)
            if price_match:
                val = float(price_match.group(1).replace(",", ""))
                if price == 0:
                    price = val
                elif mrp == 0:
                    mrp = val
                continue

            # Name: longest non-price, non-quantity line
            if len(line) > len(name) and not re.match(r"^[₹\d,.\s]+$", line):
                name = line

        if mrp == 0.0:
            mrp = price

        # Try brand extraction from name (first word often is brand)
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
            PLATFORMS["blinkit"]["orders_url"], wait_until="domcontentloaded"
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
