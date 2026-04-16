import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

# ── Azure OpenAI ──────────────────────────────────────────────
AZURE_OPENAI_ENDPOINT = os.getenv("AZURE_OPENAI_ENDPOINT")
AZURE_OPENAI_DEPLOYMENT = os.getenv("AZURE_OPENAI_DEPLOYMENT", "gpt-4o")
AZURE_OPENAI_API_KEY = os.getenv("AZURE_OPENAI_API_KEY")
AZURE_OPENAI_API_VERSION = os.getenv("AZURE_OPENAI_API_VERSION", "2024-10-21")

# ── Paths ─────────────────────────────────────────────────────
DATA_DIR = Path(__file__).parent.parent / "data"
SESSION_DIR = DATA_DIR / "sessions"          # Playwright browser state
HISTORY_DIR = DATA_DIR / "order_history"     # Cached order history JSONs
HISTORY_DIR.mkdir(parents=True, exist_ok=True)
SESSION_DIR.mkdir(parents=True, exist_ok=True)

# ── Platform URLs ─────────────────────────────────────────────
PLATFORMS = {
    "swiggy": {
        "base_url": "https://www.swiggy.com/instamart",
        "search_url": "https://www.swiggy.com/instamart/search?query={query}",
        "orders_url": "https://www.swiggy.com/my-account/orders",
    },
    "blinkit": {
        "base_url": "https://blinkit.com",
        "search_url": "https://blinkit.com/s/?q={query}",
        "orders_url": "https://blinkit.com/orders",
    },
    "zepto": {
        "base_url": "https://www.zeptonow.com",
        "search_url": "https://www.zeptonow.com/search?query={query}",
        "orders_url": "https://www.zeptonow.com/account/orders",
    },
}

# ── Browser settings ──────────────────────────────────────────
HEADLESS = os.getenv("HEADLESS", "false").lower() == "true"
SLOW_MO = int(os.getenv("SLOW_MO", "100"))          # ms between actions
SEARCH_TIMEOUT = int(os.getenv("SEARCH_TIMEOUT", "15000"))  # ms
