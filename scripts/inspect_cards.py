"""Глубокая инспекция: дампим innerText карточки Kwork и YouDo, проверяем regex."""
import asyncio
import io
import re
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

from playwright.async_api import async_playwright
from playwright_stealth import Stealth


async def main():
    async with Stealth().use_async(async_playwright()) as p:
        browser = await p.chromium.launch(headless=True)
        try:
            ctx = await browser.new_context(
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                           "(KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36",
                locale="ru-RU",
                viewport={"width": 1366, "height": 800},
            )
            page = await ctx.new_page()

            # === KWORK ===
            await page.goto("https://kwork.ru/projects", timeout=45000, wait_until="domcontentloaded")
            await page.wait_for_timeout(4000)
            await page.evaluate("window.scrollBy(0, 2000)")
            await page.wait_for_timeout(2000)

            cards = await page.evaluate(r"""
            () => {
                const out = [];
                document.querySelectorAll('.want-card').forEach((card, i) => {
                    if (i >= 3) return;
                    const a = card.querySelector('a[href*="/projects/"]');
                    out.push({
                        cls: card.className,
                        href: a ? a.href : null,
                        innerText: (card.innerText || '').substring(0, 600),
                    });
                });
                return out;
            }
            """)

            print("=== KWORK first 3 want-cards ===")
            BUDGET_RE = re.compile(r"(\d[\d\s\xa0]{0,12})\s*(?:руб|₽|р\.)", re.IGNORECASE)
            for c in cards:
                print(f"\nhref: {c['href']}")
                print(f"text: {c['innerText'][:400]}")
                m = BUDGET_RE.search(c["innerText"])
                if m:
                    raw = m.group(1)
                    clean = re.sub(r"\D", "", raw)
                    print(f"BUDGET MATCH: {repr(raw)} -> {clean}")
                else:
                    print("NO BUDGET MATCH")

            # === YOUDO ===
            await page.goto("https://youdo.com/tasks-all-opened-all", timeout=45000, wait_until="domcontentloaded")
            await page.wait_for_timeout(7000)
            await page.evaluate("window.scrollBy(0, 2000)")
            await page.wait_for_timeout(2000)

            cards = await page.evaluate(r"""
            () => {
                const out = [];
                document.querySelectorAll('li[class*="TasksList_listItem"]').forEach((card, i) => {
                    if (i >= 3) return;
                    const a = card.querySelector('a[href*="/t"]');
                    out.push({
                        cls: card.className,
                        href: a ? a.href : null,
                        innerText: (card.innerText || '').substring(0, 600),
                    });
                });
                return out;
            }
            """)

            print("\n\n=== YOUDO first 3 listItems ===")
            for c in cards:
                print(f"\nhref: {c['href']}")
                print(f"text: {c['innerText'][:400]}")
                m = BUDGET_RE.search(c["innerText"])
                if m:
                    raw = m.group(1)
                    clean = re.sub(r"\D", "", raw)
                    print(f"BUDGET MATCH: {repr(raw)} -> {clean}")
                else:
                    print("NO BUDGET MATCH")
        finally:
            await browser.close()


asyncio.run(main())
