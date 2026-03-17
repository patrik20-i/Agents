"""Basic utility tools.

Tools included:
- weather_check: fetch current weather for a city via wttr.in
- search_google: build and optionally open a Google search URL
- current_time: return local or UTC time
"""

from __future__ import annotations

from datetime import datetime, timezone
from urllib.parse import quote_plus
from urllib.request import urlopen
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


def search_google(query: str, open_in_browser: bool = False) -> str:
    """Return a Google search URL for the query.

    Set open_in_browser=True to launch the search in a browser.
    """
    query = query.strip()
    if not query:
        return "Please provide a search query."

    url = f"https://www.google.com/search?q={quote_plus(query)}"
    if open_in_browser:
        webbrowser.open(url)
    return url


def current_time(use_utc: bool = False) -> str:
    """Return the current time as an ISO 8601 string."""
    now = datetime.now(timezone.utc) if use_utc else datetime.now()
    return now.isoformat(timespec="seconds")


if __name__ == "__main__":
    # Quick demo output
    print("Weather:", weather_check("Bangalore"))
    print("Google URL:", search_google("python tools"))
    print("Local Time:", current_time())
