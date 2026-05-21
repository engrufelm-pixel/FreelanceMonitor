"""Разведка верстки Kwork и YouDo — сохраняет HTML и пробует разные селекторы."""
import asyncio
import io
import sys
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from playwright.async_api import async_playwright
from playwright_stealth import Stealth

OUT = Path(__file__).parent / "dumps"
OUT.mkdir(exist_ok=True)


async def inspect(name: str, url: str, wait_ms: int = 5000):
    async with Stealth().use_async(async_playwright()) as p:
        browser = await p.chromium.launch(headless=True)
        try:
            ctx = await browser.new_context(
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                           "(KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36",
                locale="ru-RU",
                viewport={"width": 1366, "height": 800},
                extra_http_headers={"Accept-Language": "ru-RU,ru;q=0.9"},
            )
            page = await ctx.new_page()
            await page.goto(url, timeout=45000, wait_until="domcontentloaded")
            await page.wait_for_timeout(wait_ms)
            # Прокрутка для ленивых карточек
            await page.evaluate("window.scrollBy(0, 2000)")
            await page.wait_for_timeout(2000)

            html = await page.content()
            (OUT / f"{name}.html").write_text(html, encoding="utf-8")

            # Снимем подсказки про селекторы
            probes = await page.evaluate(r"""
            () => {
                const out = {};
                const candidates = [
                    'a[href*="/projects/"]',
                    'a[href*="/tasks/"]',
                    'a[href*="/t-"]',
                    'a[href*="/task/"]',
                    '[class*="project"]',
                    '[class*="want"]',
                    '[class*="card"]',
                    '[class*="task"]',
                    '[class*="Card"]',
                    '[class*="Task"]',
                    '[data-id]',
                    '[data-task-id]',
                ];
                for (const sel of candidates) {
                    out[sel] = document.querySelectorAll(sel).length;
                }
                // Найдём примеры классов на карточках, содержащих "₽" или "руб"
                const samples = [];
                document.querySelectorAll('div, article, li').forEach(el => {
                    const t = (el.innerText || '').trim();
                    if (t.length < 30 || t.length > 800) return;
                    if (!/руб|₽/.test(t)) return;
                    const a = el.querySelector('a[href]');
                    if (!a) return;
                    samples.push({
                        tag: el.tagName,
                        cls: el.className?.toString?.().substring(0, 200),
                        href: a.href,
                        text_first_120: t.substring(0, 120).replace(/\s+/g, ' '),
                    });
                });
                out._samples = samples.slice(0, 5);
                return out;
            }
            """)
            print(f"\n=== {name} ({page.url}) ===")
            for k, v in probes.items():
                if k == "_samples":
                    continue
                print(f"  {k}: {v}")
            print("  --- samples with currency ---")
            for s in probes.get("_samples", []):
                print(f"  <{s['tag']} class='{s['cls']}'>")
                print(f"    href={s['href']}")
                print(f"    text={s['text_first_120']}")
        finally:
            await browser.close()


async def main():
    await inspect("kwork", "https://kwork.ru/projects", wait_ms=4000)
    await inspect("youdo", "https://youdo.com/tasks-all-opened-all", wait_ms=7000)
    await inspect("youdo_prog", "https://youdo.com/tasks/?categories=programming", wait_ms=7000)


asyncio.run(main())
