import asyncio
import logging
import os
import random
from typing import Any

from playwright.async_api import async_playwright
from playwright_stealth import Stealth

logger = logging.getLogger(__name__)

KWORK_URL = "https://kwork.ru/projects"

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:131.0) Gecko/20100101 Firefox/131.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36",
]

# Привязан к реальной верстке Kwork (want-card), бюджет учитывает NBSP
_EXTRACT_JS = r"""
() => {
    const seen = new Set();
    const results = [];

    document.querySelectorAll('.want-card').forEach(card => {
        const a = card.querySelector('a[href*="/projects/"]');
        if (!a) return;
        const m = a.href.match(/\/projects\/(\d+)/);
        if (!m) return;
        const id = m[1];
        if (seen.has(id)) return;
        seen.add(id);

        const text = (card.innerText || '').trim();

        // Заголовок — первая значимая строка
        const lines = text.split('\n').map(s => s.trim()).filter(Boolean);
        let title = lines[0] || '';
        title = title.replace(/\s*Показать полностью\s*$/i, '').substring(0, 250);

        // Описание — первые несколько строк до бюджета/мета
        const stopWords = ['Желаемый бюджет', 'Допустимый', 'Покупатель:', 'Размещено', 'Нанято:', 'Осталось:', 'Предложений'];
        const descLines = [];
        for (let i = 1; i < lines.length; i++) {
            if (stopWords.some(w => lines[i].startsWith(w))) break;
            descLines.push(lines[i]);
        }
        const description = descLines.join(' ').replace(/\s*Показать полностью\s*/i, ' ').trim().substring(0, 1500);

        // Бюджет: первое число перед "₽" или "руб". NBSP включён явно.
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


async def fetch_kwork_tasks() -> list[dict[str, Any]]:
    headless = os.getenv("KWORK_HEADLESS", "true").lower() in ("1", "true", "yes")
    logger.info("Kwork: запуск парсера (headless=%s)", headless)

    try:
        async with Stealth().use_async(async_playwright()) as p:
            browser = await p.chromium.launch(headless=headless)
            try:
                context = await browser.new_context(
                    user_agent=random.choice(USER_AGENTS),
                    locale="ru-RU",
                    viewport={"width": 1366, "height": 800},
                    extra_http_headers={"Accept-Language": "ru-RU,ru;q=0.9,en;q=0.8"},
                )
                page = await context.new_page()
                await page.goto(KWORK_URL, timeout=45000, wait_until="domcontentloaded")
                try:
                    await page.wait_for_selector(".want-card", timeout=20000)
                except Exception:
                    logger.warning("Kwork: .want-card не появилась за 20 сек")
                await page.evaluate("window.scrollBy(0, document.body.scrollHeight)")
                await asyncio.sleep(random.uniform(1.5, 3.0))
                raw = await page.evaluate(_EXTRACT_JS)
            finally:
                await browser.close()
    except Exception as e:
        logger.error("Kwork: сбой парсинга: %s", e, exc_info=True)
        return []

    tasks: list[dict[str, Any]] = []
    for item in raw or []:
        ext_id = str(item.get("external_id") or "").strip()
        title = (item.get("title") or "").strip()
        url = (item.get("url") or "").strip()
        if not ext_id or not title or not url:
            continue
        tasks.append(
            {
                "source": "Kwork",
                "external_id": ext_id,
                "title": title,
                "description": (item.get("description") or "").strip(),
                "budget": int(item.get("budget") or 0),
                "url": url,
            }
        )

    with_budget = sum(1 for t in tasks if t["budget"] > 0)
    logger.info("Kwork: собрано %d задач (с бюджетом: %d)", len(tasks), with_budget)
    return tasks
