"""The check every admin command uses (/stats, /alerttest): only user ids in ADMIN_USER_IDS, only in a
private chat. Anyone else gets no reply, like any unknown command, and the sender's user id is logged at
INFO (that's how an admin finds their own id).
"""

import logging

from telegram import Update
from telegram.constants import ChatType

from config import ADMIN_USER_IDS

logger = logging.getLogger(__name__)


def admin_command(update: Update, command: str) -> bool:
    """True when the update is the command from an admin in a private chat."""
    message, user, chat = update.effective_message, update.effective_user, update.effective_chat
    if not message or not user or not chat:
        return False
    if user.id not in ADMIN_USER_IDS or chat.type != ChatType.PRIVATE:
        logger.info(
            "Ignored /%s from user id %s in a %s chat (it needs a private chat and a user id in ADMIN_USER_IDS).",
            command, user.id, chat.type,
        )
        return False
    return True
