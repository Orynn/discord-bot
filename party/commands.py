import discord
from discord.ext.commands.bot import Bot
from discord.ext.commands.context import Context

from bot.checks import admin_only, guild_only
from bot.command_helpers import command_reply, delete_command
from bot.help_text import HELP_COLOR
from bot.messaging import send_message
from config import PREFIX
from party.storage import get_party_currency, save_party_currency
from sheets.currency import parse_currency


def _treasury_embed(*, amount: str, notice: str | None = None) -> discord.Embed:
    embed = discord.Embed(
        title="💰 Party treasury",
        description=notice or f"**{amount}**",
        color=HELP_COLOR,
    )
    if notice:
        embed.add_field(name="Balance", value=f"**{amount}**", inline=False)
    embed.set_footer(text=f"{PREFIX}party money show|set|add|spend")
    return embed


def setup_party(bot: Bot) -> None:
    @bot.hybrid_group(
        name="party",
        invoke_without_command=True,
        fallback="menu",
        help="Party shared resources and treasury.",
    )
    @guild_only
    async def party_group(ctx: Context) -> None:
        currency = get_party_currency(guild_id=ctx.guild.id)
        await send_message(
            ctx,
            embed=_treasury_embed(amount=currency.format()),
            definition_menu=False,
        )
        await delete_command(ctx)

    @party_group.group(
        name="money",
        invoke_without_command=True,
        fallback="show",
        help="Show or manage the party treasury.",
    )
    @guild_only
    async def party_money_group(ctx: Context) -> None:
        currency = get_party_currency(guild_id=ctx.guild.id)
        await send_message(
            ctx,
            embed=_treasury_embed(amount=currency.format()),
            definition_menu=False,
        )
        await delete_command(ctx)

    @party_money_group.command(name="set", help="Set the party treasury amount.")
    @guild_only
    @admin_only
    async def party_money_set(ctx: Context, *, amount: str) -> None:
        try:
            currency = parse_currency(amount)
        except ValueError as exc:
            await command_reply(ctx, str(exc))
            return
        save_party_currency(guild_id=ctx.guild.id, currency=currency)
        await send_message(
            ctx,
            embed=_treasury_embed(amount=currency.format(), notice=f"Set to **{currency.format()}**."),
            definition_menu=False,
        )
        await delete_command(ctx)

    @party_money_group.command(name="add", help="Add coins to the party treasury.")
    @guild_only
    @admin_only
    async def party_money_add(ctx: Context, *, amount: str) -> None:
        try:
            added = parse_currency(amount)
            currency = get_party_currency(guild_id=ctx.guild.id)
            currency.add(added)
        except ValueError as exc:
            await command_reply(ctx, str(exc))
            return
        save_party_currency(guild_id=ctx.guild.id, currency=currency)
        await send_message(
            ctx,
            embed=_treasury_embed(
                amount=currency.format(),
                notice=f"Added **{added.format()}**.",
            ),
            definition_menu=False,
        )
        await delete_command(ctx)

    @party_money_group.command(name="spend", help="Spend coins from the party treasury.")
    @guild_only
    @admin_only
    async def party_money_spend(ctx: Context, *, amount: str) -> None:
        try:
            cost = parse_currency(amount)
            currency = get_party_currency(guild_id=ctx.guild.id)
            if not currency.subtract(cost):
                await command_reply(ctx, f"Party cannot afford **{cost.format()}**.")
                return
        except ValueError as exc:
            await command_reply(ctx, str(exc))
            return
        save_party_currency(guild_id=ctx.guild.id, currency=currency)
        await send_message(
            ctx,
            embed=_treasury_embed(
                amount=currency.format(),
                notice=f"Spent **{cost.format()}**.",
            ),
            definition_menu=False,
        )
        await delete_command(ctx)
