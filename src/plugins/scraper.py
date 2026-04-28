from __future__ import annotations

import asyncio
import json
import logging
import re
from dataclasses import dataclass, field
from urllib.parse import urljoin, urlparse

import requests_cache
from bs4 import BeautifulSoup

from ..config import Settings

log = logging.getLogger(__name__)

INDEX_PATHS = (
    "/",
    "/about",
    "/about-us",
    "/contact",
    "/contact-us",
    "/products",
    "/shop",
    "/store",
    "/collections",
    "/catalog",
    "/menu",
)

PRODUCT_LINK_PATTERNS = (
    re.compile(r"/products?/[^/?#]+"),
    re.compile(r"/p/[^/?#]+"),
    re.compile(r"/item/[^/?#]+"),
    re.compile(r"/shop/[^/?#]+/[^/?#]+"),
    re.compile(r"/collections/[^/?#]+/products/[^/?#]+"),
)


@dataclass
class ScrapedPage:
    url: str
    text: str
    json_ld: list[dict] = field(default_factory=list)


class Scraper:
    def __init__(self, settings: Settings) -> None:
        self._timeout = settings.request_timeout_s
        self._char_cap = settings.page_char_cap
        self._max_product_pages = settings.max_product_pages
        self._session = requests_cache.CachedSession(
            settings.cache_path,
            expire_after=60 * 60 * 24 * 7,
            allowable_codes=(200, 301, 302, 404),
        )
        self._session.headers.update({"User-Agent": settings.user_agent})

    async def fetch_site(self, base_url: str) -> list[ScrapedPage]:
        return await asyncio.to_thread(self._fetch_site_sync, base_url)

    def _fetch_site_sync(self, base_url: str) -> list[ScrapedPage]:
        parsed = urlparse(base_url)
        if not parsed.scheme:
            base_url = "https://" + base_url
        root = f"{urlparse(base_url).scheme}://{urlparse(base_url).hostname}"

        pages: list[ScrapedPage] = []
        seen: set[str] = set()
        product_link_pool: list[str] = []

        for path in INDEX_PATHS:
            url = urljoin(root + "/", path.lstrip("/"))
            if url in seen:
                continue
            seen.add(url)
            page = self._fetch_one(url)
            if page is None:
                continue
            pages.append(page)
            product_link_pool.extend(self._discover_product_links(url, root))

        for product_url in self._dedupe(product_link_pool)[: self._max_product_pages]:
            if product_url in seen:
                continue
            seen.add(product_url)
            page = self._fetch_one(product_url)
            if page is not None:
                pages.append(page)

        return pages

    def _fetch_one(self, url: str) -> ScrapedPage | None:
        try:
            r = self._session.get(url, timeout=self._timeout, allow_redirects=True)
        except Exception as e:
            log.debug("fetch failed %s: %s", url, e)
            return None
        if r.status_code != 200 or "html" not in r.headers.get("Content-Type", "").lower():
            return None
        text = _extract_visible_text(r.text)[: self._char_cap]
        if not text:
            return None
        return ScrapedPage(
            url=str(r.url),
            text=text,
            json_ld=_extract_json_ld(r.text),
        )

    def _discover_product_links(self, page_url: str, root: str) -> list[str]:
        try:
            r = self._session.get(page_url, timeout=self._timeout)
        except Exception:
            return []
        if r.status_code != 200:
            return []
        soup = BeautifulSoup(r.text, "lxml")
        host = urlparse(root).hostname or ""
        out: list[str] = []
        for a in soup.find_all("a", href=True):
            href = a["href"]
            full = urljoin(page_url, href)
            parsed = urlparse(full)
            if parsed.hostname and parsed.hostname != host:
                continue
            path = parsed.path
            if any(p.search(path) for p in PRODUCT_LINK_PATTERNS):
                out.append(full.split("#")[0])
        return out

    @staticmethod
    def _dedupe(items: list[str]) -> list[str]:
        seen: set[str] = set()
        out: list[str] = []
        for it in items:
            if it not in seen:
                seen.add(it)
                out.append(it)
        return out


def _extract_visible_text(html: str) -> str:
    soup = BeautifulSoup(html, "lxml")
    for tag in soup(["script", "style", "noscript", "svg", "iframe", "head"]):
        tag.decompose()
    for tag in soup.find_all(["nav", "footer", "header"]):
        tag.decompose()
    text = soup.get_text(separator=" ", strip=True)
    return " ".join(text.split())


def _extract_json_ld(html: str) -> list[dict]:
    """Pull schema.org JSON-LD blobs. Most retail sites emit Product / Offer /
    Organization / LocalBusiness here — far more reliable than scraping prose."""
    soup = BeautifulSoup(html, "lxml")
    out: list[dict] = []
    for tag in soup.find_all("script", attrs={"type": "application/ld+json"}):
        raw = tag.string or tag.get_text() or ""
        if not raw.strip():
            continue
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if isinstance(data, list):
            out.extend(d for d in data if isinstance(d, dict))
        elif isinstance(data, dict):
            graph = data.get("@graph")
            if isinstance(graph, list):
                out.extend(d for d in graph if isinstance(d, dict))
            else:
                out.append(data)
    return out
