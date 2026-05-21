import html
import logging
from typing import Literal

from aiogram import Bot, F, Router
from aiogram.types import CallbackQuery

from database.db_utils import (
    ACTION_HIDE,
    ACTION_RESPOND,
    ACTION_RETONE,
    STATUS_HIDDEN,
    get_task,
    log_action,
    update_status,
)
from utils.ai_assistant import generate_pitch
from utils.keyboards import task_keyboard, tone_keyboard

logger = logging.getLogger(__name__)

router = Router(name="tasks")

SOURCE_ICON = {"Kwork": "🟠", "YouDo": "🔴", "Profi.ru": "🟢", "FL.ru": "🔵"}

Style = Literal["short", "confident", "balanced"]

DIVIDER = "─────────────────────────"


def _score_label(score: int) -> tuple[str, str]:
    """Возвращает (эмодзи, текст-метку)."""
    if score >= 90:
        return "⭐", "ИДЕАЛЬНО"
    if score >= 80:
        return "🚀", "ОТЛИЧНО"
    if score >= 60:
        return "🟢", "ПОДХОДИТ"
    if score >= 40:
        return "🟡", "НА ГРАНИ"
    return "🔴", "ПРОПУЩЕНО"


def _format_budget(amount: int) -> str:
    if not amount:
        return "не указан"
    return f"{amount:,} ₽".replace(",", " ")


def _format_card(task: dict) -> str:
    icon = SOURCE_ICON.get(task["source"], "🆕")
    score = int(task["score"])
    emoji, label = _score_label(score)
    budget = _format_budget(task["budget"])
    title = html.escape(task["title"])
    reason = html.escape(task["score_reason"] or "")
    desc = html.escape((task["description"] or "").strip())
    if len(desc) > 500:
        desc = desc[:500] + "…"

    parts = [
        f"{emoji} <b>{label} · {score}/100</b>",
        f"{icon} <b>{task['source']}</b>  ·  💰 {budget}",
        DIVIDER,
        f"<b>{title}</b>",
    ]
    if desc:
        parts.append(f"\n📋 {desc}")
    if reason:
        parts.append(f"\n🎯 <i>{reason}</i>")
    return "\n".join(parts)


async def send_task_card(bot: Bot, admin_id: int, task_id: int) -> None:
    """Отправляет карточку задачи администратору. Используется из services.monitor."""
    task = await get_task(task_id)
    if not task:
        logger.warning("send_task_card: задача %d не найдена", task_id)
        return
    await bot.send_message(
        admin_id,
        _format_card(task),
        reply_markup=task_keyboard(task_id, task["url"]),
        disable_web_page_preview=True,
    )


# ── Хендлеры кнопок ─────────────────────────────────────────────


@router.callback_query(F.data.startswith("pitch:"))
async def cb_pitch(callback: CallbackQuery) -> None:
    try:
        _, task_id_str, style = callback.data.split(":", 2)
        task_id = int(task_id_str)
    except (ValueError, AttributeError):
        await callback.answer("Неверный формат кнопки", show_alert=True)
        return

    task = await get_task(task_id)
    if not task:
        await callback.answer("Задача не найдена", show_alert=True)
        return

    await callback.answer("Генерирую отклик…")
    pitch = await generate_pitch(
        task["title"], task.get("description", ""), style, task.get("budget", 0)
    )

    header = f"✍️ Отклик ({style}) для «{task['title'][:60]}»:"
    await callback.message.answer(f"{header}\n\n{pitch}")
    await log_action(task_id, ACTION_RESPOND, {"style": style, "len": len(pitch)})


@router.callback_query(F.data.startswith("tone:"))
async def cb_tone(callback: CallbackQuery) -> None:
    try:
        task_id = int(callback.data.split(":", 1)[1])
    except ValueError:
        await callback.answer("Неверный формат", show_alert=True)
        return
    await callback.message.edit_reply_markup(reply_markup=tone_keyboard(task_id))
    await callback.answer()


@router.callback_query(F.data.startswith("back:"))
async def cb_back(callback: CallbackQuery) -> None:
    try:
        task_id = int(callback.data.split(":", 1)[1])
    except ValueError:
        await callback.answer("Неверный формат", show_alert=True)
        return
    task = await get_task(task_id)
    if not task:
        await callback.answer("Задача не найдена", show_alert=True)
        return
    await callback.message.edit_reply_markup(
        reply_markup=task_keyboard(task_id, task["url"])
    )
    await log_action(task_id, ACTION_RETONE)
    await callback.answer()


@router.callback_query(F.data.startswith("hide:"))
async def cb_hide(callback: CallbackQuery) -> None:
    try:
        task_id = int(callback.data.split(":", 1)[1])
    except ValueError:
        await callback.answer("Неверный формат", show_alert=True)
        return
    await log_action(task_id, ACTION_HIDE)
    await update_status(task_id, STATUS_HIDDEN)
    try:
        await callback.message.delete()
    except Exception:
        pass
    await callback.answer("Скрыто")
