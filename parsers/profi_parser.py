import asyncio
import json
import logging
import os
import random
from pathlib import Path
from typing import Any

from playwright.async_api import async_playwright
from playwright_stealth import Stealth

logger = logging.getLogger(__name__)

PROFI_URLS = [
    "https://profi.ru/backoffice/n.php",
    "https://profi.ru/zakazy/sozdanie-botov/",
    "https://profi.ru/zakazy/razrabotka-saytov/",
    "https://profi.ru/zakazy/programmirovanie/",
]

COOKIES_FILE = Path(__file__).parent / "profi_cookies.json"

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36"
)


class CookiesExpiredError(RuntimeError):
    """Сигнал монитору: куки Profi.ru протухли, нужен повторный импорт."""


_EXTRACT_JS = r"""
() => {
    const seen = new Set();
    const results = [];
    const links = document.querySelectorAll('a[href*="/zakazy/"], a[href*="/backoffice/"]');

    for (const a of links) {
        const m = a.href.match(/\/(?:zakaz|order)\/([\w\-]+)/) || a.href.match(/id=(\d+)/);
        if (!m) continue;
        const id = m[1];
        if (!id || seen.has(id)) continue;

        let card = a.closest('[class*="OrderCard"], [class*="order-card"], [class*="card"], article, li');
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


def _load_cookies() -> list[dict] | None:
    if not COOKIES_FILE.exists():
        logger.warning("Profi.ru: %s не найден", COOKIES_FILE.name)
        return None
    try:
        with COOKIES_FILE.open("r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict) and "cookies" in data:
            data = data["cookies"]
        # Нормализация под формат Playwright
        normalized = []
        for c in data:
            if not c.get("name"):
                continue
            entry = {
                "name": c["name"],
                "value": c.get("value", ""),
                "domain": c.get("domain", ".profi.ru"),
                "path": c.get("path", "/"),
            }
            if "expires" in c and c["expires"]:
                entry["expires"] = int(c["expires"])
            if c.get("secure"):
                entry["secure"] = True
            if c.get("httpOnly"):
                entry["httpOnly"] = True
            if c.get("sameSite"):
                ss = c["sameSite"]
                entry["sameSite"] = ss if ss in ("Strict", "Lax", "None") else "Lax"
            normalized.append(entry)
        return normalized
    except Exception as e:
        logger.error("Profi.ru: не удалось прочитать куки: %s", e)
        return None


def _looks_like_login_page(url: str, title: str) -> bool:
    u = (url or "").lower()
    t = (title or "").lower()
    return any(s in u for s in ["/login", "/signin", "/auth"]) or "вход" in t


async def fetch_profi_tasks() -> list[dict[str, Any]]:
    """Парсит задачи Profi.ru через сохранённые куки. Бросает CookiesExpiredError при редиректе на логин."""
    headless = os.getenv("PROFI_HEADLESS", "true").lower() in ("1", "true", "yes")
    logger.info("Profi.ru: запуск парсера (headless=%s)", headless)

    cookies = _load_cookies()
    all_tasks: list[dict[str, Any]] = []

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
                if cookies:
                    try:
                        await context.add_cookies(cookies)
                    except Exception as e:
                        logger.error("Profi.ru: add_cookies упал: %s", e)
                page = await context.new_page()

                for url in PROFI_URLS:
                    try:
                        await page.goto(url, timeout=45000, wait_until="domcontentloaded")
                        final_url = page.url
                        page_title = await page.title()
                        if _looks_like_login_page(final_url, page_title):
                            raise CookiesExpiredError(
                                f"Редирект на логин: {final_url}"
                            )
                        await asyncio.sleep(random.uniform(1.5, 3.0))
                        raw = await page.evaluate(_EXTRACT_JS)
                        for item in raw or []:
                            ext_id = str(item.get("external_id") or "").strip()
                            title = (item.get("title") or "").strip()
                            link = (item.get("url") or "").strip()
                            if not ext_id or not title or not link:
                                continue
                            all_tasks.append(
                                {
                                    "source": "Profi.ru",
                                    "external_id": ext_id,
                                    "title": title,
                                    "description": (item.get("description") or "").strip(),
                                    "budget": int(item.get("budget") or 0),
                                    "url": link,
                                }
                            )
                        await asyncio.sleep(random.uniform(2, 5))
                    except CookiesExpiredError:
                        raise
                    except Exception as e:
                        logger.error("Profi.ru: ошибка на %s: %s", url, e)
            finally:
                await browser.close()
    except CookiesExpiredError as e:
        logger.error("Profi.ru: %s", e)
        return []
    except Exception as e:
        logger.error("Profi.ru: сбой парсинга: %s", e, exc_info=True)
        return []

    unique = {t["external_id"]: t for t in all_tasks}
    result = list(unique.values())
    logger.info("Profi.ru: собрано %d задач", len(result))
    return result
