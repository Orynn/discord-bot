import discord
from discord import app_commands
from discord.ext.commands import MinimalHelpCommand
from discord.ext.commands.bot import Bot
from discord.ext.commands.context import Context

from bot.checks import is_admin
from bot.command_helpers import delete_command
from bot.help_text import (
    HELP_COLOR,
    build_combat_help_sections,
    build_help_sections,
    build_hunger_help_sections,
    build_sheet_help_sections,
    build_simple_help_embed,
    build_srd_help_sections,
)
from bot.help_view import HelpView
from bot.messaging import send_message
from config import PREFIX

HELP_FLAGS = frozenset({"-h", "--help", "-help"})


def leftover_argument_tokens(ctx: Context) -> list[str]:
    view = getattr(ctx, "view", None)
    rest = getattr(view, "rest", None)
    if isinstance(rest, str) and rest.strip():
        return rest.split()
    return []


def wants_command_help(ctx: Context) -> bool:
    if getattr(ctx, "command", None) is None:
        return False
    if getattr(ctx, "interaction", None) is not None:
        return False
    return any(
        token.casefold() in HELP_FLAGS for token in leftover_argument_tokens(ctx)
    )


async def maybe_send_command_help(ctx: Context) -> bool:
    if not wants_command_help(ctx):
        return False
    await ctx.send_help(ctx.command)
    return True


def _command_signature(command) -> str:
    parent = command.full_parent_name
    name = f"{parent} {command.name}" if parent else command.name
    return f"`{PREFIX}{name}`"


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
                title="Combat à cartes",
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

        lines: list[str] = []
        if group.help:
            lines.append(group.help.strip())

        subcommands = [cmd for cmd in group.commands if not cmd.hidden]
        if subcommands:
            if lines:
                lines.append("")
            for command in sorted(subcommands, key=lambda cmd: cmd.name):
                summary = (
                    (command.short_doc or command.help or "").strip().split("\n")[0]
                )
                line = f"• {_command_signature(command)}"
                if summary:
                    if len(summary) > 80:
                        summary = summary[:77] + "…"
                    line = f"{line} — {summary}"
                lines.append(line)

        embed = build_simple_help_embed(
            title=group.qualified_name,
            description="\n".join(lines) if lines else "No help available.",
            footer=f"{PREFIX}help {group.qualified_name} <subcommand> for more",
        )
        await _send_help_embed(ctx, embed)

    async def send_command_help(self, command, /) -> None:
        description = (
            command.help.strip()
            if command.help
            else f"Usage: `{PREFIX}{command.qualified_name}`"
        )
        aliases = sorted(command.aliases)
        if aliases:
            if command.parent is None:
                alias_text = ", ".join(f"`{PREFIX}{alias}`" for alias in aliases)
            else:
                alias_text = ", ".join(f"`{alias}`" for alias in aliases)
            description = f"{description}\n\n**Aliases:** {alias_text}"

        embed = discord.Embed(
            title=f"❓ {command.qualified_name}",
            description=description,
            color=HELP_COLOR,
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
        embed = build_simple_help_embed(title="⚠️ Help", description=error)
        await send_message(
            self.context,
            embeds=[embed],
            linkify=False,
            definition_menu=False,
        )


def setup_help(bot: Bot) -> None:
    bot.help_command = ArkannHelpCommand()

    @bot.hybrid_command(
        name="aide",
        help="Show the command list. Same as /help or ;help.",
        hidden=True,
    )
    async def aide_command(ctx: Context) -> None:
        await _send_sectioned_help(
            ctx,
            title="Arkann — commandes",
            sections=build_help_sections(prefix=PREFIX, is_admin=is_admin(ctx)),
        )

    @bot.tree.command(name="help", description="Show Arkann commands")
    @app_commands.describe(
        topic="Optional topic: sheet, combat, srd, hunger, or a command name"
    )
    async def slash_help(
        interaction: discord.Interaction, topic: str | None = None
    ) -> None:
        ctx = await bot.get_context(interaction)
        query = (topic or "").strip().lower()
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
                title="Combat à cartes",
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
        await ctx.send_help(query)
