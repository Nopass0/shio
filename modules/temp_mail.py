"""Hikka module for managing temporary email inboxes via mail.tm API"""

from __future__ import annotations

from dataclasses import dataclass
import secrets
import string
from typing import Dict, List, Optional

import aiohttp
from hikkatl.tl.types import Message

from .. import loader, utils


API_BASE = "https://api.mail.tm"


def _random_string(length: int) -> str:
    alphabet = string.ascii_lowercase + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(length))


@dataclass
class MailAccount:
    address: str
    password: str
    token: Optional[str] = None

    def as_email(self) -> str:
        return self.address


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
        self._mailbox: Optional[MailAccount] = None
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
            messages = await self._fetch_messages()
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

        message_id = message_id.strip()
        if not message_id:
            await utils.answer(message, self.strings("invalid_id"))
            return

        try:
            data = await self._fetch_message(message_id)
        except Exception as error:  # noqa: BLE001
            await utils.answer(message, self._format_error(error))
            return

        email = utils.escape_html(self._format_mailbox())
        body = (
            data.get("text")
            or data.get("html")
            or data.get("textBody")
            or data.get("htmlBody")
            or ""
        )

        response = [
            self.strings("message_header").format(id=message_id, email=email),
            self.strings("message_fields").format(
                sender=utils.escape_html(self._get_sender(data)),
                subject=utils.escape_html(data.get("subject", "—")),
                date=utils.escape_html(data.get("createdAt", data.get("date", ""))),
            ),
        ]

        if body:
            response.append(
                self.strings("message_body").format(
                    body=utils.escape_html(body.strip())
                )
            )

        await utils.answer(message, "\n".join(response))

    async def _generate_mailbox(self) -> MailAccount:
        domain = await self._choose_domain()

        for _ in range(5):
            login = _random_string(10)
            password = _random_string(16)
            address = f"{login}@{domain}"

            try:
                await self._request_json(
                    "POST",
                    "/accounts",
                    json={"address": address, "password": password},
                )
            except aiohttp.ClientResponseError as error:
                if error.status == 422:
                    continue
                raise
            token = await self._obtain_token(address, password)
            return MailAccount(address=address, password=password, token=token)

        raise RuntimeError("failed to create mailbox")

    async def _fetch_messages(self) -> List[Dict]:
        headers = await self._auth_headers()
        try:
            data = await self._request_json("GET", "/messages", headers=headers)
        except aiohttp.ClientResponseError as error:
            if error.status != 401:
                raise
            self._reset_token()
            headers = await self._auth_headers()
            data = await self._request_json("GET", "/messages", headers=headers)

        if not isinstance(data, dict):
            raise RuntimeError("unexpected inbox response")

        items = data.get("hydra:member", [])
        if not isinstance(items, list):
            raise RuntimeError("unexpected inbox response")

        messages: List[Dict] = []
        for item in items:
            if not isinstance(item, dict):
                continue

            messages.append(
                {
                    "id": item.get("id", ""),
                    "from": self._get_sender(item),
                    "subject": item.get("subject", ""),
                    "date": item.get("createdAt", ""),
                }
            )

        return messages

    async def _fetch_message(self, message_id: str) -> Dict:
        headers = await self._auth_headers()
        try:
            data = await self._request_json(
                "GET", f"/messages/{message_id}", headers=headers
            )
        except aiohttp.ClientResponseError as error:
            if error.status != 401:
                raise
            self._reset_token()
            headers = await self._auth_headers()
            data = await self._request_json(
                "GET", f"/messages/{message_id}", headers=headers
            )

        if not isinstance(data, dict):
            raise RuntimeError("unexpected message response")
        return data

    async def _request_json(
        self,
        method: str,
        path: str,
        *,
        params: Optional[Dict[str, object]] = None,
        json: Optional[Dict[str, object]] = None,
        headers: Optional[Dict[str, str]] = None,
    ) -> object:
        url = f"{API_BASE}{path}"
        async with aiohttp.ClientSession(timeout=self._timeout) as session:
            async with session.request(
                method, url, params=params, json=json, headers=headers
            ) as response:
                response.raise_for_status()
                return await response.json(content_type=None)

    async def _choose_domain(self) -> str:
        data = await self._request_json("GET", "/domains")
        if not isinstance(data, dict):
            raise RuntimeError("unexpected domains response")

        items = data.get("hydra:member", [])
        if not isinstance(items, list) or not items:
            raise RuntimeError("no domains available")

        domain = secrets.choice(items)
        if isinstance(domain, dict):
            value = domain.get("domain")
        else:
            value = None

        if not isinstance(value, str) or not value:
            raise RuntimeError("invalid domain received")

        return value

    async def _obtain_token(self, address: str, password: str) -> str:
        data = await self._request_json(
            "POST",
            "/token",
            json={"address": address, "password": password},
        )

        if not isinstance(data, dict):
            raise RuntimeError("unexpected token response")

        token = data.get("token")
        if not isinstance(token, str) or not token:
            raise RuntimeError("missing token in response")

        return token

    async def _auth_headers(self) -> Dict[str, str]:
        mailbox = self._mailbox
        if not mailbox:
            raise RuntimeError("mailbox not initialised")

        token = mailbox.token
        if not token:
            token = await self._obtain_token(mailbox.address, mailbox.password)
            mailbox.token = token

        return {"Authorization": f"Bearer {token}"}

    def _reset_token(self) -> None:
        if self._mailbox:
            self._mailbox.token = None

    def _get_sender(self, data: Dict) -> str:
        sender = data.get("from")
        if isinstance(sender, dict):
            value = sender.get("address") or sender.get("email")
            if isinstance(value, str) and value:
                return value
        if isinstance(sender, str):
            return sender
        return "?"

    def _format_mailbox(self) -> str:
        if not self._mailbox:
            return ""
        return self._mailbox.as_email()

    def _format_error(self, error: BaseException) -> str:
        return self.strings("fetch_error").format(
            error=utils.escape_html(str(error))
        )

