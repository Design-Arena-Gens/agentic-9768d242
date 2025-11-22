from __future__ import annotations

import logging

from dotenv import load_dotenv

from bot.config import load_settings
from bot.handlers import build_application


def main() -> None:
    load_dotenv()
    settings = load_settings()
    application = build_application(settings)
    logging.info("Starting bot with admins: %s", settings.admin_ids)
    application.run_polling()


if __name__ == "__main__":
    main()
