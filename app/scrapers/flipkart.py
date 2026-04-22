from __future__ import annotations

import json
import uuid
from urllib.parse import quote, urlencode

import httpx

from app.cache import cache
from app.models import (
    FilterGroup,
    FilterOption,
    Product,
    SearchResponse,
    SortOption,
)

_API_BASE = "https://1.rome.api.flipkart.com/api/4/page/fetch"

_HEADERS = {
    "content-type": "application/json",
    "user-agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/146.0.0.0 Safari/537.36"
    ),
    "x-user-agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/146.0.0.0 Safari/537.36 "
        "FKUA/website/42/website/Desktop"
    ),
    "origin": "https://www.flipkart.com",
    "referer": "https://www.flipkart.com/",
}

_SORT_MAP = {
    "relevance": "relevance",
    "popularity": "popularity",
    "price_asc": "price_asc",
    "price_desc": "price_desc",
    "recency_desc": "recency_desc",
    "rating_desc": "rating_desc",
}


def _build_page_uri(
    query: str,
    page: int = 1,
    sort: str | None = None,
    min_price: int | None = None,
    max_price: int | None = None,
    brand: str | None = None,
    filters: dict[str, list[str]] | None = None,
) -> str:
    params: dict[str, str] = {
        "q": query,
        "otracker": "search",
        "otracker1": "search",
        "marketplace": "FLIPKART",
        "as-show": "on",
        "as": "off",
    }

    if sort and sort in _SORT_MAP:
        params["sort"] = _SORT_MAP[sort]
    if page > 1:
        params["page"] = str(page)

    uri = f"/search?{urlencode(params)}"

    p_parts: list[str] = []
    if brand:
        for b in brand.split(","):
            p_parts.append(f"p%5B%5D=facets.brand%5B%5D%3D{quote(b.strip())}")
    if min_price is not None:
        p_parts.append(f"p%5B%5D=facets.price_range.from%3D{min_price}")
    if max_price is not None:
        p_parts.append(f"p%5B%5D=facets.price_range.to%3D{max_price}")
    if filters:
        for key, values in filters.items():
            for v in values:
                p_parts.append(f"p%5B%5D=facets.{quote(key)}%5B%5D%3D{quote(v)}")

    if p_parts:
        uri += "&" + "&".join(p_parts)

    return uri


def _parse_product(raw: dict) -> Product | None:
    val = raw.get("productInfo", {}).get("value", {})
    if not val:
        return None

    pid = val.get("id", "")
    titles = val.get("titles", {})
    title = titles.get("title", "") if isinstance(titles, dict) else ""
    if not title:
        return None

    smart_url = val.get("smartUrl", "")
    if smart_url.startswith("http"):
        url = smart_url
    else:
        url = f"https://www.flipkart.com{smart_url}"

    images = val.get("media", {}).get("images", [])
    image = None
    if images:
        image = (
            images[0]
            .get("url", "")
            .replace("{@width}", "416")
            .replace("{@height}", "416")
            .replace("{@quality}", "70")
        )

    pricing = val.get("pricing", {})
    fsp = pricing.get("finalPrice", {})
    mrp = pricing.get("mrp", {})

    price = None
    if fsp and fsp.get("decimalValue"):
        price = int(float(fsp["decimalValue"]))
    original_price = None
    if mrp and mrp.get("decimalValue"):
        original_price = int(float(mrp["decimalValue"]))

    rating_data = val.get("rating", {})
    rating = rating_data.get("average") if rating_data else None
    rating_count = rating_data.get("count") if rating_data else None

    brand = val.get("productBrand")
    specs = val.get("keySpecs", []) or []

    return Product(
        source="flipkart",
        id=pid,
        title=title,
        url=url,
        image=image,
        price=price,
        original_price=original_price,
        rating=rating,
        rating_count=rating_count,
        brand=brand,
        specs=specs,
    )


