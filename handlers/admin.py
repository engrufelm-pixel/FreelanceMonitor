import asyncio
import logging
from pathlib import Path

from aiogram import Bot, F, Router
from aiogram.filters import Command
from aiogram.types import (
    CallbackQuery,
    Document,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    Message,
    ReplyKeyboardMarkup,
)

from config import ADMIN_ID
from database.db_utils import clear_all, get_stats
from parsers.profi_parser import COOKIES_FILE
from services.monitor import format_run_stats, is_check_running, run_check

logger = logging.getLogger(__name__)

router = Router(name="admin")

# ── Названия Reply-кнопок (используются и в keyboard, и в фильтрах) ──
BTN_STATUS = "📊 Статус системы"
BTN_CHECK = "🔄 Проверить биржи"
BTN_COOKIES = "🍪 Импорт Cookies"

MAIN_KEYBOARD = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text=BTN_STATUS), KeyboardButton(text=BTN_CHECK)],
        [KeyboardButton(text=BTN_COOKIES)],
    ],
    resize_keyboard=True,
    is_persistent=True,
    input_field_placeholder="Нажми кнопку или пришли .json для Profi.ru",
)

DIVIDER = "─────────────────────────"

def _is_admin(user_id: int | None) -> bool:
    return user_id == ADMIN_ID


# ── /start: показать клавиатуру ─────────────────────────────────


@router.message(Command("start"))
async def cmd_start(message: Message) -> None:
    if not _is_admin(message.from_user.id if message.from_user else None):
        return
    text = (
        "🟢 <b>FreelanceMonitor</b>\n"
        f"{DIVIDER}\n"
        "Бот следит за лентой Kwork / YouDo / Profi.ru / FL.ru,\n"
        "оценивает задачи через GPT и присылает только релевантное.\n\n"
        "Используй кнопки внизу или загрузи cookies-файл для Profi.ru."
    )
    await message.answer(text, reply_markup=MAIN_KEYBOARD)


# ── 📊 Статус ───────────────────────────────────────────────────


@router.message(F.text == BTN_STATUS)
@router.message(Command("status"))
async def on_status(message: Message) -> None:
    if not _is_admin(message.from_user.id if message.from_user else None):
        return
    stats = await get_stats()
    by_status = stats["by_status"]
    by_source = stats["by_source"]

    cookies_line = "❌ не загружены"
    if COOKIES_FILE.exists():
        import datetime as _dt

        mtime = _dt.datetime.fromtimestamp(COOKIES_FILE.stat().st_mtime)
        cookies_line = f"✅ {mtime:%Y-%m-%d %H:%M}"

    parts = [
        "📊 <b>Статус системы</b>",
        DIVIDER,
        f"🍪 Profi cookies: {cookies_line}",
        f"📥 Обработано всего: <b>{stats['processed_total']}</b>",
        f"🕐 Последняя задача: <b>{stats['last_seen_at'] or '—'}</b>",
        DIVIDER,
        "<b>По статусам:</b>",
        f"  🚀 ready/sent:  {by_status.get('sent', 0) + by_status.get('ready_to_send', 0)}",
        f"  🟡 digest:      {by_status.get('digest', 0)}",
        f"  🔴 hidden:      {by_status.get('hidden', 0)}",
    ]
    if by_source:
        parts.append(DIVIDER)
        parts.append("<b>По источникам:</b>")
        for src, c in by_source.items():
            parts.append(f"  • {src}: {c}")

    await message.answer("\n".join(parts), reply_markup=MAIN_KEYBOARD)


# ── 🔄 Проверить биржи прямо сейчас ────────────────────────────


@router.message(F.text == BTN_CHECK)
@router.message(Command("check"))
async def on_check_now(message: Message, bot: Bot) -> None:
    if not _is_admin(message.from_user.id if message.from_user else None):
        return

    if is_check_running():
        await message.answer("⏳ Проверка уже идёт (возможно фоновая), дождись её завершения.")
        return

    await message.answer(
        "🔄 <b>Запускаю проверку всех бирж…</b>\n"
        "<i>Это займёт 1–3 минуты — пришлю карточки и итог.</i>"
    )

    async def _runner():
        try:
            stats = await run_check(bot, ADMIN_ID)
            await bot.send_message(ADMIN_ID, format_run_stats(stats))
        except Exception as e:
            logger.exception("Ручная проверка упала")
            await bot.send_message(ADMIN_ID, f"⚠️ Сбой проверки: {e}")

    asyncio.create_task(_runner())


