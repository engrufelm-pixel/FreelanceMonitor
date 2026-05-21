import asyncio
import logging
import os
import random
from typing import Any

from playwright.async_api import async_playwright
from playwright_stealth import Stealth

logger = logging.getLogger(__name__)

# Общая лента — категорийные URL сейчас редиректят сюда же
YOUDO_URLS = [
    "https://youdo.com/tasks-all-opened-all",
]

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:131.0) Gecko/20100101 Firefox/131.0",
]

# Под реальную верстку: li.TasksList_listItem__*, внутри a[href*="/t<id>"]
_EXTRACT_JS = r"""
() => {
    const seen = new Set();
    const results = [];

    document.querySelectorAll('li[class*="TasksList_listItem"]').forEach(card => {
        const a = card.querySelector('a[href*="/t"]');
        if (!a) return;
        // /t<digits> — это задача; /u<digits> — это пользователь, пропускаем
        const m = a.href.match(/youdo\.com\/t(\d+)/);
        if (!m) return;
        const id = m[1];
        if (seen.has(id)) return;
        seen.add(id);

        const text = (card.innerText || '').trim();
        if (text.length < 10) return;

        const lines = text.split('\n').map(s => s.trim()).filter(Boolean);
        const title = (lines[0] || '').substring(0, 250);

        // Описание — строки до бюджета/пользователя
        const stopRe = /^(до|Бизнес-задание|\d[\d\s ]{0,12}\s*(?:руб|₽))/i;
        const descLines = [];
        for (let i = 1; i < lines.length; i++) {
            if (stopRe.test(lines[i])) break;
            descLines.push(lines[i]);
        }
        const description = descLines.join(' ').substring(0, 1500);

        // Бюджет: "до 3 000 ₽" или "3 000 ₽"
        let budget = 0;
        const bm = text.match(/(\d[\d\s ]{0,14})\s*(?:руб|₽|р\.)/i);
        if (bm) budget = parseInt(bm[1].replace(/\D/g, '')) || 0;

        results.push({
            external_id: id,
            title: title,
            description: description || title,
            budget: budget,
            url: a.href.split('?')[0].split('#')[0],
        });
    });
    return results;
}
"""


async def fetch_youdo_tasks() -> list[dict[str, Any]]:
    headless = os.getenv("YOUDO_HEADLESS", "true").lower() in ("1", "true", "yes")
    logger.info("YouDo: запуск парсера (headless=%s)", headless)

    all_tasks: list[dict[str, Any]] = []
    try:
        async with Stealth().use_async(async_playwright()) as p:
            browser = await p.chromium.launch(headless=headless)
            try:
                context = await browser.new_context(
                    user_agent=random.choice(USER_AGENTS),
                    locale="ru-RU",
                    viewport={"width": 1366, "height": 800},
                    extra_http_headers={"Accept-Language": "ru-RU,ru;q=0.9"},
                )
                page = await context.new_page()

                for url in YOUDO_URLS:
                    try:
                        await page.goto(url, timeout=60000, wait_until="domcontentloaded")
                        # React грузит ленту медленно — ждём фиксированно, без wait_for_selector
                        await page.wait_for_timeout(7000)
                        await page.evaluate("window.scrollBy(0, 2000)")
                        await page.wait_for_timeout(3000)

                        raw = await page.evaluate(_EXTRACT_JS)
                        if not raw:
                            # Дадим React ещё шанс
                            await page.wait_for_timeout(5000)
                            raw = await page.evaluate(_EXTRACT_JS)
                        for item in raw or []:
                            ext_id = str(item.get("external_id") or "").strip()
                            title = (item.get("title") or "").strip()
                            link = (item.get("url") or "").strip()
                            if not ext_id or not title or not link:
                                continue
                            all_tasks.append(
                                {
                                    "source": "YouDo",
                                    "external_id": ext_id,
                                    "title": title,
                                    "description": (item.get("description") or "").strip(),
                                    "budget": int(item.get("budget") or 0),
                                    "url": link,
                                }
                            )
                        await asyncio.sleep(random.uniform(2, 5))
                    except Exception as e:
                        logger.error("YouDo: ошибка на %s: %s", url, e)
            finally:
                await browser.close()
    except Exception as e:
        logger.error("YouDo: сбой парсинга: %s", e, exc_info=True)
        return []

    unique = {t["external_id"]: t for t in all_tasks}
    result = list(unique.values())
    with_b = sum(1 for t in result if t["budget"] > 0)
    logger.info("YouDo: собрано %d задач (с бюджетом: %d)", len(result), with_b)
    return result
