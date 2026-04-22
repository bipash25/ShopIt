from __future__ import annotations

import re
from urllib.parse import quote, urlencode

import httpx
from bs4 import BeautifulSoup, Tag

from app.models import (
    FilterGroup,
    FilterOption,
    Product,
    SearchResponse,
    SortOption,
)

_BASE = "https://www.amazon.in/s"

_HEADERS = {
    "user-agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/146.0.0.0 Safari/537.36"
    ),
    "accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "accept-language": "en-IN,en-GB;q=0.9,en-US;q=0.8,en;q=0.7",
    "sec-ch-ua": '"Chromium";v="146", "Not-A.Brand";v="24", "Google Chrome";v="146"',
    "sec-ch-ua-mobile": "?0",
    "sec-ch-ua-platform": '"Windows"',
    "sec-ch-device-memory": "8",
    "sec-ch-dpr": "1",
    "device-memory": "8",
    "dpr": "1",
    "downlink": "10",
    "ect": "4g",
    "rtt": "50",
    "viewport-width": "1920",
    "sec-ch-viewport-width": "1920",
    "upgrade-insecure-requests": "1",
    "sec-fetch-dest": "document",
    "sec-fetch-mode": "navigate",
    "sec-fetch-site": "none",
    "sec-fetch-user": "?1",
}

SORT_OPTIONS = [
    SortOption(label="Relevance", value="relevanceblender"),
    SortOption(label="Price: Low to High", value="price-asc-rank"),
    SortOption(label="Price: High to Low", value="price-desc-rank"),
    SortOption(label="Avg. Customer Reviews", value="review-rank"),
    SortOption(label="Newest Arrivals", value="date-desc-rank"),
]


def _build_url(
    query: str,
    page: int = 1,
    sort: str | None = None,
    min_price: int | None = None,
    max_price: int | None = None,
    brand: str | None = None,
    rh: str | None = None,
) -> str:
    params: dict[str, str] = {"k": query, "page": str(page)}

    rh_parts: list[str] = []
    if rh:
        rh_parts.append(rh)
    if min_price is not None or max_price is not None:
        lo = str(min_price or "")
        hi = str(max_price or "")
        rh_parts.append(f"p_36:{lo}-{hi}")
    if brand:
        rh_parts.append(f"p_89:{quote(brand)}")
    if rh_parts:
        params["rh"] = ",".join(rh_parts)

    if sort and sort != "relevanceblender":
        params["s"] = sort

    return f"{_BASE}?{urlencode(params)}"


def _parse_product(card: Tag) -> Product | None:
    asin = card.get("data-asin", "")
    if not asin:
        return None

    title = ""
    url = ""
    for link in card.find_all("a", href=lambda h: h and "/dp/" in h):
        text = link.get_text(strip=True)
        if text and len(text) > 5 and "₹" not in text and "out of" not in text:
            title = text
            href = link["href"].split("/ref=")[0]
            url = f"https://www.amazon.in{href}"
            break

    if not title:
        h2 = card.find("h2")
        if h2:
            title = h2.get_text(strip=True)

    if not title:
        return None

    img_el = card.find("img", class_="s-image")
    image = img_el.get("src", "") if img_el else None

    price = None
    original_price = None
    offscreen_prices = card.find_all("span", class_="a-offscreen")
    for i, el in enumerate(offscreen_prices):
        text = el.get_text(strip=True).replace("₹", "").replace(",", "")
        m = re.search(r"[\d]+", text)
        if m:
            val = int(m.group())
            if i == 0:
                price = val
            elif i == 1:
                original_price = val

    rating = None
    rating_el = card.find("span", class_="a-icon-alt")
    if rating_el:
        m = re.search(r"([\d.]+)", rating_el.get_text())
        if m:
            rating = float(m.group(1))

    rating_count = None
    for a_tag in card.find_all("a", href=True):
        text = a_tag.get_text(strip=True).replace(",", "")
        if text.isdigit():
            rating_count = int(text)
            break

    sponsored = bool(
        card.find("span", string=lambda t: t and "Sponsored" in str(t))
    )

    return Product(
        source="amazon",
        id=str(asin),
        title=title,
        url=url,
        image=image,
        price=price,
        original_price=original_price,
        rating=rating,
        rating_count=rating_count,
        sponsored=sponsored,
    )


def _parse_filters(soup: BeautifulSoup) -> list[FilterGroup]:
    groups: list[FilterGroup] = []
    refinements = soup.find("div", id="s-refinements")
    if not refinements:
        return groups

    title_divs = refinements.find_all("div", id=re.compile(r"-title$"))
    for td in title_divs:
        heading = td.get_text(strip=True)
        if not heading or heading.startswith("₹"):
            continue

        section_id = td.get("id", "").replace("-title", "")
        parent = td.parent
        if not parent:
            continue

        options: list[FilterOption] = []
        for li in parent.find_all("li"):
            a = li.find("a", href=True)
            if not a:
                continue
            label = a.get_text(strip=True)
            if not label or len(label) > 100:
                continue
            href = a["href"]
            rh_match = re.search(r"rh=([^&]+)", href)
            rh_val = rh_match.group(1) if rh_match else ""
            options.append(FilterOption(label=label, value=rh_val))

        if options:
            groups.append(FilterGroup(name=heading, key=section_id, options=options))

    return groups


async def search(
    query: str,
    page: int = 1,
    sort: str | None = None,
    min_price: int | None = None,
    max_price: int | None = None,
    brand: str | None = None,
    rh: str | None = None,
    timeout: int = 15,
) -> SearchResponse:
    url = _build_url(
        query,
        page=page,
        sort=sort,
        min_price=min_price,
        max_price=max_price,
        brand=brand,
        rh=rh,
    )

    async with httpx.AsyncClient(
        headers=_HEADERS, follow_redirects=True, timeout=timeout
    ) as client:
        resp = await client.get(url)
        resp.raise_for_status()

    soup = BeautifulSoup(resp.text, "lxml")

    cards = soup.find_all("div", attrs={"data-component-type": "s-search-result"})
    products = []
    for card in cards:
        p = _parse_product(card)
        if p:
            products.append(p)

    filters = _parse_filters(soup)

    pagination = soup.find("div", attrs={"data-component-type": "s-pagination"})
    has_next = False
    if pagination:
        has_next = bool(pagination.find("a", class_="s-pagination-next"))

    result_info = soup.find("div", attrs={"data-component-type": "s-result-info-bar"})
    total = None
    if result_info:
        m = re.search(r"([\d,]+)\s+results", result_info.get_text())
        if m:
            total = int(m.group(1).replace(",", ""))

    return SearchResponse(
        query=query,
        source="amazon",
        page=page,
        total_results=total,
        has_next_page=has_next,
        products=products,
        filters=filters,
        sort_options=SORT_OPTIONS,
    )
