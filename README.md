# ShopIt API

A high-performance, real-time product search API that scrapes live data from **Amazon India** and **Flipkart**. Built with FastAPI and async Python, it provides a unified interface to search, filter, sort, and paginate products across both e-commerce platforms simultaneously.

## Features

- **Unified Search** — Query Amazon and Flipkart in parallel with a single API call
- **Per-Site Endpoints** — Dedicated endpoints for source-specific advanced filtering
- **Auto-Pagination** — Fetch every page of results in one call with `all_pages=true` (up to 20 pages per source)
- **Dynamic Filters** — Each response includes all available filters for the current query, ready to pass back as parameters
- **Sort Support** — Sort by price, popularity, ratings, recency, and more
- **Price Range Filtering** — Filter results by `min_price` and `max_price` (in INR)
- **Brand Filtering** — Filter by brand name
- **In-Memory TTL Cache** — Responses are cached for 5 minutes to reduce redundant requests and avoid rate-limiting
- **Interactive API Docs** — Auto-generated Swagger UI at `/docs` and ReDoc at `/redoc`
- **Docker Ready** — Dockerfile and docker-compose included

## How It Works

| Source | Method | Data Format |
|---|---|---|
| **Amazon India** | HTTP GET to `/s?k=...` with browser-like headers | HTML → parsed with BeautifulSoup |
| **Flipkart** | POST to internal JSON API (`1.rome.api.flipkart.com`) | Structured JSON — no HTML parsing needed |

Neither source requires cookies, login, or API keys. Both are reverse-engineered from the sites' public-facing search interfaces.

## Quick Start

### Local

```bash
git clone https://github.com/bipash25/ShopIt.git
cd ShopIt

pip install -r requirements.txt

uvicorn app.main:app --host 0.0.0.0 --port 8000
```

### Docker

```bash
docker compose up --build
```

The API will be available at `http://localhost:8000`. Open `http://localhost:8000/docs` for the interactive Swagger UI.

## API Endpoints

### `GET /api/search` — Unified Search

Search both Amazon and Flipkart in parallel.

| Parameter | Type | Default | Description |
|---|---|---|---|
| `q` | string | *required* | Search query (e.g. `iPhone 15`, `laptop`) |
| `source` | string | `all` | Which site(s): `amazon`, `flipkart`, or `all` |
| `page` | int | `1` | Page number (1–50) |
| `all_pages` | bool | `false` | Fetch ALL pages automatically (max 20 pages, ~1s delay between). **Requires at least one filter.** |
| `sort` | string | `null` | Sort order (see sort values below) |
| `min_price` | int | `null` | Minimum price in INR |
| `max_price` | int | `null` | Maximum price in INR |
| `brand` | string | `null` | Brand name filter |

**Example:**

```bash
# Search both sites for laptops under ₹50,000
curl "http://localhost:8000/api/search?q=laptop&max_price=50000&source=all"

# Get ALL Samsung earbuds from Flipkart in one shot
curl "http://localhost:8000/api/search?q=earbuds&source=flipkart&brand=Samsung&all_pages=true"
```

### `GET /api/search/amazon` — Amazon India

All parameters from the unified endpoint, plus:

| Parameter | Type | Description |
|---|---|---|
| `rh` | string | Raw Amazon filter parameter — pass the `value` field from any filter option in the response |

**Amazon Sort Values:**

| Value | Description |
|---|---|
| `price-asc-rank` | Price: Low to High |
| `price-desc-rank` | Price: High to Low |
| `review-rank` | Avg. Customer Reviews |
| `date-desc-rank` | Newest Arrivals |

**Example:**

```bash
# Search Amazon for smartphones sorted by price
curl "http://localhost:8000/api/search/amazon?q=smartphone&sort=price-asc-rank&brand=Samsung"

# Use a raw filter value from a previous response (e.g. storage capacity)
curl "http://localhost:8000/api/search/amazon?q=iPhone+15&rh=p_123%3A110955"
```

### `GET /api/search/flipkart` — Flipkart

All parameters from the unified endpoint.

**Flipkart Sort Values:**

| Value | Description |
|---|---|
| `price_asc` | Price: Low to High |
| `price_desc` | Price: High to Low |
| `popularity` | Popularity |
| `recency_desc` | Newest First |
| `rating_desc` | Customer Rating |

**Example:**

```bash
# Flipkart laptops, ₹30k–50k, sorted by price
curl "http://localhost:8000/api/search/flipkart?q=laptop&min_price=30000&max_price=50000&sort=price_asc"

# Fetch ALL pages of boAt earbuds
curl "http://localhost:8000/api/search/flipkart?q=wireless+earbuds&brand=boAt&all_pages=true"
```

### `DELETE /api/cache` — Clear Cache

Purge all cached responses. Next request will hit the source site live.

```bash
curl -X DELETE "http://localhost:8000/api/cache"
```

### `GET /health` — Health Check

```bash
curl "http://localhost:8000/health"
# {"status": "ok"}
```

## Response Schema

Every search response follows this structure:

