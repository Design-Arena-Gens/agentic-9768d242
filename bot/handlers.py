from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Optional

from telegram import InlineQueryResultArticle, InputTextMessageContent, Update
from telegram.constants import ParseMode
from telegram.ext import (
    AIORateLimiter,
    Application,
    ApplicationBuilder,
    CallbackContext,
    CommandHandler,
    ContextTypes,
    InlineQueryHandler,
    MessageHandler,
    filters,
)

from .checker import CheckerResult, CheckerService
from .config import BotSettings
from .storage import Storage
from .utils import chunk_text, escape, format_bold

logger = logging.getLogger(__name__)


class BotController:
    def __init__(
        self,
        settings: BotSettings,
        storage: Storage,
        checker: CheckerService,
    ) -> None:
        self._settings = settings
        self._storage = storage
        self._checker = checker
        self._details_cache: Optional[str] = None
        self._details_mtime: Optional[float] = None
        self._start_time = datetime.now(timezone.utc)

    async def start(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not update.effective_user:
            return
        if not await self._register_user(update):
            return

        message = await self._load_bot_details()
        await update.message.reply_text(
            message,
            parse_mode=ParseMode.HTML,
            disable_web_page_preview=True,
        )

    async def help(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        await self.start(update, context)

    async def ping(self, update: Update, _: ContextTypes.DEFAULT_TYPE) -> None:
        if not update.effective_user:
            return
        if await self._storage.is_user_banned(update.effective_user.id):
            return
        await update.message.reply_text("✅ Bot is responsive and ready.")

    async def check(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not update.effective_user or not update.message:
            return
        if not await self._register_user(update):
            return

        query = self._extract_query(update, context)
        if not query:
            await update.message.reply_text(
                "Please provide text to check, e.g. `/check https://example.com`.",
                parse_mode=ParseMode.MARKDOWN,
            )
            return

        result = await self._execute_check(update.effective_user.id, query)
        for chunk in chunk_text(result.to_message()):
            await update.message.reply_text(
                chunk, parse_mode=ParseMode.HTML, disable_web_page_preview=True
            )

    async def handle_text(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not update.effective_user or not update.message:
            return
        if update.message.text.startswith("/"):
            return
        if not await self._register_user(update):
            return
        query = update.message.text.strip()
        if not query:
            return
        result = await self._execute_check(update.effective_user.id, query)
        for chunk in chunk_text(result.to_message()):
            await update.message.reply_text(
                chunk, parse_mode=ParseMode.HTML, disable_web_page_preview=True
            )

    async def inline_query(self, update: Update, _: ContextTypes.DEFAULT_TYPE) -> None:
        if not update.inline_query:
            return
        query = update.inline_query.query.strip()
        user = update.inline_query.from_user
        if user and await self._storage.is_user_banned(user.id):
            await update.inline_query.answer([], switch_pm_text="Access denied", switch_pm_parameter="start", cache_time=0)
            return
        if not query:
            await update.inline_query.answer([], cache_time=2)
            return
        result = await self._checker.analyze(query)
        await update.inline_query.answer(
            [
                InlineQueryResultArticle(
                    id="checker",
                    title=f"{result.status.upper()}: {result.summary}",
                    input_message_content=InputTextMessageContent(
                        result.to_message(), parse_mode=ParseMode.HTML
                    ),
                    description=result.summary,
                )
            ],
            cache_time=0,
        )

    async def stats(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not await self._ensure_admin(update):
            return
        stats = await self._storage.get_stats()
        uptime = datetime.now(timezone.utc) - self._start_time
        minutes, seconds = divmod(int(uptime.total_seconds()), 60)
        hours, minutes = divmod(minutes, 60)
        days, hours = divmod(hours, 24)
        uptime_str = f"{days}d {hours}h {minutes}m {seconds}s"
        sections = [
            format_bold("Live Stats"),
            f"Users: {stats['total_users']}",
            f"Checks: {stats['total_checks']}",
            f"Banned: {stats['banned_users']}",
            f"Uptime: {uptime_str}",
        ]
        await update.message.reply_text("\n".join(sections), parse_mode=ParseMode.HTML)

    async def recent(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not await self._ensure_admin(update):
            return
        limit = 10
        if context.args:
            try:
                limit = max(1, min(50, int(context.args[0])))
            except ValueError:
                pass
        checks = await self._storage.get_recent_checks(limit=limit)
        if not checks:
            await update.message.reply_text("No checks have been recorded yet.")
            return
        messages = []
        for entry in checks:
            user = f"{entry['username'] or 'unknown'} ({entry['user_id']})"
            messages.append(
                "\n".join(
                    [
                        format_bold(f"Check #{entry['id']}"),
                        f"User: {escape(user)}",
                        f"Query: {escape(entry['query'])}",
                        f"Status: {escape(entry['status'])}",
                        f"Summary: {escape(entry['summary'])}",
                        f"At: {escape(entry['created_at'])}",
                    ]
                )
            )
        for chunk in chunk_text("\n\n".join(messages)):
            await update.message.reply_text(chunk, parse_mode=ParseMode.HTML)

    async def broadcast(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not await self._ensure_admin(update):
            return

        if update.message.reply_to_message:
            text_to_broadcast = update.message.reply_to_message.text_html
        else:
            text_to_broadcast = " ".join(context.args)

        if not text_to_broadcast:
            await update.message.reply_text(
                "Reply to a message or provide text with the command to broadcast."
            )
            return

        stats = await self._storage.get_stats()
        total = stats["total_users"]
        success = 0
        failure = 0

        application: Application = context.application
        for user_id in await self._iter_user_ids():
            try:
                await application.bot.send_message(
                    chat_id=user_id,
                    text=text_to_broadcast,
                    parse_mode=ParseMode.HTML,
                    disable_web_page_preview=True,
                )
                success += 1
            except Exception as exc:  # noqa: BLE001
                failure += 1
                logger.warning("Broadcast to %s failed: %s", user_id, exc)
                await asyncio.sleep(0.05)
            else:
                await asyncio.sleep(0.05)

        await update.message.reply_text(
            f"Broadcast finished.\nSent: {success}\nFailed: {failure}\nTotal users: {total}"
        )

    async def ban(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not await self._ensure_admin(update):
            return
        target_id = self._resolve_target_id(update, context)
        if target_id is None:
            await update.message.reply_text(
                "Provide a user ID or reply to a user to ban."
            )
            return
        changed = await self._storage.set_user_ban(target_id, True)
        if changed:
            await update.message.reply_text(f"User {target_id} banned.")
        else:
            await update.message.reply_text("User not found.")

    async def unban(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not await self._ensure_admin(update):
            return
        target_id = self._resolve_target_id(update, context)
        if target_id is None:
            await update.message.reply_text(
                "Provide a user ID or reply to a user to unban."
            )
            return
        changed = await self._storage.set_user_ban(target_id, False)
        if changed:
            await update.message.reply_text(f"User {target_id} unbanned.")
        else:
            await update.message.reply_text("User not found.")

    async def banned(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not await self._ensure_admin(update):
            return
        banned_users = await self._storage.list_banned_users()
        if not banned_users:
            await update.message.reply_text("No banned users.")
            return
        message = "\n\n".join(
            [
                "\n".join(
                    [
                        format_bold(str(entry["user_id"])),
                        f"Username: {escape(entry['username'] or 'unknown')}",
                        f"First seen: {escape(entry['first_seen'])}",
                        f"Last seen: {escape(entry['last_seen'])}",
                    ]
                )
                for entry in banned_users
            ]
        )
        for chunk in chunk_text(message):
            await update.message.reply_text(chunk, parse_mode=ParseMode.HTML)

    async def reload_details(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        if not await self._ensure_admin(update):
            return
        self._details_cache = None
        self._details_mtime = None
        await update.message.reply_text("Bot details cache cleared.")

    async def _load_bot_details(self) -> str:
        path = self._settings.bot_details_path
        try:
            mtime = path.stat().st_mtime
        except FileNotFoundError:
            default_message = (
                "Welcome! Update the bot_details.txt file to customize this text."
            )
            return default_message

        if self._details_cache is not None and self._details_mtime == mtime:
            return self._details_cache

        content = await asyncio.to_thread(path.read_text, encoding="utf-8")
        content = content.strip() or "Welcome!"
        self._details_cache = escape(content)
        self._details_mtime = mtime
        return self._details_cache

    async def _iter_user_ids(self):
        return await self._storage.get_active_user_ids()

    async def _register_user(self, update: Update) -> bool:
        user = update.effective_user
        assert user is not None
        if await self._storage.is_user_banned(user.id):
            if update.message:
                await update.message.reply_text(
                    "Access denied. Contact an administrator for assistance."
                )
            return False
        await self._storage.add_or_update_user(user.id, user.username)
        return True

    async def _ensure_admin(self, update: Update) -> bool:
        user = update.effective_user
        if not user or user.id not in self._settings.admin_ids:
            if update.message:
                await update.message.reply_text("This command is for admins only.")
            return False
        return True

    async def _execute_check(self, user_id: int, query: str) -> CheckerResult:
        result = await self._checker.analyze(query)
        await self._storage.increment_check_count(user_id)
        await self._storage.record_check(
            user_id=user_id,
            query=query,
            status=result.status,
            summary=result.summary,
            raw_response=result.to_message(),
        )
        return result

    def _extract_query(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> str:
        if context.args:
            return " ".join(context.args)
        if update.message and update.message.reply_to_message:
            text = update.message.reply_to_message.text
            if text:
                return text.strip()
        return ""

    def _resolve_target_id(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> Optional[int]:
        if update.message and update.message.reply_to_message:
            if update.message.reply_to_message.from_user:
                return update.message.reply_to_message.from_user.id
        if context.args:
            try:
                return int(context.args[0])
            except ValueError:
                return None
        return None


def build_application(settings: BotSettings) -> Application:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(name)s | %(levelname)s | %(message)s",
    )
    storage = Storage(settings.database_path)
    checker = CheckerService(timeout=settings.request_timeout)
    controller = BotController(settings, storage, checker)

    application = (
        ApplicationBuilder()
        .token(settings.bot_token)
        .rate_limiter(AIORateLimiter(max_retries=2))
        .parse_mode(ParseMode.HTML)
        .build()
    )

    async def on_startup(app: Application) -> None:
        await storage.initialize()
        logger.info("Database ready at %s", settings.database_path)

    application.post_init = on_startup

    application.add_handler(CommandHandler("start", controller.start))
    application.add_handler(CommandHandler("help", controller.help))
    application.add_handler(CommandHandler("ping", controller.ping))
    application.add_handler(CommandHandler("check", controller.check))
    application.add_handler(CommandHandler("stats", controller.stats))
    application.add_handler(CommandHandler("recent", controller.recent))
    application.add_handler(CommandHandler("broadcast", controller.broadcast))
    application.add_handler(CommandHandler("ban", controller.ban))
    application.add_handler(CommandHandler("unban", controller.unban))
    application.add_handler(CommandHandler("banned", controller.banned))
    application.add_handler(CommandHandler("reload", controller.reload_details))

    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, controller.handle_text))
    application.add_handler(InlineQueryHandler(controller.inline_query))

    application.add_error_handler(_handle_error)
    application.job_queue.run_repeating(
        _heartbeat_job(controller), interval=600, first=600
    )
    return application


def _heartbeat_job(controller: BotController):
    async def job(context: CallbackContext) -> None:
        stats = await controller._storage.get_stats()  # noqa: SLF001
        logger.info(
            "Heartbeat | users=%s checks=%s banned=%s",
            stats["total_users"],
            stats["total_checks"],
            stats["banned_users"],
        )

    return job


async def _handle_error(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.error("Update %s caused error %s", update, context.error, exc_info=context.error)
    if isinstance(update, Update) and update.effective_user and update.effective_chat:
        try:
            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text="An unexpected error occurred. Please retry in a moment.",
            )
        except Exception:  # noqa: BLE001
            logger.exception("Failed to notify user about the error.")
