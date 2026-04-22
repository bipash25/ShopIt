from __future__ import annotations

from pydantic import BaseModel, Field


class Product(BaseModel):
    """A single product listing from Amazon or Flipkart."""

    source: str = Field(description="Origin site — `amazon` or `flipkart`")
    id: str = Field(description="Product identifier (ASIN for Amazon, product ID for Flipkart)")
    title: str = Field(description="Full product title")
    url: str = Field(description="Direct link to the product page")
    image: str | None = Field(default=None, description="Product thumbnail URL")
    price: int | None = Field(default=None, description="Current selling price in INR (whole rupees)")
    original_price: int | None = Field(default=None, description="MRP / list price before discount, in INR")
    currency: str = Field(default="INR", description="Currency code (always INR)")
    rating: float | None = Field(default=None, description="Average customer rating (out of 5)")
    rating_count: int | None = Field(default=None, description="Total number of customer ratings")
    brand: str | None = Field(default=None, description="Brand name (reliably available on Flipkart)")
    specs: list[str] = Field(default_factory=list, description="Key specifications (Flipkart only — e.g. '128 GB ROM', '48MP Camera')")
    sponsored: bool = Field(default=False, description="Whether this is a sponsored/promoted listing")


class FilterOption(BaseModel):
    """A single selectable option within a filter group."""

    label: str = Field(description="Human-readable label (e.g. 'Apple', '128 GB', '4 Stars & Up')")
    value: str = Field(description="Value to pass back as a filter param — for Amazon, use as the `rh` query param")
    count: int | None = Field(default=None, description="Number of matching products (when available)")


class FilterGroup(BaseModel):
    """A group of related filter options (e.g. Brand, Price Range, RAM)."""

    name: str = Field(description="Filter category name (e.g. 'Brands', 'Storage Capacity', 'Customer Reviews')")
    key: str = Field(description="Machine-readable key for this filter group")
    options: list[FilterOption] = Field(default_factory=list, description="Available filter options")


class SortOption(BaseModel):
    """An available sort order for results."""

    label: str = Field(description="Human-readable sort label (e.g. 'Price -- Low to High')")
    value: str = Field(description="Value to pass as the `sort` query parameter")


class SearchResponse(BaseModel):
    """Complete search result from a single source, including products, filters, and pagination info."""

    query: str = Field(description="The search query that was executed")
    source: str = Field(description="Source site — `amazon` or `flipkart`")
    page: int = Field(default=1, description="Current page number (1 when `all_pages=true`)")
    total_results: int | None = Field(default=None, description="Estimated total matching products (when reported by the source)")
    total_pages_fetched: int = Field(default=1, description="Number of pages fetched — >1 when `all_pages=true`")
    has_next_page: bool = Field(default=False, description="Whether more pages are available (always `false` when `all_pages=true`)")
    products: list[Product] = Field(default_factory=list, description="List of product results")
    filters: list[FilterGroup] = Field(default_factory=list, description="Available filters for this query — pass option values back as params to narrow results")
    sort_options: list[SortOption] = Field(default_factory=list, description="Available sort orders — pass the `value` as the `sort` query param")
    cached: bool = Field(default=False, description="`true` if this response was served from cache")