def _parse_filters(slots: list[dict]) -> list[FilterGroup]:
    groups: list[FilterGroup] = []
    for slot in slots:
        widget = slot.get("widget", {})
        if widget.get("type") != "FILTERS":
            continue

        filters_data = widget.get("data", {}).get("filters", {})
        if not isinstance(filters_data, dict):
            continue

        facet_response = filters_data.get("facetResponse", {})
        facets = facet_response.get("facets", [])

        for facet in facets:
            if not isinstance(facet, dict):
                continue
            title = facet.get("title", "")
            facet_id = facet.get("id", "")
            if not title:
                continue

            options: list[FilterOption] = []
            for value_group in facet.get("values", []):
                if not isinstance(value_group, dict):
                    continue
                for v in value_group.get("values", []):
                    if not isinstance(v, dict):
                        continue
                    label = v.get("title", "")
                    resource = v.get("resource", {})
                    param_val = resource.get("params", "") if resource else ""
                    count = v.get("count")
                    if label:
                        options.append(
                            FilterOption(label=label, value=param_val, count=count)
                        )

            if options:
                groups.append(FilterGroup(name=title, key=facet_id, options=options))
        break

    return groups


def _parse_sort_options(slots: list[dict]) -> list[SortOption]:
    options: list[SortOption] = []
    for slot in slots:
        widget = slot.get("widget", {})
        if widget.get("type") != "FILTER_SORT_OPTIONS":
            continue
        for opt in widget.get("data", {}).get("sortOptions", []):
            val = opt.get("value", {})
            title = val.get("title", "") if isinstance(val, dict) else ""
            action = opt.get("action", {})
            params = action.get("params", {}) if action else {}
            sort_val = params.get("value", "") if isinstance(params, dict) else ""
            if title:
                options.append(SortOption(label=title, value=sort_val))
        break
    return options


async def search(
    query: str,
    page: int = 1,
    sort: str | None = None,
    min_price: int | None = None,
    max_price: int | None = None,
    brand: str | None = None,
    filters: dict[str, list[str]] | None = None,
    timeout: int = 15,
) -> SearchResponse:
    page_uri = _build_page_uri(
        query,
        page=page,
        sort=sort,
        min_price=min_price,
        max_price=max_price,
        brand=brand,
        filters=filters,
    )

    page_context: dict = {"fetchSeoData": True}

    # Use all params to prevent cache collisions across different price/brand filters
    filter_str = json.dumps(filters, sort_keys=True) if filters else ""
    ccsi_key = ("flipkart_ccsi", query, str(sort), str(min_price), str(max_price), str(brand), filter_str)

    cached_ccsi = cache.get(*ccsi_key)
    if page > 1 and cached_ccsi:
        page_context["paginatedFetch"] = True
        page_context["pageNumber"] = page
        page_context["paginationContextMap"] = {
            "federator": {"SHOP_CARD": 0, "ccsi": cached_ccsi}
        }

    ssid = f"tbk3xszkzk000000{str(uuid.uuid4().int)[:12]}"
    sqid = f"{str(uuid.uuid4().int)[:12]}"

    body = {
        "pageUri": page_uri,
        "pageContext": page_context,
        "requestContext": {"type": "BROWSE_PAGE", "ssid": ssid, "sqid": sqid},
    }

    async with httpx.AsyncClient(
        headers=_HEADERS, follow_redirects=True, timeout=timeout
    ) as client:
        resp = await client.post(_API_BASE, json=body)
        resp.raise_for_status()

    data = resp.json()
    response = data.get("RESPONSE", {})
    slots = response.get("slots", [])
    
    if page == 1:
        page_data = response.get("pageData", {})
        pagination_ctx = page_data.get("paginationContextMap", {})
        if pagination_ctx:
            ccsi = pagination_ctx.get("federator", {}).get("ccsi", "")
            if ccsi:
                cache.set(ccsi, *ccsi_key, ttl=300)

    products: list[Product] = []
    for slot in slots:
        widget = slot.get("widget", {})
        if widget.get("type") != "PRODUCT_SUMMARY":
            continue
        for raw_product in widget.get("data", {}).get("products", []):
            p = _parse_product(raw_product)
            if p:
                products.append(p)

    filter_groups = _parse_filters(slots)
    sort_options = _parse_sort_options(slots)

    page_data = response.get("pageData", {})
    has_next = page_data.get("hasMorePages", False)
    total = None
    for slot in slots:
        widget = slot.get("widget", {})
        if widget.get("type") == "FILTER_SORT_OPTIONS":
            total_str = widget.get("data", {}).get("totalCount")
            if total_str is not None:
                total = int(total_str)
            break

    return SearchResponse(
        query=query,
        source="flipkart",
        page=page,
        total_results=total,
        has_next_page=has_next,
        products=products,
        filters=filter_groups,
        sort_options=sort_options,
    )
