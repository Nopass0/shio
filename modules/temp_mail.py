"""Hikka module for managing temporary email inboxes via mail.tm API"""

from __future__ import annotations

import asyncio
import contextlib
from dataclasses import dataclass
import secrets
import string
from typing import Dict, List, Optional, Set

import aiohttp
from hikkatl.tl import functions
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
        "chat_created": "💬 <b>Chat <a href=\"{link}\">{title}</a> created for mailbox.</b>",
        "chat_created_no_link": "💬 <b>Chat <code>{title}</code> created for mailbox.</b>",
        "chat_failed": "💢 <b>Failed to create mailbox chat:</b> {error}",
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
        "chat_about": "Temporary mailbox chat created via TempMail module.",
        "chat_welcome": (
            "👋 This chat was created for <code>{email}</code>. "
            "New incoming messages will appear here automatically."
        ),
        "chat_email": (
            "✉️ <b>New email for <code>{email}</code></b>\n"
            "<b>From:</b> {sender}\n"
            "<b>Subject:</b> {subject}\n"
            "<b>Date:</b> {date}{body}"
        ),
        "chat_email_body": "\n\n<code>{body}</code>",
        "usage": (
            "ℹ️ <b>Usage:</b> <code>{prefix}tempmail [new|inbox|read &lt;id&gt;]</code>\n"
            "Without arguments shows current mailbox or creates a new one."
        ),
    }

    strings_ru = {
        "_cls_doc": "Создаёт временный почтовый ящик и позволяет читать письма",
        "name": "TempMail",
        "new_mailbox": "📬 <b>Создан временный ящик:</b> <code>{email}</code>",
        "chat_created": "💬 <b>Создан чат <a href=\"{link}\">{title}</a> для ящика.</b>",
        "chat_created_no_link": "💬 <b>Создан чат <code>{title}</code> для ящика.</b>",
        "chat_failed": "💢 <b>Не удалось создать чат для ящика:</b> {error}",
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
        "chat_about": "Чат для временной почты, созданный модулем TempMail.",
        "chat_welcome": (
            "👋 Чат создан для <code>{email}</code>. "
            "Новые входящие письма будут появляться здесь автоматически."
        ),
        "chat_email": (
            "✉️ <b>Новое письмо для <code>{email}</code></b>\n"
            "<b>От:</b> {sender}\n"
            "<b>Тема:</b> {subject}\n"
            "<b>Дата:</b> {date}{body}"
        ),
        "chat_email_body": "\n\n<code>{body}</code>",
        "usage": (
            "ℹ️ <b>Использование:</b> <code>{prefix}tempmail [new|inbox|read &lt;id&gt;]</code>\n"
            "Без аргументов показывает текущий ящик или создаёт новый."
        ),
    }

    def __init__(self) -> None:
        self._mailbox: Optional[MailAccount] = None
        self._timeout = aiohttp.ClientTimeout(total=10)
        self._mail_chat = None
        self._mail_chat_peer = None
        self._poll_task: Optional[asyncio.Task] = None
        self._known_message_ids: Set[str] = set()
        self._poll_interval = 30
        self._poll_error_delay = 10

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

        await self._stop_polling()
        self._mailbox = mailbox
        self._mail_chat = None
        self._mail_chat_peer = None
        self._known_message_ids.clear()

        response_lines = [
            self.strings("new_mailbox").format(
                email=utils.escape_html(self._format_mailbox())
            )
        ]

        chat_line = await self._create_mail_chat(mailbox)
        if chat_line:
            response_lines.append(chat_line)

        await utils.answer(message, "\n".join(response_lines))

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

    async def _create_mail_chat(self, mailbox: MailAccount) -> str:
        title = mailbox.as_email()

        try:
            result = await self._client(
                functions.channels.CreateChannelRequest(
                    title=title,
                    about=self.strings("chat_about"),
                    megagroup=True,
                )
            )
        except Exception as error:  # noqa: BLE001
            return self.strings("chat_failed").format(
                error=utils.escape_html(str(error))
            )

        if not result.chats:
            return self.strings("chat_failed").format(
                error=utils.escape_html("no chat returned")
            )

        chat = result.chats[0]
        self._mail_chat = chat

        try:
            self._mail_chat_peer = await self._client.get_input_entity(chat)
        except Exception:  # noqa: BLE001
            self._mail_chat_peer = chat

        link = utils.get_entity_url(chat)

        try:
            await self._client.send_message(
                self._mail_chat_peer,
                self.strings("chat_welcome").format(
                    email=utils.escape_html(mailbox.as_email())
                ),
            )
        except Exception:  # noqa: BLE001
            pass

        await self._initialize_known_messages()
        self._start_polling()

        if link:
            return self.strings("chat_created").format(
                title=utils.escape_html(title),
                link=link,
            )
        return self.strings("chat_created_no_link").format(
            title=utils.escape_html(title)
        )

    async def _initialize_known_messages(self) -> None:
        try:
            messages = await self._fetch_messages()
        except Exception:  # noqa: BLE001
            self._known_message_ids.clear()
            return

        self._known_message_ids = {
            item.get("id")
            for item in messages
            if isinstance(item, dict)
            and isinstance(item.get("id"), str)
            and item.get("id")
        }

    def _start_polling(self) -> None:
        if self._poll_task or not self._mailbox or not self._mail_chat_peer:
            return

        loop = asyncio.get_running_loop()
        self._poll_task = loop.create_task(self._poll_loop())

    async def _stop_polling(self) -> None:
        task = self._poll_task
        if not task:
            return

        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task

        self._poll_task = None

    async def _poll_loop(self) -> None:
        current_task = asyncio.current_task()
        try:
            while self._mailbox and self._mail_chat_peer:
                await self._poll_once()
                await asyncio.sleep(self._poll_interval)
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001
            await asyncio.sleep(self._poll_error_delay)
            if self._mailbox and self._mail_chat_peer:
                loop = asyncio.get_running_loop()
                self._poll_task = loop.create_task(self._poll_loop())
        finally:
            if self._poll_task is current_task:
                self._poll_task = None

    async def _poll_once(self) -> None:
        messages = await self._fetch_messages()
        for item in messages:
            message_id = item.get("id")
            if not isinstance(message_id, str) or not message_id:
                continue
            if message_id in self._known_message_ids:
                continue

            try:
                data = await self._fetch_message(message_id)
            except Exception:  # noqa: BLE001
                continue

            text = self._format_chat_email(data)

            try:
                await self._client.send_message(self._mail_chat_peer, text)
            except Exception:  # noqa: BLE001
                pass

            self._known_message_ids.add(message_id)

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

    def _format_chat_email(self, data: Dict) -> str:
        email = utils.escape_html(self._format_mailbox())
        sender = utils.escape_html(self._get_sender(data))
        subject = utils.escape_html(data.get("subject", "—"))
        date = utils.escape_html(data.get("createdAt", data.get("date", "")))

        body = (
            data.get("text")
            or data.get("html")
            or data.get("textBody")
            or data.get("htmlBody")
            or ""
        )

        body_text = ""
        if isinstance(body, str):
            trimmed = body.strip()
            if trimmed:
                if len(trimmed) > 2000:
                    trimmed = f"{trimmed[:2000].rstrip()}…"
                body_text = self.strings("chat_email_body").format(
                    body=utils.escape_html(trimmed)
                )

        return self.strings("chat_email").format(
            email=email,
            sender=sender,
            subject=subject,
            date=date,
            body=body_text,
        )

