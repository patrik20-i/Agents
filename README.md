# 🛒 Grocery Price Comparison Agent

Compares prices across **Swiggy Instamart**, **Blinkit**, and **Zepto** for your grocery list — powered by browser automation and GPT-4o.

## How it works

1. You enter a free-form grocery list  
2. The agent parses it into structured items using GPT-4o  
3. If you didn't specify brand/size, it checks your **order history** on each platform to pick your usual preference  
4. It searches all three platforms in parallel using Playwright  
5. GPT-4o picks the best match per item per platform  
6. You get a comparison table with per-item prices and totals  

## Setup

```bash
# Install Python dependencies
pip install -r requirements.txt

# Install Playwright browsers (Chromium)
playwright install chromium
```

## Configuration

All config is in `.env` (already set up):

```env
AZURE_OPENAI_ENDPOINT=https://...
AZURE_OPENAI_DEPLOYMENT=gpt-4o
AZURE_OPENAI_API_KEY=...
AZURE_OPENAI_API_VERSION=2024-10-21

# Optional
HEADLESS=false        # Set to true for headless browser
SLOW_MO=100           # Milliseconds between browser actions
SEARCH_TIMEOUT=15000  # Search result wait timeout (ms)
```

## Usage

```bash
python -m grocery_agent
```

The agent will:
1. Ask you to type your grocery list
2. On first run, open a browser for you to **log in** to each platform (session saved for future runs)
3. Search all items and show the comparison

### Example input

```
tomatoes 1 kg
Amul toned milk 500 ml
onions
Aashirvaad atta 5 kg
eggs
curd
```

### Example output

```
┌──────────────────┬────────────────────┬────────────────────┬────────────────────┐
│ Item             │ Swiggy Instamart   │ Blinkit            │ Zepto              │
├──────────────────┼────────────────────┼────────────────────┼────────────────────┤
│ Tomatoes 1 kg    │ ₹40                │ ₹38                │ ₹42                │
│ Amul Milk 500ml  │ ₹31                │ ₹31                │ ₹31                │
│ Onions 1 kg      │ ₹35                │ ₹32                │ ₹30                │
│ Aashirvaad 5kg   │ ₹285               │ ₹279               │ ₹289               │
│ Eggs 6 pcs       │ ₹42                │ ₹40                │ ₹39                │
│ Curd 400 g       │ ₹35                │ ₹35                │ ₹37                │
├──────────────────┼────────────────────┼────────────────────┼────────────────────┤
│ TOTAL            │ ₹468               │ ₹455  ← cheapest   │ ₹468               │
└──────────────────┴────────────────────┴────────────────────┴────────────────────┘
```

## Project structure

```
grocery_agent/
├── __init__.py
├── __main__.py          # python -m grocery_agent entry point
├── main.py              # CLI flow
├── agent.py             # LLM orchestration (parse, match, format)
├── config.py            # Settings from .env
├── platforms/
│   ├── __init__.py
│   ├── base.py          # Abstract scraper + data models
│   ├── swiggy.py        # Swiggy Instamart scraper
│   ├── blinkit.py       # Blinkit scraper
│   └── zepto.py         # Zepto scraper
└── history/
    └── __init__.py      # Order history preference analyzer
data/
├── sessions/            # Saved browser login sessions
└── order_history/       # Cached order history JSONs
```

## Notes

- **First run** requires manual login to each platform via the browser popup. Sessions are saved in `data/sessions/` and reused.
- **Order history** is fetched once and cached in `data/order_history/`. The preference analyzer uses it to pick brands/sizes you usually buy.
- The scrapers use CSS selectors that may break if platforms update their UI. If a platform stops working, the selectors in its scraper file need updating.
- Set `HEADLESS=true` in `.env` for faster, background operation (after login sessions are saved).
