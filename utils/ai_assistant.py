import json
import logging
import re
from typing import Literal

from openai import AsyncOpenAI

from config import AI_MODEL, AITUNNEL_API_KEY, AITUNNEL_BASE_URL, DEVELOPER_PROFILE

logger = logging.getLogger(__name__)

Style = Literal["short", "confident", "balanced"]

_client: AsyncOpenAI | None = None


def _get_client() -> AsyncOpenAI:
    global _client
    if _client is None:
        _client = AsyncOpenAI(api_key=AITUNNEL_API_KEY, base_url=AITUNNEL_BASE_URL)
    return _client


# ── Скоринг ─────────────────────────────────────────────────────

_SCORE_SYSTEM = f"""Ты — ассистент фрилансера. Оцени задачу по матрице навыков разработчика.

Профиль:
{DEVELOPER_PROFILE}

Критерии оценки (взвешенно):
1. Соответствие стеку (Python, aiogram, FastAPI, парсинг, AI-интеграции, Google Sheets, лендинги без CMS)
2. Vibe coding — задача понятна, реализуема за 1-5 дней, не требует месяцев архитектуры
3. Токсичность/риски — нет признаков «сложный клиент», «микроменеджмент», «огромный объём правок за копейки», «бесконечные правки»

Шкала 0-100:
- 80-100: идеальное совпадение по стеку, чистый vibe coding
- 60-79: подходит, стандартная задача с лёгкими нюансами
- 40-59: на грани — частичное совпадение или непонятный объём
- 0-39: не подходит (другой стек / мобильная разработка / WordPress / крипта / геймдев / копирайт / спам)

Ответь СТРОГО валидным JSON без пояснений и без markdown-обёртки:
{{"score": <int 0-100>, "reason": "<одна короткая фраза>"}}"""


_JSON_RE = re.compile(r"\{.*\}", re.DOTALL)


def _extract_json(raw: str) -> dict:
    """Пытается достать JSON даже если модель обернула его в ```json ... ```."""
    raw = raw.strip()
    m = _JSON_RE.search(raw)
    if not m:
        raise ValueError(f"JSON not found in: {raw[:200]}")
    return json.loads(m.group(0))


async def score_task(title: str, description: str, budget: int | str = 0) -> dict:
    """Оценивает задачу 0-100. Возвращает {"score": int, "reason": str}."""
    budget_line = f"\nБюджет: {budget} ₽" if budget else ""
    user_msg = f"Заголовок: {title}{budget_line}\n\nОписание:\n{description or 'не указано'}"

    try:
        resp = await _get_client().chat.completions.create(
            model=AI_MODEL,
            messages=[
                {"role": "system", "content": _SCORE_SYSTEM},
                {"role": "user", "content": user_msg},
            ],
            max_tokens=150,
            temperature=0.2,
            response_format={"type": "json_object"},
        )
        raw = resp.choices[0].message.content or ""
        data = _extract_json(raw)
        score = max(0, min(100, int(data.get("score", 50))))
        reason = str(data.get("reason", "")).strip()[:200]
        return {"score": score, "reason": reason}
    except Exception as e:
        logger.error("score_task failed: %s", e)
        return {"score": 50, "reason": "parse_error"}


# ── Генерация откликов ─────────────────────────────────────────

_PITCH_STYLE_HINTS: dict[Style, str] = {
    "short": "Сделай отклик очень коротким (1-2 предложения + одна строка-CTA). Минимум воды, максимум сути.",
    "confident": "Звучи уверенно и по делу. Покажи, что уже делал такое. Без преувеличений вроде «гарантирую», но твёрдо.",
    "balanced": "Сбалансированный отклик 2-4 коротких абзаца. Дружелюбно, конкретно, без шаблонов.",
}


def _pitch_system(style: Style) -> str:
    style_hint = _PITCH_STYLE_HINTS.get(style, _PITCH_STYLE_HINTS["balanced"])
    return f"""Ты пишешь отклик на задачу с фриланс-биржи от лица разработчика.

Профиль разработчика:
{DEVELOPER_PROFILE}

Правила:
- Живой язык от первого лица. Никаких канцеляризмов.
- ЗАПРЕЩЕНО: «Здравствуйте, уважаемый заказчик», «я профессиональный разработчик с опытом N лет», «гарантирую качество», «выполню в срок».
- РАЗРЕШЕНО: «Привет», «Здравствуйте», конкретика типа «делал такое буквально на прошлой неделе», «понял задачу — нужно X».

Структура:
1. Короткое приветствие (1 строка).
2. Подтверждение понимания задачи + конкретный релевантный опыт.
3. Call to Action — «давайте созвонимся / напишите детали / могу прислать пример».

{style_hint}

Выдай ТОЛЬКО текст отклика, без префиксов «ОТКЛИК:», без markdown."""


async def generate_pitch(
    title: str, description: str, style: Style = "balanced", budget: int | str = 0
) -> str:
    """Генерирует отклик в нужном стиле. Возвращает готовый текст."""
    budget_line = f"\nБюджет: {budget} ₽" if budget else ""
    user_msg = f"Задача: {title}{budget_line}\n\nОписание:\n{description or 'не указано'}"

    try:
        resp = await _get_client().chat.completions.create(
            model=AI_MODEL,
            messages=[
                {"role": "system", "content": _pitch_system(style)},
                {"role": "user", "content": user_msg},
            ],
            max_tokens=600,
            temperature=0.8,
        )
        return (resp.choices[0].message.content or "").strip()
    except Exception as e:
        logger.error("generate_pitch failed: %s", e)
        return f"⚠️ Не удалось сгенерировать отклик: {e}"
