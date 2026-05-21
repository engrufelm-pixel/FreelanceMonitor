import asyncio
import html as _html
import logging
import os
import random
import re
from typing import Any

import feedparser
from playwright.async_api import async_playwright
from playwright_stealth import Stealth

logger = logging.getLogger(__name__)

FL_RSS_URL = "https://www.fl.ru/rss/all.xml"
FL_HTML_URL = "https://www.fl.ru/projects/?kind=1"

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36"
)

_BUDGET_RE = re.compile(r"(\d[\d\s ]{1,12})\s*(?:руб|₽|р\.)", re.IGNORECASE)
_ID_RE = re.compile(r"/projects/(\d+)")


def _strip_html(text: str) -> str:
    no_tags = re.sub(r"<[^>]+>", " ", text or "")
    return _html.unescape(no_tags).replace("\xa0", " ").strip()


async def _fetch_via_rss() -> list[dict[str, Any]]:
    """Лёгкий путь: RSS-лента FL.ru (без браузера)."""
    try:
        feed = await asyncio.to_thread(feedparser.parse, FL_RSS_URL)
    except Exception as e:
        logger.error("FL.ru RSS: ошибка fetch: %s", e)
        return []

    tasks: list[dict[str, Any]] = []
    for entry in feed.entries:
        url = (entry.get("link") or "").strip()
        m = _ID_RE.search(url)
        if not m:
            continue
        title = _html.unescape((entry.get("title") or "").strip())
        if not title:
            continue
        desc = _strip_html(entry.get("summary") or "")
        text_for_budget = f"{title}\n{desc}"
        bm = _BUDGET_RE.search(text_for_budget)
        budget = int(re.sub(r"\D", "", bm.group(1))) if bm else 0
        tasks.append(
            {
                "source": "FL.ru",
                "external_id": m.group(1),
                "title": title[:250],
                "description": desc[:1500],
                "budget": budget,
                "url": url.split("?")[0].split("#")[0],
            }
        )
    logger.info("FL.ru RSS: %d записей", len(tasks))
    return tasks


_EXTRACT_JS = r"""
() => {
    const seen = new Set();
    const results = [];
    const links = document.querySelectorAll('a[href*="/projects/"]');

    for (const a of links) {
        const m = a.href.match(/\/projects\/(\d+)/);
        if (!m) continue;
        const id = m[1];
        if (seen.has(id)) continue;

        let card = a.closest('[class*="project"], [class*="card"], article, li');
        if (!card) card = a.parentElement?.parentElement || a.parentElement;
        const text = (card?.innerText || '').trim();
        if (text.length < 20) continue;

        let title = (a.innerText || '').trim();
        if (!title || title.length < 10) {
            title = text.split('\n').find(l => l.trim().length > 10) || text.split('\n')[0] || '';
        }
        title = title.trim().substring(0, 250);
        if (!title) continue;

        seen.add(id);
        let budget = 0;
        const bm = text.match(/(\d[\d\s ]{1,12})\s*(?:руб|₽|р\.)/i);
        if (bm) budget = parseInt(bm[1].replace(/\D/g, '')) || 0;

        results.push({
            external_id: id,
            title: title,
            description: text.substring(0, 1500),
            budget: budget,
            url: a.href.split('?')[0].split('#')[0],
        });
    }
    return results;
}
"""


async def _fetch_via_html() -> list[dict[str, Any]]:
    """HTML-fallback через Playwright + stealth."""
    headless = os.getenv("FL_HEADLESS", "true").lower() in ("1", "true", "yes")
    tasks: list[dict[str, Any]] = []
    try:
        async with Stealth().use_async(async_playwright()) as p:
            browser = await p.chromium.launch(headless=headless)
            try:
                context = await browser.new_context(
                    user_agent=USER_AGENT,
                    locale="ru-RU",
                    viewport={"width": 1366, "height": 800},
                    extra_http_headers={"Accept-Language": "ru-RU,ru;q=0.9"},
                )
                page = await context.new_page()
                await page.goto(FL_HTML_URL, timeout=45000, wait_until="domcontentloaded")
                try:
                    await page.wait_for_selector('a[href*="/projects/"]', timeout=15000)
                except Exception:
                    logger.warning("FL.ru HTML: проекты не появились")
                await asyncio.sleep(random.uniform(1.5, 3.0))
                raw = await page.evaluate(_EXTRACT_JS)
                for item in raw or []:
                    ext_id = str(item.get("external_id") or "").strip()
                    title = (item.get("title") or "").strip()
                    link = (item.get("url") or "").strip()
                    if not ext_id or not title or not link:
                        continue
                    tasks.append(
                        {
                            "source": "FL.ru",
                            "external_id": ext_id,
                            "title": title,
                            "description": (item.get("description") or "").strip(),
                            "budget": int(item.get("budget") or 0),
                            "url": link,
                        }
                    )
            finally:
                await browser.close()
    except Exception as e:
        logger.error("FL.ru HTML: %s", e, exc_info=True)
        return []
    logger.info("FL.ru HTML: %d записей", len(tasks))
    return tasks


async def fetch_fl_tasks() -> list[dict[str, Any]]:
    """RSS как основной источник, HTML как fallback при пустом RSS."""
    tasks = await _fetch_via_rss()
    if not tasks:
        logger.info("FL.ru: RSS пуст, пробую HTML")
        tasks = await _fetch_via_html()
    unique = {t["external_id"]: t for t in tasks}
    return list(unique.values())
