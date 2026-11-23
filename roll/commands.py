import re

import discord
from discord import app_commands
from discord.ext import commands
from discord.ext.commands.bot import Bot
from discord.ext.commands.context import Context

from bot.command_helpers import command_reply, delete_command
from bot.help_text import command_help
from bot.messaging import send_interaction_message, send_message
from config import PREFIX
from sheets.context import resolve_guild_id, resolve_mention_and_text, resolve_owner
from sheets.data import CharacterSheet
from sheets.dice import (
    ParsedRollRequest,
    apply_roll_options,
    execute_roll,
    format_roll_series_embed,
    parse_advantage_flag,
    parse_roll_args,
    validate_roll_request,
)
from sheets.storage import get_sheet, save_sheet

ROLL_HELP = command_help(
    "Jets de dés, avec les bonus de la fiche si tu en as une.",
    f"`{PREFIX}roll [dés|compétence] [adv|dis] [vs DD] [# texte]`",
    f"`{PREFIX}roll d20+5` · `{PREFIX}roll 2d6 + 3` — jet à la main, sans fiche",
    f"`{PREFIX}roll 1d20+1d4+5` · `{PREFIX}roll athlétisme +d4` — plusieurs dés",
    f"`{PREFIX}roll athlétisme` · `{PREFIX}roll force` — compétence ou caractéristique",
    f"`{PREFIX}roll sauvegarde sag` · `{PREFIX}roll dex save` — sauvegarde",
    f"`{PREFIX}roll adv perception` · `{PREFIX}roll dis d20+7` — avantage / désavantage",
    f"`{PREFIX}roll sauvegarde dex vs 15` — réussite ou échec contre un DD",
    f"`{PREFIX}roll 2x d20+7` · `{PREFIX}roll 6x 4d6kh3` — plusieurs jets (10 max)",
    f"`{PREFIX}roll crit 2d6+3` — dégâts critiques (dés doublés)",
    f"`{PREFIX}roll 2d6r2+3` — relance une fois les 1 et 2",
    f"`{PREFIX}roll d20+5 # épée longue` — texte affiché sur le jet",
    f"`{PREFIX}roll secret d20` — résultat envoyé en MP (en `/roll` : visible par toi seul)",
    f"`{PREFIX}roll @joueur athlétisme` — staff seulement",
    "`/roll` — mêmes jets, plus les options `bonus` (`2`, `1d4`), `avantage` et `secret`",
    "Fiche : `béni` / `fléau` en condition ajoute ±1d4 aux attaques et sauvegardes ; "
    "un halfelin relance ses 1 naturels (Chanceux).",
)

REROLL_TIMEOUT = 15 * 60

_ADVANTAGE_CHOICES = [
    app_commands.Choice(name="Avantage", value="advantage"),
    app_commands.Choice(name="Désavantage", value="disadvantage"),
]


def _clean_roll_args(args: str) -> str:
    return re.sub(r"<@!?\d+>", "", args).strip()


async def _leading_member(ctx: Context, args: str) -> tuple[discord.Member | None, str]:
    # Prefix `;roll Alice athletics`: the first word may name a member, as the
    # old positional Member converter allowed.
    first, _, rest = args.strip().partition(" ")
    if not first or not rest.strip():
        return None, args
    try:
        member = await commands.MemberConverter().convert(ctx, first)
    except commands.BadArgument:
        return None, args
    return member, rest.strip()


async def _resolve_roll_target(
    ctx: Context,
    member: discord.Member | None,
) -> tuple[int, CharacterSheet | None, str] | None:
    guild_id = resolve_guild_id(ctx)
    if guild_id is None:
        await command_reply(ctx, "Cette commande marche seulement sur le serveur.")
        return None

    owner_id = await resolve_owner(ctx, member)
    if owner_id is None:
        return None

    sheet = get_sheet(user_id=owner_id, guild_id=guild_id)
    if member is None and ctx.guild is not None and owner_id != ctx.author.id:
        found = ctx.guild.get_member(owner_id)
        if isinstance(found, discord.Member):
            member = found

    if member is not None and member.id != ctx.author.id:
        if sheet is None:
            await command_reply(ctx, f"**{member.display_name}** n’a pas de fiche.")
            return None
        return owner_id, sheet, f"**{sheet.name}** ({member.display_name})"

    label = f"**{sheet.name}**" if sheet else f"**{ctx.author.display_name}**"
    return owner_id, sheet, label


def _avantage_value(value: object) -> str | None:
    if value is None:
        return None
    if isinstance(value, app_commands.Choice):
        raw = value.value
        return str(raw) if raw is not None else None
    text = str(value).strip()
    return text or None


def prepare_roll_request(
    args: str,
    *,
    bonus: int | str | None = None,
    avantage: object = None,
) -> ParsedRollRequest | None:
    option_adv = parse_advantage_flag(_avantage_value(avantage))
    cleaned = args.strip()
    if not cleaned:
        if not bonus and option_adv is None:
            return None
        cleaned = "1d20"
    request = parse_roll_args(cleaned)
    request = apply_roll_options(request, bonus=bonus, advantage=option_adv)
    validate_roll_request(request)
    return request


