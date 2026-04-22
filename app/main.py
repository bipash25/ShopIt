from __future__ import annotations

import asyncio
from enum import Enum
from typing import Annotated

from fastapi import FastAPI, Query, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from app.cache import cache
from app.models import SearchResponse
from app.scrapers import amazon, flipkart

MAX_ALL_PAGES = 20
ALL_PAGES_DELAY = 1.0

app = FastAPI(
    title="ShopIt API",
    description=(
        "## Live product search API for Amazon India & Flipkart\n\n"
        "Scrapes real-time product data including prices, ratings, images, "
        "specs, and available filters. Supports search, filtering, sorting, "
        "pagination, and **automatic full-catalog fetching** (`all_pages=true`).\n\n"
        "### Key features\n"
        "- **Unified search** across both sites in parallel\n"
        "- **Per-site endpoints** for advanced, source-specific filtering\n"
        "- **Auto-pagination** — fetch every page of results in one call\n"
        "- **In-memory TTL cache** (5 min) to avoid redundant requests\n"
        "- **Dynamic filters** — each response includes available filters "
        "for the current query, ready to pass back as params\n\n"
        "### Rate limiting\n"
        "Both Amazon and Flipkart have anti-bot protections. "
        "This API adds a 1-second delay between pages during `all_pages` fetching. "
        "Avoid hammering the endpoints with many concurrent requests.\n"
    ),
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


class Source(str, Enum):
    amazon = "amazon"
    flipkart = "flipkart"
    all = "all"


def _has_filters(**kwargs) -> bool:
    return any(v is not None for v in kwargs.values())


def _cache_key(source: str, **kwargs) -> tuple[str, ...]:
    parts = [source]
    for k in sorted(kwargs):
        v = kwargs[k]
        if v is not None:
            parts.append(f"{k}={v}")
    return tuple(parts)


async def _fetch_all_pages_amazon(
    q: str, sort: str | None,
    min_price: int | None, max_price: int | None,
    brand: str | None, rh: str | None,
) -> SearchResponse:
    first = await amazon.search(
        q, page=1, sort=sort,
        min_price=min_price, max_price=max_price,
        brand=brand, rh=rh,
    )
    all_products = list(first.products)
    pages_fetched = 1
    current_page = 1

    while first.has_next_page if pages_fetched == 1 else result.has_next_page:
        if pages_fetched >= MAX_ALL_PAGES:
            break
        current_page += 1
        await asyncio.sleep(ALL_PAGES_DELAY)
        result = await amazon.search(
            q, page=current_page, sort=sort,
            min_price=min_price, max_price=max_price,
            brand=brand, rh=rh,
        )
        all_products.extend(result.products)
        pages_fetched += 1
        if not result.has_next_page:
            break

    first.products = all_products
    first.total_pages_fetched = pages_fetched
    first.has_next_page = False
    return first


async def _fetch_all_pages_flipkart(
    q: str, sort: str | None,
    min_price: int | None, max_price: int | None,
    brand: str | None,
) -> SearchResponse:
    first = await flipkart.search(
        q, page=1, sort=sort,
        min_price=min_price, max_price=max_price,
        brand=brand,
    )
    all_products = list(first.products)
    pages_fetched = 1
    current_page = 1

    while first.has_next_page if pages_fetched == 1 else result.has_next_page:
        if pages_fetched >= MAX_ALL_PAGES:
            break
        current_page += 1
        await asyncio.sleep(ALL_PAGES_DELAY)
        result = await flipkart.search(
            q, page=current_page, sort=sort,
            min_price=min_price, max_price=max_price,
            brand=brand,
        )
        all_products.extend(result.products)
        pages_fetched += 1
        if not result.has_next_page:
            break

    first.products = all_products
    first.total_pages_fetched = pages_fetched
    first.has_next_page = False
    return first


@app.get(
    "/api/search",
    response_model=list[SearchResponse],
    summary="Unified search across Amazon & Flipkart",
    tags=["Search"],
)
async def search(
    q: Annotated[str, Query(min_length=1, description="Search query (e.g. 'iPhone 15', 'laptop', 'headphones')")],
    source: Annotated[Source, Query(description="Which site(s) to search — `all` queries both in parallel")] = Source.all,
    page: Annotated[int, Query(ge=1, le=50, description="Page number (ignored when `all_pages=true`)")] = 1,
    all_pages: Annotated[bool, Query(description="Fetch ALL pages and return the full product list (max 20 pages). Requires at least one filter applied.")] = False,
    sort: Annotated[str | None, Query(description="Sort order — Amazon: `price-asc-rank`, `price-desc-rank`, `review-rank`, `date-desc-rank` | Flipkart: `price_asc`, `price_desc`, `popularity`, `recency_desc`")] = None,
    min_price: Annotated[int | None, Query(ge=0, description="Minimum price filter in INR")] = None,
    max_price: Annotated[int | None, Query(ge=0, description="Maximum price filter in INR")] = None,
    brand: Annotated[str | None, Query(description="Brand name filter (e.g. 'Apple', 'Samsung')")] = None,
):
    """
    Search products across Amazon India and Flipkart simultaneously.

    When `source=all`, both sites are queried in parallel and results are returned
    as a list with one entry per source.

    Set `all_pages=true` to automatically paginate through every available page
    and return the complete product list in a single response. This is rate-limited
    to 1 request/second per source and capped at 20 pages max.

    **Note:** `all_pages` requires at least one filter (`min_price`, `max_price`, `brand`, or `sort`)
    to prevent excessively large unfiltered fetches.
    """
    if all_pages and not _has_filters(sort=sort, min_price=min_price, max_price=max_price, brand=brand):
        raise HTTPException(
            400,
            "all_pages requires at least one filter (sort, min_price, max_price, or brand) "
            "to avoid fetching an excessive number of pages.",
        )

    sources = (
        [Source.amazon, Source.flipkart]
        if source == Source.all
        else [source]
    )

    tasks = []
    for s in sources:
        if all_pages:
            ck = _cache_key(s.value, q=q, all_pages=True, sort=sort, min_price=min_price, max_price=max_price, brand=brand)
            cached_result = cache.get(*ck)
            if cached_result:
                cached_result.cached = True
                tasks.append(_wrap_cached(cached_result))
            elif s == Source.amazon:
                tasks.append(_fetch_all_cached(
                    _fetch_all_pages_amazon(q, sort, min_price, max_price, brand, None), ck
                ))
            else:
                tasks.append(_fetch_all_cached(
                    _fetch_all_pages_flipkart(q, sort, min_price, max_price, brand), ck
                ))
        else:
            ck = _cache_key(s.value, q=q, page=page, sort=sort, min_price=min_price, max_price=max_price, brand=brand)
            cached_result = cache.get(*ck)
            if cached_result:
                cached_result.cached = True
                tasks.append(_wrap_cached(cached_result))
            elif s == Source.amazon:
                tasks.append(_search_amazon(q, page, sort, min_price, max_price, brand, ck))
            else:
                tasks.append(_search_flipkart(q, page, sort, min_price, max_price, brand, ck))

    results = await asyncio.gather(*tasks, return_exceptions=True)

    responses = []
    for r in results:
        if isinstance(r, Exception):
            continue
        responses.append(r)

    if not responses:
        raise HTTPException(502, "All sources failed. Try again later.")

    return responses


async def _wrap_cached(data: SearchResponse) -> SearchResponse:
    return data


async def _fetch_all_cached(coro, ck: tuple[str, ...]) -> SearchResponse:
    result = await coro
    cache.set(result, *ck)
    return result


async def _search_amazon(
    q: str, page: int, sort: str | None,
    min_price: int | None, max_price: int | None,
    brand: str | None, ck: tuple[str, ...],
) -> SearchResponse:
    result = await amazon.search(
        q, page=page, sort=sort,
        min_price=min_price, max_price=max_price, brand=brand,
    )
    cache.set(result, *ck)
    return result


async def _search_flipkart(
    q: str, page: int, sort: str | None,
    min_price: int | None, max_price: int | None,
    brand: str | None, ck: tuple[str, ...],
) -> SearchResponse:
    result = await flipkart.search(
        q, page=page, sort=sort,
        min_price=min_price, max_price=max_price, brand=brand,
    )
    cache.set(result, *ck)
    return result


@app.get(
    "/api/search/amazon",
    response_model=SearchResponse,
    summary="Search Amazon India",
    tags=["Amazon"],
)
async def search_amazon(
    q: Annotated[str, Query(min_length=1, description="Search query")],
    page: Annotated[int, Query(ge=1, le=50, description="Page number (ignored when `all_pages=true`)")] = 1,
    all_pages: Annotated[bool, Query(description="Fetch ALL pages and return complete product list (max 20 pages). Requires at least one filter applied.")] = False,
    sort: Annotated[str | None, Query(description="Sort: `price-asc-rank` | `price-desc-rank` | `review-rank` | `date-desc-rank`")] = None,
    min_price: Annotated[int | None, Query(ge=0, description="Min price in INR")] = None,
    max_price: Annotated[int | None, Query(ge=0, description="Max price in INR")] = None,
    brand: Annotated[str | None, Query(description="Brand name (e.g. 'Apple')")] = None,
    rh: Annotated[str | None, Query(description="Raw Amazon `rh` filter parameter — pass the `value` field from any filter option directly")] = None,
):
    """
    Search Amazon India with full filter support.

    **Filters:** Use `brand`, `min_price`, `max_price` for common filters, or pass the
    raw `rh` parameter from the `filters[].options[].value` field in any response for
    advanced filtering (e.g. RAM, storage, customer reviews).

    **Sort options:** `price-asc-rank`, `price-desc-rank`, `review-rank`, `date-desc-rank`

    **All pages:** Set `all_pages=true` to auto-paginate through every page (max 20).
    Requires at least one filter to be applied.
    """
    if all_pages and not _has_filters(sort=sort, min_price=min_price, max_price=max_price, brand=brand, rh=rh):
        raise HTTPException(
            400,
            "all_pages requires at least one filter (sort, min_price, max_price, brand, or rh) "
            "to avoid fetching an excessive number of pages.",
        )

    if all_pages:
        ck = _cache_key("amazon", q=q, all_pages=True, sort=sort, min_price=min_price, max_price=max_price, brand=brand, rh=rh)
        cached_result = cache.get(*ck)
        if cached_result:
            cached_result.cached = True
            return cached_result
        result = await _fetch_all_pages_amazon(q, sort, min_price, max_price, brand, rh)
        cache.set(result, *ck)
        return result

    ck = _cache_key("amazon", q=q, page=page, sort=sort, min_price=min_price, max_price=max_price, brand=brand, rh=rh)
    cached_result = cache.get(*ck)
    if cached_result:
        cached_result.cached = True
        return cached_result

    result = await amazon.search(
        q, page=page, sort=sort,
        min_price=min_price, max_price=max_price,
        brand=brand, rh=rh,
    )
    cache.set(result, *ck)
    return result


@app.get(
    "/api/search/flipkart",
    response_model=SearchResponse,
    summary="Search Flipkart",
    tags=["Flipkart"],
)
async def search_flipkart(
    q: Annotated[str, Query(min_length=1, description="Search query")],
    page: Annotated[int, Query(ge=1, le=50, description="Page number (ignored when `all_pages=true`)")] = 1,
    all_pages: Annotated[bool, Query(description="Fetch ALL pages and return complete product list (max 20 pages). Requires at least one filter applied.")] = False,
    sort: Annotated[str | None, Query(description="Sort: `price_asc` | `price_desc` | `popularity` | `recency_desc` | `rating_desc`")] = None,
    min_price: Annotated[int | None, Query(ge=0, description="Min price in INR")] = None,
    max_price: Annotated[int | None, Query(ge=0, description="Max price in INR")] = None,
    brand: Annotated[str | None, Query(description="Brand name (e.g. 'Samsung'). Comma-separated for multiple.")] = None,
):
    """
    Search Flipkart with full filter support.

    **Filters:** Use `brand`, `min_price`, `max_price` for common filters.

    **Sort options:** `price_asc`, `price_desc`, `popularity`, `recency_desc`, `rating_desc`

    **All pages:** Set `all_pages=true` to auto-paginate through every page (max 20).
    Requires at least one filter to be applied.
    """
    if all_pages and not _has_filters(sort=sort, min_price=min_price, max_price=max_price, brand=brand):
        raise HTTPException(
            400,
            "all_pages requires at least one filter (sort, min_price, max_price, or brand) "
            "to avoid fetching an excessive number of pages.",
        )

    if all_pages:
        ck = _cache_key("flipkart", q=q, all_pages=True, sort=sort, min_price=min_price, max_price=max_price, brand=brand)
        cached_result = cache.get(*ck)
        if cached_result:
            cached_result.cached = True
            return cached_result
        result = await _fetch_all_pages_flipkart(q, sort, min_price, max_price, brand)
        cache.set(result, *ck)
        return result

    ck = _cache_key("flipkart", q=q, page=page, sort=sort, min_price=min_price, max_price=max_price, brand=brand)
    cached_result = cache.get(*ck)
    if cached_result:
        cached_result.cached = True
        return cached_result

    result = await flipkart.search(
        q, page=page, sort=sort,
        min_price=min_price, max_price=max_price,
        brand=brand,
    )
    cache.set(result, *ck)
    return result


@app.delete(
    "/api/cache",
    summary="Clear response cache",
    tags=["Utility"],
)
async def clear_cache():
    """Purge all cached search responses. The next request for any query will hit the source site live."""
    cache.clear()
    return {"status": "ok", "message": "Cache cleared"}


@app.get(
    "/health",
    summary="Health check",
    tags=["Utility"],
)
async def health():
    """Returns `{\"status\": \"ok\"}` if the API is running."""
    return {"status": "ok"}
