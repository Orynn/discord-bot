import asyncio
import inspect

import discord
from discord import app_commands
from discord.ext.commands import CheckFailure, Group, MinimalHelpCommand
from discord.ext.commands.bot import Bot
from discord.ext.commands.context import Context

from bot.checks import is_admin
from bot.command_helpers import command_reply, delete_command
from bot.help_text import (
    HELP_COLOR,
    build_combat_help_sections,
    build_command_help_embed,
    build_group_help_embed,
    build_guide_help_embeds,
    build_help_sections,
    build_hunger_help_sections,
    build_roleplay_help_sections,
    build_sheet_help_sections,
    build_simple_help_embed,
    build_srd_help_sections,
    command_help,
    command_help_summary,
    is_help_all_topic,
    is_roleplay_help_topic,
    pack_embed_batches,
)
from bot.help_view import HelpView
from bot.messaging import send_message
from config import PREFIX

HELP_FLAGS = frozenset({"-h", "--help", "-help"})
HELP_WORDS = frozenset({"help", "aide"})
_SECTIONED_GROUPS = frozenset({"sheet", "combat", "srd", "hunger"})
_HELP_ALL_PAUSE_SECONDS = 0.35
_TEXT_KWARG_NAMES = frozenset(
    {
        "args",
        "query",
        "text",
        "prompt",
        "details",
        "amount",
        "when",
        "dialogue",
        "condition",
        "value",
        "name",
        "action",
        "target",
        "mood",
        "note",
    }
)


class CommandHelpShown(CheckFailure):
    """Help was sent; do not run the command or treat this as a permission error."""


def is_command_help_shown(error: BaseException) -> bool:
    if isinstance(error, CommandHelpShown):
        return True
    original = getattr(error, "original", None)
    if isinstance(original, CommandHelpShown):
        return True
    return isinstance(getattr(error, "__cause__", None), CommandHelpShown)


def leftover_argument_tokens(ctx: Context) -> list[str]:
    view = getattr(ctx, "view", None)
    rest = getattr(view, "rest", None)
    if isinstance(rest, str) and rest.strip():
        return rest.split()
    kwargs = getattr(ctx, "kwargs", None)
    if isinstance(kwargs, dict):
        preferred: list[str] = []
        other: list[str] = []
        for key, value in kwargs.items():
            if not isinstance(value, str) or not value.strip():
                continue
            target = preferred if str(key).casefold() in _TEXT_KWARG_NAMES else other
            target.extend(value.split())
        return preferred or other
    return []


def tokens_request_help(tokens: list[str]) -> bool:
    if not tokens:
        return False
    folded = [token.casefold() for token in tokens]
    if any(token in HELP_FLAGS for token in folded):
        return True
    return all(token in HELP_WORDS for token in folded)


def _is_help_token(token: str) -> bool:
    folded = token.casefold()
    return folded in HELP_FLAGS or folded in HELP_WORDS


def _subcommand_named(command, name: str):
    children = getattr(command, "all_commands", None)
    if not isinstance(children, dict) or not children:
        return None
    found = children.get(name)
    if found is not None:
        return found
    folded = name.casefold()
    if folded != name:
        found = children.get(folded)
        if found is not None:
            return found
    for key, child in children.items():
        if str(key).casefold() == folded:
            return child
    return None


def _command_is_lookup(command) -> bool:
    params = getattr(command, "clean_params", None)
    if not isinstance(params, dict):
        return False
    for name, parameter in params.items():
        if str(name).casefold() != "query":
            continue
        default = getattr(parameter, "default", inspect.Parameter.empty)
        if default is inspect.Parameter.empty:
            return True
    return False


def help_target_command(ctx: Context):
    command = getattr(ctx, "command", None)
    if command is None:
        return None
    tokens = leftover_argument_tokens(ctx)
    index = 0
    while index < len(tokens) and not _is_help_token(tokens[index]):
        child = _subcommand_named(command, tokens[index])
        if child is None:
            break
        command = child
        index += 1
    remaining = tokens[index:]
    if not tokens_request_help(remaining):
        return None
    folded = [token.casefold() for token in remaining]
    dash_help = any(token in HELP_FLAGS for token in folded)
    if not dash_help and _command_is_lookup(command):
        return None
    return command


def wants_command_help(ctx: Context) -> bool:
    return help_target_command(ctx) is not None


async def maybe_send_command_help(ctx: Context) -> bool:
    command = help_target_command(ctx)
    if command is None:
        return False
    await ctx.send_help(command)
    return True


def _command_name(command) -> str:
    return f"`{PREFIX}{command.qualified_name}`"


def _command_signature(command) -> str:
    signature = (command.signature or "").strip()
    if signature:
        return f"`{PREFIX}{command.qualified_name} {signature}`"
    return _command_name(command)


def _command_aliases(command) -> list[str]:
    parent = command.full_parent_name
    aliases = []
    for alias in sorted(command.aliases):
        if parent:
            aliases.append(f"`{PREFIX}{parent} {alias}`")
        else:
            aliases.append(f"`{PREFIX}{alias}`")
    return aliases