def roll_embed(
    *,
    request: ParsedRollRequest,
    owner_id: int,
    guild_id: int | None,
    sheet: CharacterSheet | None,
    roller_label: str,
) -> discord.Embed:
    """Roll `request` (`repeat` times) and return the embed to post."""
    results = [
        execute_roll(
            dice=request.dice,
            sheet=sheet,
            modifier_tokens=request.modifier_tokens,
            advantage=request.advantage,
            dc=request.dc,
        )
        for _ in range(request.repeat)
    ]
    spent = any(result.spent_inspiration for result in results)
    if spent and sheet is not None and guild_id is not None:
        save_sheet(user_id=owner_id, guild_id=guild_id, sheet=sheet)
    return format_roll_series_embed(
        results, roller_label=roller_label, label=request.label
    )


class RerollView(discord.ui.View):
    """🎲 button under a roll: the same roll again, for its author only."""

    def __init__(
        self,
        *,
        author_id: int,
        request: ParsedRollRequest,
        owner_id: int,
        guild_id: int | None,
        roller_label: str,
        secret: bool,
    ) -> None:
        super().__init__(timeout=REROLL_TIMEOUT)
        self.author_id = author_id
        self.request = request
        self.owner_id = owner_id
        self.guild_id = guild_id
        self.roller_label = roller_label
        self.secret = secret
        self.message: discord.Message | None = None

    def again(self) -> "RerollView":
        return RerollView(
            author_id=self.author_id,
            request=self.request,
            owner_id=self.owner_id,
            guild_id=self.guild_id,
            roller_label=self.roller_label,
            secret=self.secret,
        )

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id == self.author_id:
            return True
        await interaction.response.send_message(
            "Seul l’auteur du jet peut le relancer.", ephemeral=True
        )
        return False

    @discord.ui.button(
        label="Relancer", emoji="🎲", style=discord.ButtonStyle.secondary
    )
    async def reroll(
        self, interaction: discord.Interaction, _button: discord.ui.Button
    ) -> None:
        sheet = (
            get_sheet(user_id=self.owner_id, guild_id=self.guild_id)
            if self.guild_id is not None
            else None
        )
        try:
            embed = roll_embed(
                request=self.request,
                owner_id=self.owner_id,
                guild_id=self.guild_id,
                sheet=sheet,
                roller_label=self.roller_label,
            )
        except ValueError as exc:
            await interaction.response.send_message(str(exc), ephemeral=True)
            return
        view = self.again()
        view.message = await send_interaction_message(
            interaction,
            embed=embed,
            view=view,
            ephemeral=self.secret and interaction.guild is not None,
            definition_menu=False,
        )

    async def on_timeout(self) -> None:
        if self.message is None:
            return
        try:
            await self.message.edit(view=None)
        except discord.HTTPException:
            pass


async def _send_roll(
    ctx: Context, *, embed: discord.Embed, view: RerollView, secret: bool
) -> bool:
    if not secret:
        view.message = await send_message(
            ctx, embed=embed, view=view, definition_menu=False
        )
        return True
    if ctx.interaction is not None:
        view.message = await send_message(
            ctx, embed=embed, view=view, ephemeral=True, definition_menu=False
        )
        return True
    try:
        view.message = await send_message(
            ctx.author, embed=embed, view=view, definition_menu=False
        )
    except discord.Forbidden:
        await command_reply(
            ctx, "Je ne peux pas t’envoyer de MP : ouvre tes messages privés."
        )
        return False
    return True


def setup_roll(bot: Bot) -> None:
    @bot.hybrid_command(
        name="roll",
        aliases=["r"],
        help=ROLL_HELP,
    )
    @app_commands.describe(
        args="Dés ou compétence, ex. perception, 2d6+3, d20+5 vs 15",
        bonus="Bonus en plus, ex. 2, -1 ou 1d4",
        avantage="Avantage ou désavantage",
        secret="Résultat visible par toi seul",
        member="Fiche d’un autre joueur (staff)",
    )
    @app_commands.choices(avantage=_ADVANTAGE_CHOICES)
    async def roll_command(
        ctx: Context,
        *,
        args: str = "",
        bonus: str | None = None,
        avantage: str | None = None,
        secret: bool = False,
        member: discord.Member | None = None,
    ) -> None:
        if member is None:
            parsed = await resolve_mention_and_text(ctx, args)
            if parsed is None:
                return
            member, args = parsed
            if member is None and ctx.interaction is None:
                member, args = await _leading_member(ctx, args)
        else:
            args = _clean_roll_args(args)
        if secret and not args.strip():
            args = "1d20"

        try:
            request = prepare_roll_request(args, bonus=bonus, avantage=avantage)
        except ValueError as exc:
            await command_reply(ctx, str(exc))
            return
        if request is None:
            await ctx.send_help(ctx.command)
            return

        target = await _resolve_roll_target(ctx, member)
        if target is None:
            return
        owner_id, sheet, roller_label = target
        guild_id = resolve_guild_id(ctx)

        try:
            embed = roll_embed(
                request=request,
                owner_id=owner_id,
                guild_id=guild_id,
                sheet=sheet,
                roller_label=roller_label,
            )
        except ValueError as exc:
            await command_reply(ctx, str(exc))
            return

        secret = secret or request.secret
        view = RerollView(
            author_id=ctx.author.id,
            request=request,
            owner_id=owner_id,
            guild_id=guild_id,
            roller_label=roller_label,
            secret=secret,
        )
        if await _send_roll(ctx, embed=embed, view=view, secret=secret):
            await delete_command(ctx)
