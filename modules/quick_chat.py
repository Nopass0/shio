"""Hikka module to create chats quickly"""

import re
from typing import List, Tuple

from hikkatl.tl import functions
from hikkatl.tl.types import Message
from hikkatl.utils import get_display_name

from .. import loader, utils


@loader.tds
class QuickChatMod(loader.Module):
    """Create supergroup chats and optionally invite users with a single command"""

    strings = {
        "name": "QuickChat",
        "no_title": "🚫 <b>Specify a chat title.</b>",
        "creating": "🛠 <b>Creating chat <code>{title}</code>…</b>",
        "created_with_link": "✅ <b>Chat <a href=\"{link}\">{title}</a> is ready.</b>",
        "created_no_link": "✅ <b>Chat <code>{title}</code> is ready.</b>",
        "added": "👥 <b>Invited:</b> {users}",
        "not_found": "⚠️ <b>Could not resolve:</b> {users}",
        "invite_failed": "💢 <b>Telegram refused to invite members:</b> {error}",
        "failed": "💥 <b>Could not create chat:</b> {error}",
        "usage": (
            "ℹ️ <b>Usage:</b> <code>{prefix}quickchat Project name | @user1 @user2</code>\n"
            "Also supports a newline separator or quoted title followed by usernames."
        ),
        "about": "Quick chat created from Hikka via QuickChat module.",
        "welcome": "👋 Chat created from Hikka. Configure it as you like!",
    }

    strings_ru = {
        "_cls_doc": "Создаёт супергруппу и приглашает участников по команде",
        "name": "QuickChat",
        "no_title": "🚫 <b>Укажи название чата.</b>",
        "creating": "🛠 <b>Создаю чат <code>{title}</code>…</b>",
        "created_with_link": "✅ <b>Чат <a href=\"{link}\">{title}</a> готов.</b>",
        "created_no_link": "✅ <b>Чат <code>{title}</code> готов.</b>",
        "added": "👥 <b>Приглашены:</b> {users}",
        "not_found": "⚠️ <b>Не удалось найти:</b> {users}",
        "invite_failed": "💢 <b>Телеграм отказал в приглашении:</b> {error}",
        "failed": "💥 <b>Не удалось создать чат:</b> {error}",
        "usage": (
            "ℹ️ <b>Использование:</b> <code>{prefix}quickchat Название | @user1 @user2</code>\n"
            "Также можно разделить название и участников переводом строки или указать название в кавычках,"
            " а затем перечислить пользователей."
        ),
        "about": "Быстрый чат, созданный модулем QuickChat.",
        "welcome": "👋 Чат создан через Hikka. Настрой всё под себя!",
    }

    async def quickchatcmd(self, message: Message):
        """Create a supergroup chat. Optional participants can be specified after a separator."""

        title, raw_participants = self._extract_command_parts(message)

        if not title:
            await utils.answer(
                message,
                self.strings("usage").format(prefix=utils.escape_html(self.get_prefix())),
            )
            return

        status = await utils.answer(
            message,
            self.strings("creating").format(title=utils.escape_html(title)),
        )

        try:
            result = await self._client(
                functions.channels.CreateChannelRequest(
                    title=title,
                    about=self.strings("about"),
                    megagroup=True,
                )
            )
        except Exception as e:  # noqa: BLE001 - show actual error to the user
            await utils.answer(
                status,
                self.strings("failed").format(error=utils.escape_html(str(e))),
            )
            return

        chat = result.chats[0]
        link = utils.get_entity_url(chat)
        response_lines = [
            (
                self.strings("created_with_link").format(
                    title=utils.escape_html(title),
                    link=link,
                )
                if link
                else self.strings("created_no_link").format(
                    title=utils.escape_html(title)
                )
            )
        ]

        added_users, unresolved, invite_error = await self._try_invite(
            chat, raw_participants
        )

        if added_users:
            response_lines.append(
                self.strings("added").format(users=", ".join(added_users))
            )

        if unresolved:
            response_lines.append(
                self.strings("not_found").format(
                    users=", ".join(map(utils.escape_html, unresolved))
                )
            )

        if invite_error:
            response_lines.append(
                self.strings("invite_failed").format(error=invite_error)
            )

        try:
            await self._client.send_message(chat, self.strings("welcome"))
        except Exception:  # noqa: BLE001 - failing to send welcome should not break command
            pass

        await utils.answer(status, "\n".join(response_lines))

    def _extract_command_parts(self, message: Message) -> Tuple[str, str]:
        raw = utils.get_args_raw(message) or ""
        parts: Tuple[str, str]

        for separator in ("|", "\n", "\r"):
            if separator in raw:
                first, second = raw.split(separator, maxsplit=1)
                parts = (first.strip(), second.strip())
                break
        else:
            args = utils.get_args(message)
            if isinstance(args, list) and args:
                parts = (args[0], " ".join(args[1:]))
            else:
                parts = (raw.strip(), "")

        title, participants = parts
        return title, participants

    async def _try_invite(
        self, chat, raw_participants: str
    ) -> Tuple[List[str], List[str], str]:
        if not raw_participants:
            return [], [], ""

        usernames = self._normalize_participants(raw_participants)
        if not usernames:
            return [], [], ""

        added: List[str] = []
        unresolved: List[str] = []
        input_users = []

        for username in usernames:
            try:
                entity = await self._client.get_entity(username)
            except Exception:  # noqa: BLE001 - continue gathering errors
                unresolved.append(username)
                continue

            try:
                input_entity = await self._client.get_input_entity(entity)
            except Exception:
                unresolved.append(username)
                continue

            added.append(utils.escape_html(get_display_name(entity)))
            input_users.append(input_entity)

        invite_error = ""

        if input_users:
            try:
                await self._client(
                    functions.channels.InviteToChannelRequest(
                        channel=await self._client.get_input_entity(chat),
                        users=input_users,
                    )
                )
            except Exception as e:  # noqa: BLE001 - display specific error text
                invite_error = utils.escape_html(str(e))

        return added, unresolved, invite_error

    def _normalize_participants(self, raw: str) -> List[str]:
        tokens = list(filter(None, re.split(r"[\s,]+", raw.strip())))
        seen = set()
        unique: List[str] = []
        for token in tokens:
            lowered = token.lower()
            if lowered in seen:
                continue
            seen.add(lowered)
            unique.append(token)
        return unique
