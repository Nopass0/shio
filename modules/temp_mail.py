"""Hikka module for managing temporary email inboxes via 1secmail"""

from typing import Dict, List, Optional, Tuple

import aiohttp
from hikkatl.tl.types import Message

from .. import loader, utils


API_URL = "https://www.1secmail.com/api/v1/"


@loader.tds
class TempMailMod(loader.Module):
    """Create disposable mailboxes and read their messages"""

    strings = {
        "name": "TempMail",
        "new_mailbox": "📬 <b>Temporary mailbox created:</b> <code>{email}</code>",
        "current_mailbox": "📮 <b>Current mailbox:</b> <code>{email}</code>",
        "no_mailbox": "🚫 <b>No mailbox yet.</b> Use <code>{prefix}tempmail new</code>.",
        "invalid_id": "❓ <b>Specify a valid message ID.</b>",
        "fetch_error": "💥 <b>Failed to contact temporary mail service:</b> {error}",
        "inbox_empty": "📭 <b>No messages in <code>{email}</code> yet.</b>",
        "inbox_header": "📨 <b>Inbox for <code>{email}</code>:</b>",
        "inbox_line": "• <code>{id}</code> — <b>{sender}</b>: {subject} ({date})",
        "message_header": "✉️ <b>Message #{id} for <code>{email}</code>:</b>",
        "message_fields": "<b>From:</b> {sender}\n<b>Subject:</b> {subject}\n<b>Date:</b> {date}",
        "message_body": "\n\n<code>{body}</code>",
        "usage": (
            "ℹ️ <b>Usage:</b> <code>{prefix}tempmail [new|inbox|read &lt;id&gt;]</code>\n"
            "Without arguments shows current mailbox or creates a new one."
        ),
    }

    strings_ru = {
        "_cls_doc": "Создаёт временный почтовый ящик и позволяет читать письма",
        "name": "TempMail",
        "new_mailbox": "📬 <b>Создан временный ящик:</b> <code>{email}</code>",
        "current_mailbox": "📮 <b>Текущий ящик:</b> <code>{email}</code>",
        "no_mailbox": "🚫 <b>Ящик ещё не создан.</b> Используй <code>{prefix}tempmail new</code>.",
        "invalid_id": "❓ <b>Укажи корректный ID письма.</b>",
        "fetch_error": "💥 <b>Не удалось обратиться к сервису временной почты:</b> {error}",
        "inbox_empty": "📭 <b>Нет писем в <code>{email}</code>.</b>",
        "inbox_header": "📨 <b>Входящие для <code>{email}</code>:</b>",
        "inbox_line": "• <code>{id}</code> — <b>{sender}</b>: {subject} ({date})",
        "message_header": "✉️ <b>Письмо №{id} для <code>{email}</code>:</b>",
        "message_fields": "<b>От:</b> {sender}\n<b>Тема:</b> {subject}\n<b>Дата:</b> {date}",
        "message_body": "\n\n<code>{body}</code>",
        "usage": (
            "ℹ️ <b>Использование:</b> <code>{prefix}tempmail [new|inbox|read &lt;id&gt;]</code>\n"
            "Без аргументов показывает текущий ящик или создаёт новый."
        ),
    }

    def __init__(self) -> None:
        self._mailbox: Optional[Tuple[str, str]] = None
        self._timeout = aiohttp.ClientTimeout(total=10)

    async def tempmailcmd(self, message: Message):
        """Manage temporary mailbox. Use no args to show or new to regenerate"""

        args = utils.get_args(message)

        if not args:
            if self._mailbox:
                await utils.answer(
                    message,
                    self.strings("current_mailbox").format(
                        email=utils.escape_html(self._format_mailbox())
                    ),
                )
                return

            await self._create_mailbox(message)
            return

        command = args[0].lower()

        if command == "new":
            await self._create_mailbox(message)
        elif command in {"inbox", "list"}:
            await self._show_inbox(message)
        elif command == "read" and len(args) >= 2:
            await self._read_message(message, args[1])
        else:
            await utils.answer(
                message,
                self.strings("usage").format(
                    prefix=utils.escape_html(self.get_prefix())
                ),
            )

    async def _create_mailbox(self, message: Message) -> None:
        try:
            mailbox = await self._generate_mailbox()
        except Exception as error:  # noqa: BLE001
            await utils.answer(
                message,
                self._format_error(error),
            )
            return

        self._mailbox = mailbox
        await utils.answer(
            message,
            self.strings("new_mailbox").format(
                email=utils.escape_html(self._format_mailbox())
            ),
        )

    async def _show_inbox(self, message: Message) -> None:
        mailbox = self._mailbox
        if not mailbox:
            await utils.answer(
                message,
                self.strings("no_mailbox").format(
                    prefix=utils.escape_html(self.get_prefix())
                ),
            )
            return

        try:
            messages = await self._fetch_messages(*mailbox)
        except Exception as error:  # noqa: BLE001
            await utils.answer(message, self._format_error(error))
            return

        email = utils.escape_html(self._format_mailbox())

        if not messages:
            await utils.answer(
                message,
                self.strings("inbox_empty").format(email=email),
            )
            return

        lines = [self.strings("inbox_header").format(email=email)]
        for item in messages:
            lines.append(
                self.strings("inbox_line").format(
                    id=item.get("id", "?"),
                    sender=utils.escape_html(item.get("from", "?")),
                    subject=utils.escape_html(item.get("subject", "—")),
                    date=utils.escape_html(item.get("date", "")),
                )
            )

        await utils.answer(message, "\n".join(lines))

    async def _read_message(self, message: Message, message_id: str) -> None:
        mailbox = self._mailbox
        if not mailbox:
            await utils.answer(
                message,
                self.strings("no_mailbox").format(
                    prefix=utils.escape_html(self.get_prefix())
                ),
            )
            return

        if not message_id.isdigit():
            await utils.answer(message, self.strings("invalid_id"))
            return

        try:
            data = await self._fetch_message(*mailbox, int(message_id))
        except Exception as error:  # noqa: BLE001
            await utils.answer(message, self._format_error(error))
            return

        email = utils.escape_html(self._format_mailbox())
        body = data.get("textBody") or data.get("htmlBody") or ""

        response = [
            self.strings("message_header").format(id=message_id, email=email),
            self.strings("message_fields").format(
                sender=utils.escape_html(data.get("from", "?")),
                subject=utils.escape_html(data.get("subject", "—")),
                date=utils.escape_html(data.get("date", "")),
            ),
        ]

        if body:
            response.append(
                self.strings("message_body").format(
                    body=utils.escape_html(body.strip())
                )
            )

        await utils.answer(message, "\n".join(response))

    async def _generate_mailbox(self) -> Tuple[str, str]:
        data = await self._get_json({"action": "genRandomMailbox", "count": 1})
        if not isinstance(data, list) or not data:
            raise RuntimeError("empty response")

        email = data[0]
        if "@" not in email:
            raise RuntimeError("invalid email returned")

        login, domain = email.split("@", maxsplit=1)
        return login, domain

    async def _fetch_messages(self, login: str, domain: str) -> List[Dict]:
        data = await self._get_json(
            {"action": "getMessages", "login": login, "domain": domain}
        )
        if not isinstance(data, list):
            raise RuntimeError("unexpected inbox response")
        return data

    async def _fetch_message(self, login: str, domain: str, message_id: int) -> Dict:
        data = await self._get_json(
            {
                "action": "readMessage",
                "login": login,
                "domain": domain,
                "id": message_id,
            }
        )
        if not isinstance(data, dict):
            raise RuntimeError("unexpected message response")
        return data

    async def _get_json(self, params: Dict[str, object]) -> object:
        async with aiohttp.ClientSession(timeout=self._timeout) as session:
            async with session.get(API_URL, params=params) as response:
                response.raise_for_status()
                return await response.json(content_type=None)

    def _format_mailbox(self) -> str:
        if not self._mailbox:
            return ""
        login, domain = self._mailbox
        return f"{login}@{domain}"

    def _format_error(self, error: BaseException) -> str:
        return self.strings("fetch_error").format(
            error=utils.escape_html(str(error))
        )

