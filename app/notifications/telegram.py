"""Telegram notifications with inline keyboard for decision approvals."""
import structlog
from telegram import Bot, InlineKeyboardButton, InlineKeyboardMarkup

from app.config import settings

logger = structlog.get_logger()


class TelegramNotifier:
    """Sends alerts and decision approval requests via Telegram."""

    def __init__(self):
        self.bot: Bot | None = None
        self.chat_id = settings.telegram_chat_id
        if settings.telegram_bot_token:
            self.bot = Bot(token=settings.telegram_bot_token)

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
        if not self.bot or not self.chat_id:
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

        keyboard = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("✅ APPROVE", callback_data=f"approve:{decision_id}"),
                InlineKeyboardButton("❌ REJECT", callback_data=f"reject:{decision_id}"),
            ],
            [
                InlineKeyboardButton("⏸ SNOOZE 7d", callback_data=f"snooze:{decision_id}"),
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
        # Telegram has a 4096 char limit, split if needed
        if len(report_text) <= 4096:
            await self.send_message(report_text)
        else:
            chunks = [report_text[i:i + 4000] for i in range(0, len(report_text), 4000)]
            for chunk in chunks:
                await self.send_message(chunk)