```json
{
  "query": "iPhone 15",
  "source": "flipkart",
  "page": 1,
  "total_results": 679,
  "total_pages_fetched": 1,
  "has_next_page": true,
  "cached": false,
  "products": [
    {
      "source": "flipkart",
      "id": "MOBGTAGPTB3VS24W",
      "title": "Apple iPhone 15 (Black, 128 GB)",
      "url": "https://www.flipkart.com/...",
      "image": "https://rukminim1.flixcart.com/image/416/416/...",
      "price": 59900,
      "original_price": 69900,
      "currency": "INR",
      "rating": 4.6,
      "rating_count": 274062,
      "brand": "Apple",
      "specs": [
        "128 GB ROM",
        "15.49 cm (6.1 inch) Super Retina XDR Display",
        "48MP + 12MP | 12MP Front Camera",
        "A16 Bionic Chip, 6 Core Processor Processor"
      ],
      "sponsored": false
    }
  ],
  "filters": [
    {
      "name": "Brand",
      "key": "brand",
      "options": [
        { "label": "Apple", "value": "facets.brand%5B%5D=Apple", "count": 592 },
        { "label": "Samsung", "value": "facets.brand%5B%5D=Samsung", "count": 21 }
      ]
    }
  ],
  "sort_options": [
    { "label": "Relevance", "value": "relevance" },
    { "label": "Price -- Low to High", "value": "price_asc" }
  ]
}
```

### Product Fields

| Field | Type | Availability | Description |
|---|---|---|---|
| `source` | string | Both | `amazon` or `flipkart` |
| `id` | string | Both | Product ID (ASIN for Amazon) |
| `title` | string | Both | Full product title |
| `url` | string | Both | Direct product page link |
| `image` | string | Both | Thumbnail image URL |
| `price` | int | Both | Current price in whole INR |
| `original_price` | int | Both | MRP / list price before discount |
| `currency` | string | Both | Always `INR` |
| `rating` | float | Both | Average rating (out of 5) |
| `rating_count` | int | Both | Number of ratings |
| `brand` | string | Flipkart (reliable) | Brand name |
| `specs` | string[] | Flipkart only | Key specs (RAM, camera, display, etc.) |
| `sponsored` | bool | Amazon | Whether the listing is sponsored |

## Using Dynamic Filters

Every search response includes a `filters` array with all available filter options for that query. To apply a filter:

1. Make an initial search request
2. Look at the `filters` array in the response
3. Pick a filter option's `value`
4. Pass it back:
   - **Amazon**: as the `rh` query parameter
   - **Flipkart**: price/brand filters use dedicated params; other facets use the `value` field

```bash
# Step 1: Search
curl "http://localhost:8000/api/search/amazon?q=smartphone"

# Step 2: Response includes filters like:
#   { "name": "Brands", "options": [{ "label": "Samsung", "value": "p_123%3A46655" }] }

# Step 3: Apply the filter
curl "http://localhost:8000/api/search/amazon?q=smartphone&rh=p_123%3A46655"
```

## `all_pages` — Full Catalog Fetch

Set `all_pages=true` on any endpoint to automatically loop through every available page and return all products in a single response.

- **Requires at least one filter** — `all_pages` is rejected (HTTP 400) on plain, unfiltered searches to prevent fetching dozens of pages. Apply any combination of `sort`, `min_price`, `max_price`, `brand`, or `rh` (Amazon) first.
- **Max 20 pages** per request (safety cap)
- **1-second delay** between page requests (rate-limit protection)
- The `total_pages_fetched` field shows how many pages were retrieved
- `has_next_page` is always `false` in the response (all fetched)
- Results are **cached** — subsequent identical requests are instant

```bash
# Get every boAt earbud listing on Flipkart
curl "http://localhost:8000/api/search/flipkart?q=earbuds&brand=boAt&all_pages=true"
# → 800 products across 20 pages in one response
```

## Project Structure

```
ShopIt/
├── app/
│   ├── __init__.py
│   ├── main.py              # FastAPI app — endpoints, routing, caching
│   ├── models.py             # Pydantic schemas (Product, SearchResponse, etc.)
│   ├── cache.py              # In-memory TTL cache
│   └── scrapers/
│       ├── __init__.py
│       ├── amazon.py         # Amazon India scraper (HTML → BeautifulSoup)
│       └── flipkart.py       # Flipkart scraper (internal JSON API)
├── Dockerfile
├── docker-compose.yml
├── requirements.txt
├── .env.example
└── README.md
```

## Limitations & Notes

- **No API keys required** — both scrapers work without authentication
- **Anti-bot protections** — both sites have bot detection. The default headers mimic a real Chrome browser on Windows. Excessive requests may trigger CAPTCHAs or temporary blocks
- **Rotating proxies** — not included but easy to add via `httpx` proxy configuration if you get rate-limited
- **Data accuracy** — prices and availability are scraped in real-time but may differ slightly from what you see in a browser (due to personalization, location, login status)
- **Flipkart's API** may change its endpoint or response format without notice — the scraper would need updating
- **Amazon's HTML** structure may change — the BeautifulSoup selectors would need updating

## Tech Stack

- **[FastAPI](https://fastapi.tiangolo.com/)** — async web framework with auto-generated OpenAPI docs
- **[httpx](https://www.python-httpx.org/)** — async HTTP client
- **[BeautifulSoup4](https://www.crummy.com/software/BeautifulSoup/)** + **lxml** — HTML parsing (Amazon)
- **[Pydantic](https://docs.pydantic.dev/)** — data validation and serialization
- **[Docker](https://www.docker.com/)** — containerized deployment
