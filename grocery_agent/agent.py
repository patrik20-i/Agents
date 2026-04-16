"""
Core LLM agent that:
  1. Parses the user's grocery list (free-form text → structured items)
  2. Enriches each item with brand/size preferences from order history
  3. Orchestrates parallel searches across platforms
  4. Picks the best match per item per platform
  5. Builds the final comparison table
"""
from __future__ import annotations

import asyncio
import json
from dataclasses import asdict
from typing import Optional

from openai import AsyncAzureOpenAI

from grocery_agent.config import (
    AZURE_OPENAI_ENDPOINT,
    AZURE_OPENAI_API_KEY,
    AZURE_OPENAI_DEPLOYMENT,
    AZURE_OPENAI_API_VERSION,
)
from grocery_agent.platforms.base import BaseScraper, ProductResult, SearchResult
from grocery_agent.platforms import (
    SwiggyInstamartScraper,
    BlinkitScraper,
    ZeptoScraper,
)
from grocery_agent.history import PreferenceAnalyzer


# ── LLM helpers ───────────────────────────────────────────────
_client: Optional[AsyncAzureOpenAI] = None


def _get_client() -> AsyncAzureOpenAI:
    global _client
    if _client is None:
        _client = AsyncAzureOpenAI(
            azure_endpoint=AZURE_OPENAI_ENDPOINT,
            api_key=AZURE_OPENAI_API_KEY,
            api_version=AZURE_OPENAI_API_VERSION,
        )
    return _client


async def _chat(system: str, user: str) -> str:
    client = _get_client()
    resp = await client.chat.completions.create(
        model=AZURE_OPENAI_DEPLOYMENT,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        temperature=0.1,
    )
    return resp.choices[0].message.content or ""


# ── Step 1: Parse grocery list ────────────────────────────────
PARSE_SYSTEM = """\
You are a grocery-list parser. The user gives you a free-form grocery list.
Return a JSON array of objects, each with:
  - "item": the core item name (e.g. "milk", "onion")
  - "brand": brand if specified, else null
  - "quantity": size/quantity if specified (e.g. "1 kg", "500 ml"), else null
  - "notes": any extra detail (e.g. "organic", "low-fat"), else null
  - "search_query": a concise search string to use on a grocery app

Return ONLY valid JSON, no markdown fences."""


async def parse_grocery_list(raw_text: str) -> list[dict]:
    result = await _chat(PARSE_SYSTEM, raw_text)
    # Strip markdown fences if present
    result = result.strip()
    if result.startswith("```"):
        result = result.split("\n", 1)[1]
    if result.endswith("```"):
        result = result.rsplit("```", 1)[0]
    return json.loads(result.strip())


# ── Step 2: Enrich with preferences ──────────────────────────
def enrich_with_preferences(
    items: list[dict], analyzer: PreferenceAnalyzer
) -> list[dict]:
    """
    If the user didn't specify brand or quantity, fill from order history.
    """
    for item in items:
        prefs = analyzer.get_preferences(item["item"])
        if not item.get("brand") and prefs["brand"]:
            item["brand"] = prefs["brand"]
            item["brand_source"] = "order_history"
        if not item.get("quantity") and prefs["quantity"]:
            item["quantity"] = prefs["quantity"]
            item["quantity_source"] = "order_history"

        # Rebuild search query with enriched details
        parts = []
        if item.get("brand"):
            parts.append(item["brand"])
        parts.append(item["item"])
        if item.get("quantity"):
            parts.append(item["quantity"])
        if item.get("notes"):
            parts.append(item["notes"])
        item["search_query"] = " ".join(parts)

    return items


# ── Step 3: Pick best match using LLM ────────────────────────
MATCH_SYSTEM = """\
You are a product-matching assistant. Given a desired grocery item and a list
of search results from a platform, pick the SINGLE best matching product.
Consider: brand match, quantity match, price. If nothing matches at all,
return null.

Return ONLY a JSON object with keys: "index" (0-based index into the
products list) or null if no match. No markdown fences."""


async def pick_best_match(
    desired: dict, results: SearchResult
) -> Optional[ProductResult]:
    if not results.products:
        return None

    products_desc = json.dumps(
        [
            {
                "index": i,
                "name": p.name,
                "brand": p.brand,
                "price": p.price,
                "quantity": p.quantity,
            }
            for i, p in enumerate(results.products)
        ],
        indent=2,
    )

    user_msg = (
        f"Desired item: {json.dumps(desired)}\n\n"
        f"Available products on {results.platform}:\n{products_desc}"
    )

    raw = await _chat(MATCH_SYSTEM, user_msg)
    raw = raw.strip().strip("`").strip()
    if raw.startswith("json"):
        raw = raw[4:].strip()

    try:
        parsed = json.loads(raw)
        idx = parsed.get("index")
        if idx is not None and 0 <= idx < len(results.products):
            return results.products[idx]
    except Exception:
        pass

    # Fallback: cheapest available
    return results.best_match()


# ── Step 4: Orchestrate search across platforms ───────────────
async def search_item_on_platform(
    scraper: BaseScraper, item: dict
) -> tuple[str, dict, Optional[ProductResult], Optional[str]]:
    """Returns (platform_name, item, best_product, error)."""
    result = await scraper.search(item["search_query"])
    if result.error:
        return scraper.PLATFORM_NAME, item, None, result.error

    best = await pick_best_match(item, result)
    return scraper.PLATFORM_NAME, item, best, None


async def search_all_platforms(
    items: list[dict],
    scrapers: list[BaseScraper],
) -> dict:
    """
    Returns:
      {
        "swiggy":  {"items": [{item, product, error}, ...], "total": float},
        "blinkit": {"items": [{item, product, error}, ...], "total": float},
        "zepto":   {"items": [{item, product, error}, ...], "total": float},
      }
    """
    results = {s.PLATFORM_NAME: {"items": [], "total": 0.0} for s in scrapers}

    # Search each item on each platform (one item at a time per platform
    # to not overwhelm the sites, but all platforms in parallel)
    for item in items:
        tasks = [
            search_item_on_platform(scraper, item)
            for scraper in scrapers
        ]
        platform_results = await asyncio.gather(*tasks)

        for platform_name, itm, product, error in platform_results:
            entry = {
                "item": itm["item"],
                "search_query": itm["search_query"],
                "product": product.to_dict() if product else None,
                "error": error,
                "available": product is not None,
            }
            results[platform_name]["items"].append(entry)
            if product:
                results[platform_name]["total"] += product.price

    return results


# ── Step 5: Format comparison ─────────────────────────────────
FORMAT_SYSTEM = """\
You are a helpful grocery shopping assistant. Format the comparison results
into a clear, readable summary for the user.

Include:
- A table showing each item, availability, and price on each platform
- Total cost per platform
- A recommendation on which platform is cheapest overall
- Note any items that are unavailable on specific platforms

Use clean formatting with ₹ for prices. Be concise."""


async def format_comparison(
    items: list[dict], platform_results: dict
) -> str:
    user_msg = json.dumps(
        {
            "grocery_list": items,
            "platform_results": platform_results,
        },
        indent=2,
        default=str,
    )
    return await _chat(FORMAT_SYSTEM, user_msg)
