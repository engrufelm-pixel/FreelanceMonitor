from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup


def task_keyboard(task_id: int, url: str) -> InlineKeyboardMarkup:
    """Основная клавиатура под карточкой задачи."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="🔗 Открыть", url=url),
                InlineKeyboardButton(text="✍️ Сгенерировать отклик", callback_data=f"pitch:{task_id}:balanced"),
            ],
            [
                InlineKeyboardButton(text="🔄 Тональность", callback_data=f"tone:{task_id}"),
                InlineKeyboardButton(text="🗑 Скрыть", callback_data=f"hide:{task_id}"),
            ],
        ]
    )


def tone_keyboard(task_id: int) -> InlineKeyboardMarkup:
    """Подменю выбора стиля отклика."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="Короче", callback_data=f"pitch:{task_id}:short"),
                InlineKeyboardButton(text="Увереннее", callback_data=f"pitch:{task_id}:confident"),
            ],
            [
                InlineKeyboardButton(text="← Назад", callback_data=f"back:{task_id}"),
            ],
        ]
    )