# ── 🍪 Импорт Cookies ──────────────────────────────────────────


@router.message(F.text == BTN_COOKIES)
@router.message(Command("import_cookies"))
async def on_import_cookies(message: Message) -> None:
    if not _is_admin(message.from_user.id if message.from_user else None):
        return
    await message.answer(
        "🍪 <b>Импорт cookies Profi.ru</b>\n"
        f"{DIVIDER}\n"
        "1. Открой <b>profi.ru</b> в Chrome / Firefox под своим аккаунтом\n"
        "2. Установи расширение <b>Cookie-Editor</b>\n"
        "3. На странице profi.ru: Cookie-Editor → <b>Export → JSON</b>\n"
        "4. Сохрани как <code>profi_cookies.json</code>\n"
        "5. Пришли файл сюда следующим сообщением"
    )


@router.message(F.document)
async def on_document(message: Message, bot: Bot) -> None:
    if not _is_admin(message.from_user.id if message.from_user else None):
        return
    doc: Document = message.document
    name = (doc.file_name or "").lower()
    if not name.endswith(".json"):
        return

    try:
        Path(COOKIES_FILE).parent.mkdir(parents=True, exist_ok=True)
        await bot.download(doc, destination=str(COOKIES_FILE))
        await message.answer(
            "✅ <b>Cookies сохранены</b>\n"
            f"<code>{COOKIES_FILE.name}</code>\n"
            f"{DIVIDER}\n"
            "Следующая проверка Profi.ru пойдёт авторизованной."
        )
    except Exception as e:
        logger.error("Не удалось сохранить куки: %s", e, exc_info=True)
        await message.answer(f"⚠️ Ошибка сохранения: {e}")


# ── Скрытая команда /reset_db ───────────────────────────────────


@router.message(Command("reset_db"))
async def on_reset_db(message: Message) -> None:
    if not _is_admin(message.from_user.id if message.from_user else None):
        return
    confirm_kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="✅ Да, очистить", callback_data="reset_db:yes"),
                InlineKeyboardButton(text="❌ Отмена", callback_data="reset_db:no"),
            ]
        ]
    )
    await message.answer(
        "⚠️ <b>Полная очистка БД</b>\n"
        f"{DIVIDER}\n"
        "Будут удалены ВСЕ задачи, история дедупликации и лог действий.\n"
        "Бот заново перепроверит все биржи с чистого листа.\n\n"
        "Подтверди действие:",
        reply_markup=confirm_kb,
    )


@router.callback_query(F.data == "reset_db:no")
async def cb_reset_db_no(callback: CallbackQuery) -> None:
    if not _is_admin(callback.from_user.id if callback.from_user else None):
        return
    await callback.message.edit_text("❌ Отменено")
    await callback.answer()


@router.callback_query(F.data == "reset_db:yes")
async def cb_reset_db_yes(callback: CallbackQuery) -> None:
    if not _is_admin(callback.from_user.id if callback.from_user else None):
        return
    try:
        before = await clear_all()
        await callback.message.edit_text(
            "🧹 <b>БД очищена</b>\n"
            f"{DIVIDER}\n"
            f"Удалено tasks: <b>{before.get('tasks', 0)}</b>\n"
            f"Удалено processed_tasks: <b>{before.get('processed_tasks', 0)}</b>\n"
            f"Удалено actions: <b>{before.get('actions', 0)}</b>\n\n"
            "Бот стартанёт с чистого листа на следующей проверке."
        )
        await callback.answer("Готово")
    except Exception as e:
        logger.exception("reset_db упал")
        await callback.message.edit_text(f"⚠️ Ошибка очистки: {e}")
        await callback.answer()
