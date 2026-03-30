"""Telegram notifications with inline keyboard for decision approvals."""
import asyncio
from datetime import datetime

import structlog

from app.config import settings

logger = structlog.get_logger()

# Lazy imports to avoid requiring python-telegram-bot at import time
_Bot = None
_InlineKeyboardButton = None
_InlineKeyboardMarkup = None
_Application = None
_CallbackQueryHandler = None
_CommandHandler = None


def _load_telegram():
    global _Bot, _InlineKeyboardButton, _InlineKeyboardMarkup, _Application, _CallbackQueryHandler, _CommandHandler
    if _Bot is not None:
        return True
    try:
        from telegram import Bot, InlineKeyboardButton, InlineKeyboardMarkup
        from telegram.ext import Application, CallbackQueryHandler, CommandHandler
        _Bot = Bot
        _InlineKeyboardButton = InlineKeyboardButton
        _InlineKeyboardMarkup = InlineKeyboardMarkup
        _Application = Application
        _CallbackQueryHandler = CallbackQueryHandler
        _CommandHandler = CommandHandler
        return True
    except ImportError:
        logger.warning("python-telegram-bot not installed, Telegram features disabled")
        return False


class TelegramNotifier:
    """Sends alerts and decision approval requests via Telegram."""

    def __init__(self):
        self.bot = None
        self.app = None
        self.chat_id = settings.telegram_chat_id
        self._running = False

        if settings.telegram_bot_token and _load_telegram():
            self.bot = _Bot(token=settings.telegram_bot_token)

    async def start_polling(self):
        """Start listening for callback button presses. Run as background task."""
        if not settings.telegram_bot_token or not _load_telegram():
            logger.warning("Telegram polling not started: no token or missing package")
            return

        self.app = _Application.builder().token(settings.telegram_bot_token).build()

        # Register handlers
        self.app.add_handler(_CallbackQueryHandler(self._handle_callback))
        self.app.add_handler(_CommandHandler("status", self._handle_status_command))

        self._running = True
        logger.info("Telegram callback polling started")

        await self.app.initialize()
        await self.app.start()
        await self.app.updater.start_polling()

    async def stop_polling(self):
        """Stop the Telegram polling."""
        if self.app and self._running:
            self._running = False
            await self.app.updater.stop()
            await self.app.stop()
            await self.app.shutdown()
            logger.info("Telegram callback polling stopped")

    async def _handle_callback(self, update, context):
        """Process APPROVE/REJECT/SNOOZE button presses."""
        query = update.callback_query
        await query.answer()

        data = query.data  # "approve:123", "reject:123", "snooze:123"
        parts = data.split(":")
        if len(parts) != 2:
            await query.edit_message_text("Invalid callback data.")
            return

        action, decision_id_str = parts
        try:
            decision_id = int(decision_id_str)
        except ValueError:
            await query.edit_message_text("Invalid decision ID.")
            return

        # Import here to avoid circular imports
        from app.database import async_session
        from app.models.decision import Decision
        from sqlalchemy import select

        async with async_session() as session:
            result = await session.execute(
                select(Decision).where(Decision.id == decision_id)
            )
            decision = result.scalar_one_or_none()

            if not decision:
                await query.edit_message_text(f"Decision #{decision_id} not found.")
                return

            if decision.status != "PROPOSED":
                await query.edit_message_text(
                    f"Decision #{decision_id} is already {decision.status}."
                )
                return

            user = query.from_user
            username = user.username or user.first_name or "unknown"

            if action == "approve":
                decision.status = "APPROVED"
                decision.approved_by = f"telegram:{username}"
                decision.approved_at = datetime.utcnow()
                await session.commit()
                await query.edit_message_text(
                    f"✅ Decision #{decision_id} APPROVED by @{username}"
                )
                logger.info("Decision approved via Telegram", decision_id=decision_id, by=username)

            elif action == "reject":
                decision.status = "REJECTED"
                decision.approved_by = f"telegram:{username}"
                await session.commit()
                await query.edit_message_text(
                    f"❌ Decision #{decision_id} REJECTED by @{username}"
                )
                logger.info("Decision rejected via Telegram", decision_id=decision_id, by=username)

            elif action == "snooze":
                from datetime import timedelta
                decision.proposed_at = datetime.utcnow() + timedelta(days=7)
                await session.commit()
                await query.edit_message_text(
                    f"⏸ Decision #{decision_id} SNOOZED for 7 days by @{username}"
                )
                logger.info("Decision snoozed via Telegram", decision_id=decision_id, by=username)

            else:
                await query.edit_message_text(f"Unknown action: {action}")

    async def _handle_status_command(self, update, context):
        """Handle /status command - show quick portfolio overview."""
        from app.database import async_session
        from app.models.project import Project
        from sqlalchemy import select

        async with async_session() as session:
            projects = (await session.execute(select(Project))).scalars().all()

        lines = ["📊 *Portfolio Status*\n"]
        for p in projects:
            emoji = {"ACTIVE": "🟢", "PAUSED": "🟡", "KILLED": "🔴"}.get(p.status, "⚪")
            lines.append(f"{emoji} *{p.name}*: {p.status}")

        await update.message.reply_text("\n".join(lines), parse_mode="Markdown")

    async def send_message(self, text: str, parse_mode: str = "Markdown"):
        """Send a simple text message."""
        if not self.bot or not self.chat_id:
            logger.warning("Telegram not configured, skipping notification")
            return
        try:
            await self.bot.send_message(
                chat_id=self.chat_id,
                text=text,
                parse_mode=parse_mode,
            )
        except Exception as e:
            logger.error("Telegram send failed", error=str(e))

    async def send_alert(self, severity: str, project: str, message: str):
        """Send a formatted alert."""
        emoji = {"INFO": "ℹ️", "WARNING": "⚠️", "CRITICAL": "🔴", "EMERGENCY": "🚨"}.get(severity, "📢")
        text = f"{emoji} *{severity}* | {project}\n\n{message}"
        await self.send_message(text)

    async def send_decision_approval(
        self, decision_id: int, project_name: str, decision_type: str,
        confidence: float, reasons: list[str], handles_real_money: bool,
    ):
        """Send a decision requiring human approval with inline keyboard."""
        if not self.bot or not self.chat_id or not _load_telegram():
            logger.warning("Telegram not configured, skipping approval request")
            return

        reasons_text = "\n".join(f"• {r}" for r in reasons)
        safety_note = "\n⚠️ *This project handles real money.*\nOpen positions will be closed before shutdown." if handles_real_money else ""

        text = (
            f"🗳 *DECISION REQUIRES APPROVAL*\n\n"
            f"*Project:* {project_name}\n"
            f"*Decision:* {decision_type}\n"
            f"*Confidence:* {confidence:.0f}%\n\n"
            f"*Reasons:*\n{reasons_text}"
            f"{safety_note}"
        )

        keyboard = _InlineKeyboardMarkup([
            [
                _InlineKeyboardButton("✅ APPROVE", callback_data=f"approve:{decision_id}"),
                _InlineKeyboardButton("❌ REJECT", callback_data=f"reject:{decision_id}"),
            ],
            [
                _InlineKeyboardButton("⏸ SNOOZE 7d", callback_data=f"snooze:{decision_id}"),
            ],
        ])

        try:
            await self.bot.send_message(
                chat_id=self.chat_id,
                text=text,
                parse_mode="Markdown",
                reply_markup=keyboard,
            )
        except Exception as e:
            logger.error("Telegram approval send failed", error=str(e))

    async def send_report(self, report_text: str):
        """Send a portfolio report."""
        if len(report_text) <= 4096:
            await self.send_message(report_text)
        else:
            chunks = [report_text[i:i + 4000] for i in range(0, len(report_text), 4000)]
            for chunk in chunks:
                await self.send_message(chunk)