def iter_visible_commands(bot: Bot):
    def walk(commands):
        for command in sorted(commands, key=lambda cmd: cmd.qualified_name):
            if command.hidden:
                continue
            if command.parent is None and command.name == "help":
                continue
            yield command
            children = getattr(command, "commands", None)
            if children:
                yield from walk(children)

    yield from walk(bot.commands)


def _group_subcommand_rows(group: Group) -> list[tuple[str, str]]:
    rows = []
    for command in sorted(
        (cmd for cmd in group.commands if not cmd.hidden),
        key=lambda cmd: cmd.name,
    ):
        rows.append(
            (
                _command_name(command),
                command_help_summary(command.help or command.short_doc or ""),
            )
        )
    return rows


def command_catalog_embed(command) -> discord.Embed | None:
    if isinstance(command, Group) and command.qualified_name in _SECTIONED_GROUPS:
        return None
    if isinstance(command, Group):
        return build_group_help_embed(
            qualified_name=command.qualified_name,
            help_text=command.help or "",
            usage=_command_signature(command),
            subcommands=_group_subcommand_rows(command),
            aliases=_command_aliases(command),
            footer=f"Astuce : {PREFIX}{command.qualified_name} <sous-commande> -h",
        )
    return build_command_help_embed(
        qualified_name=command.qualified_name,
        help_text=command.help or "",
        usage=_command_signature(command),
        aliases=_command_aliases(command),
    )


def collect_all_help_embeds(bot: Bot, *, is_admin: bool) -> list[discord.Embed]:
    embeds = build_guide_help_embeds(prefix=PREFIX, is_admin=is_admin)
    embeds.append(
        discord.Embed(
            title="❓ Commandes",
            description="Fiche détaillée de chaque commande (`-h`).",
            color=HELP_COLOR,
        )
    )
    for command in iter_visible_commands(bot):
        embed = command_catalog_embed(command)
        if embed is not None:
            embeds.append(embed)
    return embeds


async def send_all_help(ctx: Context) -> None:
    interaction = getattr(ctx, "interaction", None)
    if interaction is not None and not interaction.response.is_done():
        await ctx.defer()

    embeds = collect_all_help_embeds(ctx.bot, is_admin=is_admin(ctx))
    batches = pack_embed_batches(embeds)
    try:
        for index, batch in enumerate(batches):
            content = None
            if index == 0:
                content = f"📖 Aide complète Arkann — {len(embeds)} fiches"
            await send_message(
                ctx.author,
                content=content,
                embeds=batch,
                linkify=False,
                definition_menu=False,
            )
            if index + 1 < len(batches):
                await asyncio.sleep(_HELP_ALL_PAUSE_SECONDS)
    except discord.Forbidden:
        await command_reply(
            ctx,
            (
                "Je ne peux pas t’écrire en MP. "
                f"Autorise les messages privés, puis relance `{PREFIX}help all`."
            ),
            linkify=False,
            definition_menu=False,
        )
        await delete_command(ctx)
        return

    if ctx.guild is not None:
        await command_reply(
            ctx,
            "Aide complète envoyée en MP.",
            linkify=False,
            definition_menu=False,
        )
    await delete_command(ctx)


async def _send_sectioned_help(
    ctx: Context,
    *,
    title: str,
    sections,
) -> None:
    view = HelpView(
        title=title,
        sections=sections,
    )
    message = await send_message(
        ctx,
        embed=view.current_embed(),
        view=view,
        linkify=False,
        definition_menu=False,
    )
    view.message = message
    await delete_command(ctx)


async def _send_help_embed(ctx: Context, embed: discord.Embed) -> None:
    await send_message(ctx, embeds=[embed], linkify=False, definition_menu=False)
    await delete_command(ctx)


async def send_srd_help(ctx: Context) -> None:
    await _send_sectioned_help(
        ctx,
        title="Recherche de règles",
        sections=build_srd_help_sections(prefix=PREFIX),
    )


