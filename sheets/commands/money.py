import discord
from discord.ext.commands import Group
from discord.ext.commands.context import Context

from bot.checks import admin_only, is_admin
from bot.command_helpers import command_reply, delete_command
from bot.help_text import HELP_COLOR, command_help
from bot.messaging import send_message
from config import PREFIX
from sheets.context import (
    get_sheet_for_owner,
    resolve_guild_id,
    save_owner_sheet,
    target_label,
)
from sheets.currency import parse_currency
from sheets.storage import get_sheet, transfer_currency


def register_money_commands(sheet_group: Group) -> None:
    @sheet_group.group(
        name="money",
        aliases=["gold", "coins"],
        invoke_without_command=True,
        help=command_help(
            "Bourse du personnage (50 po, 5 po 3 pa).",
            f"`{PREFIX}sheet money`",
        ),
    )
    async def sheet_money_group(
        ctx: Context, member: discord.Member | None = None
    ) -> None:
        result = await get_sheet_for_owner(ctx, member)
        if result is None:
            return
        _, sheet = result

        label = target_label(member, sheet)
        admin_hint = " [@player]" if is_admin(ctx) else ""
        embed = discord.Embed(
            title="💰 Wallet",
            description=f"{label} has **{sheet.currency.format()}**.",
            color=HELP_COLOR,
        )
        embed.add_field(
            name="⌨️ Commands",
            value=(
                f"`{PREFIX}sheet money show{admin_hint}` — display wallet\n"
                f"`{PREFIX}sheet money set{admin_hint} <amount>` — set wallet *(admin)*\n"
                f"`{PREFIX}sheet money add{admin_hint} <amount>` — add coins *(admin)*\n"
                f"`{PREFIX}sheet money spend{admin_hint} <amount>` — remove coins\n"
                f"`{PREFIX}sheet money pay{admin_hint} @player <amount>` — pay another player"
            ),
            inline=False,
        )
        embed.set_footer(text="Amounts: 50 gp · 5 gp 3 sp")
        await send_message(ctx, embed=embed, definition_menu=False)
        await delete_command(ctx)

    @sheet_money_group.command(
        name="show",
        help=command_help(
            "Affiche la bourse.",
            f"`{PREFIX}sheet money show [@joueur]`",
        ),
    )
    async def sheet_money_show(
        ctx: Context, member: discord.Member | None = None
    ) -> None:
        result = await get_sheet_for_owner(ctx, member)
        if result is None:
            return
        _, sheet = result

        label = target_label(member, sheet)
        await command_reply(ctx, f"{label}: **{sheet.currency.format()}**.")
        await delete_command(ctx)

    @sheet_money_group.command(
        name="set",
        help=command_help(
            "Fixe le contenu de la bourse (staff).",
            f"`{PREFIX}sheet money set [@joueur] <montant>`",
        ),
    )
    @admin_only
    async def sheet_money_set(
        ctx: Context,
        member: discord.Member | None = None,
        *,
        amount: str,
    ) -> None:
        result = await get_sheet_for_owner(ctx, member)
        if result is None:
            return
        owner_id, sheet = result

        try:
            sheet.currency = parse_currency(amount)
        except ValueError as exc:
            await command_reply(ctx, str(exc))
            return

        save_owner_sheet(ctx, owner_id, sheet)
        label = target_label(member, sheet)
        await command_reply(
            ctx, f"{label}: wallet set to **{sheet.currency.format()}**."
        )
        await delete_command(ctx)

    @sheet_money_group.command(
        name="add",
        help=command_help(
            "Ajoute des pièces à la bourse (staff).",
            f"`{PREFIX}sheet money add [@joueur] <montant>`",
        ),
    )
    @admin_only
    async def sheet_money_add(
        ctx: Context,
        member: discord.Member | None = None,
        *,
        amount: str,
    ) -> None:
        result = await get_sheet_for_owner(ctx, member)
        if result is None:
            return
        owner_id, sheet = result

        try:
            added = parse_currency(amount)
            sheet.currency.add(added)
        except ValueError as exc:
            await command_reply(ctx, str(exc))
            return

        save_owner_sheet(ctx, owner_id, sheet)
        label = target_label(member, sheet)
        await command_reply(
            ctx,
            f"{label}: added **{added.format()}** → **{sheet.currency.format()}**.",
        )
        await delete_command(ctx)

    @sheet_money_group.command(
        name="spend",
        aliases=["remove"],
        help=command_help(
            "Dépense des pièces de la bourse.",
            f"`{PREFIX}sheet money spend [@joueur] <montant>`",
        ),
    )
    async def sheet_money_spend(
        ctx: Context,
        member: discord.Member | None = None,
        *,
        amount: str,
    ) -> None:
        result = await get_sheet_for_owner(ctx, member)
        if result is None:
            return
        owner_id, sheet = result

        try:
            cost = parse_currency(amount)
        except ValueError as exc:
            await command_reply(ctx, str(exc))
            return

        if not sheet.currency.subtract(cost):
            label = target_label(member, sheet)
            await command_reply(
                ctx,
                f"{label} cannot afford **{cost.format()}** (wallet: **{sheet.currency.format()}**).",
            )
            return

        save_owner_sheet(ctx, owner_id, sheet)
        label = target_label(member, sheet)
        await command_reply(
            ctx,
            f"{label}: spent **{cost.format()}** → **{sheet.currency.format()}**.",
        )
        await delete_command(ctx)

    @sheet_money_group.command(
        name="pay",
        help=command_help(
            "Paie un autre joueur.",
            f"`{PREFIX}sheet money pay [@payeur] @destinataire <montant>`",
        ),
    )
    async def sheet_money_pay(
        ctx: Context,
        payer: discord.Member | None = None,
        recipient: discord.Member | None = None,
        *,
        amount: str,
    ) -> None:
        if recipient is None:
            await command_reply(
                ctx,
                f"Missing recipient. Usage: `{PREFIX}sheet money pay [@payer] @player <amount>`",
            )
            return

        payer_result = await get_sheet_for_owner(ctx, payer)
        if payer_result is None:
            return
        payer_id, payer_sheet = payer_result

        if recipient.id == payer_id:
            await command_reply(ctx, "You cannot pay yourself.")
            return

        guild_id = resolve_guild_id(ctx)
        if guild_id is None:
            await command_reply(ctx, "Cette commande marche seulement sur le serveur.")
            return

        recipient_sheet = get_sheet(user_id=recipient.id, guild_id=guild_id)
        if recipient_sheet is None:
            await command_reply(
                ctx, f"**{recipient.display_name}** n’a pas de fiche."
            )
            return

        try:
            payment = parse_currency(amount)
            transfer_currency(
                guild_id=guild_id,
                payer_id=payer_id,
                recipient_id=recipient.id,
                payment=payment,
            )
        except ValueError as exc:
            await command_reply(ctx, str(exc))
            return

        payer_sheet = get_sheet(user_id=payer_id, guild_id=guild_id)
        recipient_sheet = get_sheet(user_id=recipient.id, guild_id=guild_id)
        if payer_sheet is None or recipient_sheet is None:
            await command_reply(ctx, "Could not load updated wallets.")
            return

        payer_label = target_label(payer, payer_sheet)
        await command_reply(
            ctx,
            (
                f"{payer_label} paid **{payment.format()}** to "
                f"**{recipient_sheet.name}** ({recipient.display_name}).\n"
                f"Payer: **{payer_sheet.currency.format()}** · "
                f"Recipient: **{recipient_sheet.currency.format()}**."
            ),
        )
        await delete_command(ctx)
