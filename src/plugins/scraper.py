from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from urllib.parse import urljoin, urlparse

import requests_cache
from bs4 import BeautifulSoup

from ..config import Settings

log = logging.getLogger(__name__)

CANDIDATE_PATHS = ("/", "/about", "/about-us", "/contact", "/contact-us", "/products")


@dataclass
class ScrapedPage:
    url: str
    text: str


class Scraper:
    def __init__(self, settings: Settings) -> None:
        self._timeout = settings.request_timeout_s
        self._char_cap = settings.page_char_cap
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
        for path in CANDIDATE_PATHS:
            url = urljoin(root + "/", path.lstrip("/"))
            if url in seen:
                continue
            seen.add(url)
            text = self._fetch_one(url)
            if text:
                pages.append(ScrapedPage(url=url, text=text))
        return pages

    def _fetch_one(self, url: str) -> str | None:
        try:
            r = self._session.get(url, timeout=self._timeout, allow_redirects=True)
        except Exception as e:
            log.debug("fetch failed %s: %s", url, e)
            return None
        if r.status_code != 200 or "html" not in r.headers.get("Content-Type", "").lower():
            return None
        return _extract_visible_text(r.text)[: self._char_cap]


def _extract_visible_text(html: str) -> str:
    soup = BeautifulSoup(html, "lxml")
    for tag in soup(["script", "style", "noscript", "svg", "iframe", "head"]):
        tag.decompose()
    # Drop nav/footer chrome — usually link soup, low signal.
    for tag in soup.find_all(["nav", "footer", "header"]):
        tag.decompose()
    text = soup.get_text(separator=" ", strip=True)
    # Collapse runs of whitespace.
    return " ".join(text.split())