class ArkannHelpCommand(MinimalHelpCommand):
    async def command_callback(
        self, ctx: Context, /, *, command: str | None = None
    ) -> None:
        if is_help_all_topic(command):
            await send_all_help(ctx)
            return
        if is_roleplay_help_topic(command):
            await _send_sectioned_help(
                ctx,
                title="Jeu de rôle",
                sections=build_roleplay_help_sections(prefix=PREFIX),
            )
            return
        await super().command_callback(ctx, command=command)

    async def send_bot_help(self, mapping, /) -> None:
        ctx = self.context
        await _send_sectioned_help(
            ctx,
            title="Arkann — commandes",
            sections=build_help_sections(prefix=PREFIX, is_admin=is_admin(ctx)),
        )

    async def send_group_help(self, group, /) -> None:
        ctx = self.context
        if group.qualified_name == "sheet":
            await _send_sectioned_help(
                ctx,
                title="Fiche de personnage",
                sections=build_sheet_help_sections(
                    prefix=PREFIX,
                    is_admin=is_admin(ctx),
                ),
            )
            return

        if group.qualified_name == "combat":
            await _send_sectioned_help(
                ctx,
                title="Combat",
                sections=build_combat_help_sections(
                    prefix=PREFIX,
                    is_admin=is_admin(ctx),
                ),
            )
            return

        if group.qualified_name == "srd":
            await send_srd_help(ctx)
            return

        if group.qualified_name == "hunger":
            await _send_sectioned_help(
                ctx,
                title="Faim",
                sections=build_hunger_help_sections(
                    prefix=PREFIX,
                    is_admin=is_admin(ctx),
                ),
            )
            return

        subcommands = []
        for command in sorted(
            (cmd for cmd in group.commands if not cmd.hidden),
            key=lambda cmd: cmd.name,
        ):
            subcommands.append(
                (
                    _command_name(command),
                    command_help_summary(command.help or command.short_doc or ""),
                )
            )
        embed = build_group_help_embed(
            qualified_name=group.qualified_name,
            help_text=group.help or "",
            usage=_command_signature(group),
            subcommands=subcommands,
            aliases=_command_aliases(group),
            footer=f"Astuce : {PREFIX}{group.qualified_name} <sous-commande> -h",
        )
        await _send_help_embed(ctx, embed)

    async def send_command_help(self, command, /) -> None:
        embed = build_command_help_embed(
            qualified_name=command.qualified_name,
            help_text=command.help or "",
            usage=_command_signature(command),
            aliases=_command_aliases(command),
        )
        await _send_help_embed(self.context, embed)

    async def send_pages(self) -> None:
        ctx = self.context
        embeds = [
            discord.Embed(description=page, color=HELP_COLOR)
            for page in self.paginator.pages
        ]
        if embeds:
            await send_message(ctx, embeds=embeds, linkify=False, definition_menu=False)
            await delete_command(ctx)

    async def send_error_message(self, error: str) -> None:
        embed = build_simple_help_embed(title="⚠️ Aide", description=error)
        await send_message(
            self.context,
            embeds=[embed],
            linkify=False,
            definition_menu=False,
        )


def setup_help(bot: Bot) -> None:
    bot.help_command = ArkannHelpCommand()

    @bot.check
    async def intercept_slash_command_help(ctx: Context) -> bool:
        if getattr(ctx, "interaction", None) is None:
            return True
        if await maybe_send_command_help(ctx):
            raise CommandHelpShown()
        return True

    @bot.hybrid_command(
        name="aide",
        help=command_help(
            "Affiche la liste des commandes.",
            f"`{PREFIX}aide` · `{PREFIX}help` · `/help`",
            f"`{PREFIX}help all` — tout envoyer en MP",
        ),
        hidden=True,
    )
    async def aide_command(ctx: Context, *, topic: str = "") -> None:
        if is_help_all_topic(topic):
            await send_all_help(ctx)
            return
        await _send_sectioned_help(
            ctx,
            title="Arkann — commandes",
            sections=build_help_sections(prefix=PREFIX, is_admin=is_admin(ctx)),
        )

    @bot.tree.command(name="help", description="Show Arkann commands")
    @app_commands.describe(
        topic="Sujet : all, sheet, combat, srd, hunger, roleplay, ou un nom de commande"
    )
    async def slash_help(
        interaction: discord.Interaction, topic: str | None = None
    ) -> None:
        ctx = await bot.get_context(interaction)
        query = (topic or "").strip().lower()
        if is_help_all_topic(query):
            await send_all_help(ctx)
            return
        if not query:
            await _send_sectioned_help(
                ctx,
                title="Arkann — commandes",
                sections=build_help_sections(prefix=PREFIX, is_admin=is_admin(ctx)),
            )
            return
        if query in {"sheet", "character", "fiche"}:
            await _send_sectioned_help(
                ctx,
                title="Fiche de personnage",
                sections=build_sheet_help_sections(
                    prefix=PREFIX, is_admin=is_admin(ctx)
                ),
            )
            return
        if query in {"combat", "cards"}:
            await _send_sectioned_help(
                ctx,
                title="Combat",
                sections=build_combat_help_sections(
                    prefix=PREFIX, is_admin=is_admin(ctx)
                ),
            )
            return
        if query in {"srd", "lookup", "5etools", "regles", "règles"}:
            await send_srd_help(ctx)
            return
        if query in {"hunger", "faim", "food"}:
            await _send_sectioned_help(
                ctx,
                title="Faim",
                sections=build_hunger_help_sections(
                    prefix=PREFIX,
                    is_admin=is_admin(ctx),
                ),
            )
            return
        if is_roleplay_help_topic(query):
            await _send_sectioned_help(
                ctx,
                title="Jeu de rôle",
                sections=build_roleplay_help_sections(prefix=PREFIX),
            )
            return
        await ctx.send_help(query)
