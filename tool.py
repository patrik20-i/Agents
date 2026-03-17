"""Basic utility tools.

Tools included:
- weather_check: fetch current weather for a city via wttr.in
- search_google: fetch top web results and summarize top 5 pages
- current_time: return local or UTC time
"""

from __future__ import annotations

from datetime import datetime, timezone
import re
from html import unescape
from urllib.parse import parse_qs, quote_plus, urlparse
from urllib.request import Request, urlopen
import webbrowser


def weather_check(city: str) -> str:
    """Return a simple weather summary for the given city.

    Uses wttr.in's plain text one-line response.
    """
    city = city.strip()
    if not city:
        return "Please provide a city name."

    url = f"https://wttr.in/{quote_plus(city)}?format=3"
    try:
        with urlopen(url, timeout=8) as response:  # nosec B310
            return response.read().decode("utf-8").strip()
    except Exception as exc:
        return f"Could not fetch weather for '{city}': {exc}"


def _clean_text(html: str) -> str:
    html = re.sub(r"<script[\\s\\S]*?</script>", " ", html, flags=re.IGNORECASE)
    html = re.sub(r"<style[\\s\\S]*?</style>", " ", html, flags=re.IGNORECASE)
    html = re.sub(r"<[^>]+>", " ", html)
    return " ".join(unescape(html).split())


def _extract_google_result_links(search_html: str, max_links: int = 5) -> list[str]:
    links: list[str] = []
    seen: set[str] = set()
    for href in re.findall(r'href="([^"]+)"', search_html):
        if not href.startswith("/url?"):
            continue
        parsed = urlparse(href)
        qs = parse_qs(parsed.query)
        raw_link = qs.get("q", [""])[0]
        if not raw_link.startswith("http"):
            continue
        if "google." in urlparse(raw_link).netloc:
            continue
        if raw_link in seen:
            continue
        seen.add(raw_link)
        links.append(raw_link)
        if len(links) >= max_links:
            break
    return links


def _extract_duckduckgo_result_links(search_html: str, max_links: int = 5) -> list[str]:
    links: list[str] = []
    seen: set[str] = set()
    for href in re.findall(r'href="([^"]+)"', search_html):
        if "duckduckgo.com/l/?" in href and "uddg=" in href:
            qs = parse_qs(urlparse(href).query)
            raw_link = qs.get("uddg", [""])[0]
        elif href.startswith("http"):
            raw_link = href
        else:
            continue

        if not raw_link.startswith("http"):
            continue
        if "duckduckgo.com" in urlparse(raw_link).netloc:
            continue
        if raw_link in seen:
            continue

        seen.add(raw_link)
        links.append(raw_link)
        if len(links) >= max_links:
            break
    return links


def _extract_title(html: str) -> str:
    match = re.search(r"<title>([\\s\\S]*?)</title>", html, flags=re.IGNORECASE)
    if not match:
        return "Untitled"
    return " ".join(unescape(match.group(1)).split())


def search_google(query: str, open_in_browser: bool = False) -> str:
    """Search Google, read top 5 result pages, and return a concise synthesis."""
    query = query.strip()
    if not query:
        return "Please provide a search query."

    search_url = f"https://www.google.com/search?q={quote_plus(query)}&num=10&hl=en"
    if open_in_browser:
        webbrowser.open(search_url)

    headers = {
        "User-Agent": (
            "Mozilla/5.0 (X11; Linux x86_64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        )
    }

    try:
        req = Request(search_url, headers=headers)
        with urlopen(req, timeout=12) as response:  # nosec B310
            search_html = response.read().decode("utf-8", errors="ignore")
    except Exception as exc:
        return f"Could not fetch Google search results: {exc}"

    top_links = _extract_google_result_links(search_html, max_links=5)
    if not top_links:
        # Fallback for JS-heavy Google pages where links are not present server-side.
        ddg_url = f"https://duckduckgo.com/html/?q={quote_plus(query)}"
        try:
            ddg_req = Request(ddg_url, headers=headers)
            with urlopen(ddg_req, timeout=12) as response:  # nosec B310
                ddg_html = response.read().decode("utf-8", errors="ignore")
            top_links = _extract_duckduckgo_result_links(ddg_html, max_links=5)
        except Exception:
            top_links = []

    if not top_links:
        return "Could not extract result links from search providers."

    summaries: list[str] = []
    for idx, link in enumerate(top_links, start=1):
        try:
            page_req = Request(link, headers=headers)
            with urlopen(page_req, timeout=10) as response:  # nosec B310
                page_html = response.read().decode("utf-8", errors="ignore")

            title = _extract_title(page_html)
            text = _clean_text(page_html)
            snippet = text[:280].strip() if text else "No readable content extracted."
            summaries.append(f"{idx}. {title}\n{snippet}\nSource: {link}")
        except Exception as exc:
            summaries.append(f"{idx}. Failed to read source: {link}\nReason: {exc}")

    return "\n\n".join(summaries)


def current_time(use_utc: bool = False) -> str:
    """Return the current time as an ISO 8601 string."""
    now = datetime.now(timezone.utc) if use_utc else datetime.now()
    return now.isoformat(timespec="seconds")


if __name__ == "__main__":
    # Quick demo output
    print("Weather:", weather_check("Bangalore"))
    print("Google URL:", search_google("python tools"))
    print("Local Time:", current_time())
