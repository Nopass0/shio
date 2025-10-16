"""Hikka module providing inline module/command browser"""

import inspect
import math
from typing import Dict, List

from hikkatl.tl.types import Message

from .. import loader, utils
from ..inline.types import InlineCall


@loader.tds
class ModuleMenu(loader.Module):
    """Interactive inline menu with loaded modules and their commands"""

    strings = {
        "name": "ModuleMenu",
        "menu_title": (
            "📚 <b>Loaded modules:</b> {total}\n"
            "<i>Select a module to view its commands.</i>"
        ),
        "empty": "🙈 <b>No modules loaded.</b>",
        "page_label": "{page}/{pages}",
        "back": "⬅️ Back",
        "close": "✖️ Close",
        "first_page": "You're already on the first page",
        "last_page": "You're already on the last page",
        "module_template": (
            "<b>{name}</b>\n{description}\n\n"
            "<b>Commands ({count}):</b>\n{commands}{inline_section}"
        ),
        "command_line": "• <code>{prefix}{command}</code> — {description}",
        "no_command_docs": "No description",
        "no_commands": "No commands in this module.",
        "inline_section": "\n\n<b>Inline:</b>\n{handlers}",
        "inline_line": "• <code>@{bot} {handler}</code> — {description}",
        "no_inline_docs": "No description",
    }

    strings_ru = {
        "_cls_doc": "Инлайн-меню с модулями и командами",
        "name": "ModuleMenu",
        "menu_title": (
            "📚 <b>Загруженные модули:</b> {total}\n"
            "<i>Выбери модуль, чтобы увидеть его команды.</i>"
        ),
        "empty": "🙈 <b>Модули не найдены.</b>",
        "page_label": "{page}/{pages}",
        "back": "⬅️ Назад",
        "close": "✖️ Закрыть",
        "first_page": "Это первая страница",
        "last_page": "Это последняя страница",
        "module_template": (
            "<b>{name}</b>\n{description}\n\n"
            "<b>Команды ({count}):</b>\n{commands}{inline_section}"
        ),
        "command_line": "• <code>{prefix}{command}</code> — {description}",
        "no_command_docs": "Описание отсутствует",
        "no_commands": "В модуле нет команд.",
        "inline_section": "\n\n<b>Инлайн:</b>\n{handlers}",
        "inline_line": "• <code>@{bot} {handler}</code> — {description}",
        "no_inline_docs": "Описание отсутствует",
    }

    def __init__(self):
        self._page_size = 6

    @loader.command()
    async def modmenu(self, message: Message):
        """Open the inline menu with modules and commands"""

        modules = self._collect_modules()

        if not modules:
            await utils.answer(message, self.strings("empty"))
            return

        await self._show_page(message, 0, modules)

    async def inline__modmenu_page(self, call: InlineCall, page: int):
        modules = self._collect_modules()

        if not modules:
            await call.answer(self.strings("empty"), show_alert=True)
            await call.unload()
            return

        page_count = max(math.ceil(len(modules) / self._page_size), 1)

        if page < 0:
            await call.answer(self.strings("first_page"))
            page = 0
        elif page >= page_count:
            await call.answer(self.strings("last_page"))
            page = page_count - 1

        await call.edit(**self._build_page_content(modules, page))

    async def inline__modmenu_module(self, call: InlineCall, module_id: str, page: int):
        modules = self._collect_modules()
        module = next((mod for mod in modules if mod["id"] == module_id), None)

        if module is None:
            await call.answer(self.strings("empty"), show_alert=True)
            await call.edit(**self._build_page_content(modules, 0))
            return

        await call.edit(**self._build_module_content(module, page))

    async def inline__modmenu_back(self, call: InlineCall, page: int):
        modules = self._collect_modules()
        if not modules:
            await call.answer(self.strings("empty"), show_alert=True)
            await call.unload()
            return

        await call.edit(**self._build_page_content(modules, max(page, 0)))

    async def inline__modmenu_noop(self, call: InlineCall):
        await call.answer("•")

    async def _show_page(self, message: Message, page: int, modules: List[Dict]):
        await self.inline.form(
            **self._build_page_content(modules, page),
            message=message,
        )

    def _collect_modules(self) -> List[Dict]:
        modules = []
        for index, module in enumerate(self.allmodules.modules):
            name = self._get_module_name(module)
            description = inspect.getdoc(module) or ""
            modules.append(
                {
                    "id": f"{index}:{module.__class__.__name__}",
                    "module": module,
                    "name": name,
                    "description": description,
                }
            )

        modules.sort(key=lambda item: item["name"].lower())
        return modules

    def _build_page_content(self, modules: List[Dict], page: int) -> Dict:
        total = len(modules)
        page_count = max(math.ceil(total / self._page_size), 1)
        page = max(0, min(page, page_count - 1))

        start = page * self._page_size
        end = start + self._page_size
        page_modules = modules[start:end]

        text = self.strings("menu_title").format(total=total)

        markup: List[List[Dict]] = []

        for module in page_modules:
            markup.append(
                [
                    {
                        "text": module["name"],
                        "callback": self.inline__modmenu_module,
                        "args": (module["id"], page),
                    }
                ]
            )

        if page_count > 1:
            markup.append(
                [
                    {
                        "text": "⬅️",
                        "callback": self.inline__modmenu_page,
                        "args": (page - 1,),
                    },
                    {
                        "text": self.strings("page_label").format(
                            page=page + 1,
                            pages=page_count,
                        ),
                        "callback": self.inline__modmenu_noop,
                    },
                    {
                        "text": "➡️",
                        "callback": self.inline__modmenu_page,
                        "args": (page + 1,),
                    },
                ]
            )

        markup.append([{ "text": self.strings("close"), "action": "close" }])

        return {
            "text": text,
            "reply_markup": markup,
        }

    def _build_module_content(self, module_data: Dict, page: int) -> Dict:
        module = module_data["module"]
        name = utils.escape_html(module_data["name"])
        description = utils.escape_html(module_data["description"]) if module_data["description"] else ""

        commands = module.commands
        prefix = utils.escape_html(self.get_prefix())
        command_lines = []

        for command_name, function in sorted(commands.items()):
            doc = inspect.getdoc(function) or self.strings("no_command_docs")
            command_lines.append(
                self.strings("command_line").format(
                    prefix=prefix,
                    command=utils.escape_html(command_name),
                    description=utils.escape_html(doc),
                )
            )

        commands_text = "\n".join(command_lines) if command_lines else self.strings("no_commands")

        inline_handlers = getattr(module, "inline_handlers", {})
        inline_lines = []
        if inline_handlers:
            bot_username = self.inline.bot_username or "inline_bot"
            for handler_name, handler in sorted(inline_handlers.items()):
                doc = inspect.getdoc(handler) or self.strings("no_inline_docs")
                inline_lines.append(
                    self.strings("inline_line").format(
                        bot=utils.escape_html(bot_username),
                        handler=utils.escape_html(handler_name),
                        description=utils.escape_html(doc),
                    )
                )

        inline_section = (
            self.strings("inline_section").format(handlers="\n".join(inline_lines))
            if inline_lines
            else ""
        )

        text = self.strings("module_template").format(
            name=name,
            description=description if description else "",
            count=len(command_lines),
            commands=commands_text,
            inline_section=inline_section,
        )

        markup = [
            [
                {
                    "text": self.strings("back"),
                    "callback": self.inline__modmenu_back,
                    "args": (page,),
                }
            ],
            [{"text": self.strings("close"), "action": "close"}],
        ]

        return {
            "text": text,
            "reply_markup": markup,
        }

    def _get_module_name(self, module: loader.Module) -> str:
        try:
            return module.strings("name")
        except Exception:
            return getattr(module, "name", module.__class__.__name__)
