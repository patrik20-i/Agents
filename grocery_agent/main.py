#!/usr/bin/env python3
"""
Grocery Price Comparison Agent
──────────────────────────────
CLI entry point.  Run:  python -m grocery_agent
"""
from __future__ import annotations

import asyncio
import sys

from grocery_agent.platforms import (
    SwiggyInstamartScraper,
    BlinkitScraper,
    ZeptoScraper,
)
from grocery_agent.platforms.base import BaseScraper
from grocery_agent.history import PreferenceAnalyzer
from grocery_agent.agent import (
    parse_grocery_list,
    enrich_with_preferences,
    search_all_platforms,
    format_comparison,
)


PLATFORM_SCRAPERS: list[type[BaseScraper]] = [
    SwiggyInstamartScraper,
    BlinkitScraper,
    ZeptoScraper,
]


# ── Helpers ───────────────────────────────────────────────────
def _print_header():
    print()
    print("=" * 60)
    print("  🛒  Grocery Price Comparison Agent")
    print("  Compares Swiggy Instamart · Blinkit · Zepto")
    print("=" * 60)
    print()


async def _ensure_login(scraper: BaseScraper) -> None:
    """Check if the scraper has a saved session; prompt login if not."""
    if not await scraper.is_logged_in():
        print(f"  ⚠  No saved session for {scraper.PLATFORM_NAME}.")
        answer = input(f"     Log in to {scraper.PLATFORM_NAME}? [Y/n] ").strip()
        if answer.lower() != "n":
            await scraper.interactive_login()
        else:
            print(f"     Skipping {scraper.PLATFORM_NAME} (no login).\n")


async def _load_order_history(
    scrapers: list[BaseScraper], analyzer: PreferenceAnalyzer
) -> None:
    """Load order history from each platform for preference learning."""
    print("  📦  Loading order history for preference learning…")
    for scraper in scrapers:
        try:
            history = await scraper.get_order_history(limit=50)
            analyzer.add_history(history, scraper.PLATFORM_NAME)
            print(f"     {scraper.PLATFORM_NAME}: {len(history)} items")
        except Exception as e:
            print(f"     {scraper.PLATFORM_NAME}: skipped ({e})")
    analyzer.load_cached_history()
    print()


# ── Main flow ─────────────────────────────────────────────────
async def main() -> None:
    _print_header()

    # ── 1. Get grocery list from user ─────────────────────────
    print("Enter your grocery list (free-form, one item per line).")
    print("When done, press ENTER on an empty line:\n")

    lines: list[str] = []
    while True:
        try:
            line = input("  > ")
        except EOFError:
            break
        if not line.strip():
            break
        lines.append(line.strip())

    if not lines:
        print("No items entered. Goodbye!")
        return

    raw_list = "\n".join(lines)
    print(f"\n  📝  Received {len(lines)} item(s). Parsing…\n")

    # ── 2. Parse with LLM ────────────────────────────────────
    try:
        parsed_items = await parse_grocery_list(raw_list)
        print("  Parsed grocery list:")
        for i, item in enumerate(parsed_items, 1):
            brand = item.get("brand") or "any brand"
            qty = item.get("quantity") or "default size"
            notes = item.get("notes") or ""
            print(f"    {i}. {item['item']}  ({brand}, {qty}) {notes}")
        print()
    except Exception as e:
        print(f"  ❌  Failed to parse grocery list: {e}")
        return

    # ── 3. Launch scrapers & handle login ─────────────────────
    scrapers: list[BaseScraper] = []
    for ScraperClass in PLATFORM_SCRAPERS:
        scraper = ScraperClass()
        await scraper.launch()
        await _ensure_login(scraper)
        scrapers.append(scraper)

    if not scrapers:
        print("No platforms available. Exiting.")
        return

    # ── 4. Load order history & enrich preferences ────────────
    analyzer = PreferenceAnalyzer()
    await _load_order_history(scrapers, analyzer)
    enriched_items = enrich_with_preferences(parsed_items, analyzer)

    # Show enriched details
    any_enriched = any(
        item.get("brand_source") == "order_history"
        or item.get("quantity_source") == "order_history"
        for item in enriched_items
    )
    if any_enriched:
        print("  🧠  Preferences applied from your order history:")
        for item in enriched_items:
            extras = []
            if item.get("brand_source") == "order_history":
                extras.append(f"brand→{item['brand']}")
            if item.get("quantity_source") == "order_history":
                extras.append(f"size→{item['quantity']}")
            if extras:
                print(f"     {item['item']}: {', '.join(extras)}")
        print()

    # ── 5. Search across all platforms ────────────────────────
    total_searches = len(enriched_items) * len(scrapers)
    print(f"  🔍  Searching {len(enriched_items)} item(s) across "
          f"{len(scrapers)} platform(s) ({total_searches} searches)…\n")

    platform_results = await search_all_platforms(enriched_items, scrapers)

    # ── 6. Quick summary before LLM formatting ───────────────
    for pname, data in platform_results.items():
        available = sum(1 for i in data["items"] if i["available"])
        print(f"     {pname}: {available}/{len(data['items'])} items found, "
              f"subtotal ₹{data['total']:.0f}")
    print()

    # ── 7. Format final comparison with LLM ───────────────────
    print("  📊  Generating comparison…\n")
    comparison = await format_comparison(enriched_items, platform_results)
    print(comparison)
    print()

    # ── 8. Cleanup ────────────────────────────────────────────
    for scraper in scrapers:
        await scraper.close()


def run():
    """Sync entry point."""
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n\nInterrupted. Goodbye!")
        sys.exit(0)


if __name__ == "__main__":
    run()
