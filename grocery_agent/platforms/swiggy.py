"""Swiggy Instamart scraper using Playwright."""
from __future__ import annotations

import re
from grocery_agent.config import PLATFORMS, SEARCH_TIMEOUT
from grocery_agent.platforms.base import (
    BaseScraper,
    ProductResult,
    OrderHistoryItem,
)


class SwiggyInstamartScraper(BaseScraper):
    PLATFORM_NAME = "swiggy"

    def _login_url(self) -> str:
        return PLATFORMS["swiggy"]["base_url"]

    # ── search ────────────────────────────────────────────────
    async def _search_items(self, query: str) -> list[ProductResult]:
        page = self._page
        url = PLATFORMS["swiggy"]["search_url"].format(query=query)
        await page.goto(url, wait_until="domcontentloaded")

        # Wait for product cards to render
        try:
            await page.wait_for_selector(
                '[data-testid="ItemWidgetContainer"], '
                '.sc-aXZVg, '                        # common Swiggy card class
                'div[class*="ProductCard"], '
                'div[class*="product-card"], '
                'a[href*="/instamart/item/"]',
                timeout=SEARCH_TIMEOUT,
            )
        except Exception:
            # Fallback: wait a bit and try to scrape whatever loaded
            await page.wait_for_timeout(3000)

        products: list[ProductResult] = []

        # Strategy 1: structured data-testid cards
        cards = await page.query_selector_all(
            '[data-testid="ItemWidgetContainer"], '
            'div[class*="ProductCard"], '
            'a[href*="/instamart/item/"]'
        )

        if not cards:
            # Strategy 2: any card-like container with a price
            cards = await page.query_selector_all(
                'div[class*="product"], div[class*="Product"], '
                'div[class*="item-card"], div[class*="ItemCard"]'
            )

        for card in cards[:10]:  # cap at 10 results
            try:
                product = await self._parse_swiggy_card(card)
                if product:
                    products.append(product)
            except Exception:
                continue

        return products

    async def _parse_swiggy_card(self, card) -> ProductResult | None:
        text = (await card.inner_text()).strip()
        if not text:
            return None

        lines = [l.strip() for l in text.split("\n") if l.strip()]

        name = lines[0] if lines else "Unknown"
        brand = ""
        quantity = ""
        price = 0.0
        mrp = 0.0

        for line in lines:
            # Price detection: ₹123 or Rs 123
            price_match = re.search(r"₹\s*([\d,]+(?:\.\d+)?)", line)
            if price_match and price == 0.0:
                price = float(price_match.group(1).replace(",", ""))

            # MRP (strikethrough / original price)
            mrp_match = re.search(r"MRP\s*₹\s*([\d,]+(?:\.\d+)?)", line, re.I)
            if mrp_match:
                mrp = float(mrp_match.group(1).replace(",", ""))

            # Quantity: "500 g", "1 kg", "1 L", "6 pcs"
            qty_match = re.search(
                r"(\d+(?:\.\d+)?\s*(?:kg|g|ml|l|ltr|pc|pcs|pack|unit|no)s?)\b",
                line,
                re.I,
            )
            if qty_match and not quantity:
                quantity = qty_match.group(1)

        if mrp == 0.0:
            mrp = price

        # Try to extract image
        img_el = await card.query_selector("img")
        image_url = ""
        if img_el:
            image_url = await img_el.get_attribute("src") or ""

        return ProductResult(
            name=name,
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
            PLATFORMS["swiggy"]["orders_url"], wait_until="domcontentloaded"
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
            'div[class*="past-order"], a[href*="/order/"]'
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
