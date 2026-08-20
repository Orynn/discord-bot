import discord
from discord.ext.commands import Group
from discord.ext.commands.context import Context

from bot.checks import is_admin
from bot.command_helpers import command_reply, delete_command
from config import PREFIX
from sheets.context import format_skill_name, get_sheet_for_owner, save_owner_sheet, target_label
from sheets.data import ABILITIES, lookup_skill


def register_proficiency_commands(sheet_group: Group) -> None:
    @sheet_group.group(
        name="prof",
        invoke_without_command=True,
        fallback="help",
        help="Manage save and skill proficiencies.",
    )
    async def sheet_prof_group(ctx: Context) -> None:
        admin_hint = " [@player]" if is_admin(ctx) else ""
        await command_reply(
            ctx,
            (
                f"Usage:\n"
                f"`{PREFIX}sheet prof save{admin_hint} <ability>` — toggle save proficiency\n"
                f"`{PREFIX}sheet prof skill{admin_hint} <skill> [expertise]` — toggle skill proficiency"
            ),
        )
        await delete_command(ctx)

    @sheet_prof_group.command(
        name="save",
        help=f"Toggle saving throw proficiency. Usage: `{PREFIX}sheet prof save [@player] <ability>`",
    )
    async def sheet_prof_save(
        ctx: Context,
        member: discord.Member | None = None,
        ability: str = "",
    ) -> None:
        result = await get_sheet_for_owner(ctx, member)
        if result is None:
            return
        owner_id, sheet = result

        if not ability:
            await command_reply(
                ctx,
                f"Missing ability. Usage: `{PREFIX}sheet prof save [@player] <ability>`",
            )
            return

        ability = ability.lower()
        if ability not in ABILITIES:
            await command_reply(ctx, f"Unknown ability. Choose from: {', '.join(ABILITIES)}")
            return

        added = sheet.toggle_save_proficiency(ability=ability)
        save_owner_sheet(ctx, owner_id, sheet)
        status = "added" if added else "removed"
        label = target_label(member, sheet)
        await command_reply(ctx, f"{label}: save proficiency for **{ability.upper()}** {status}.")
        await delete_command(ctx)

    @sheet_prof_group.command(
        name="skill",
        help=(
            f"Toggle skill proficiency or expertise. "
            f"Usage: `{PREFIX}sheet prof skill [@player] <skill> [expertise]`"
        ),
    )
    async def sheet_prof_skill(
        ctx: Context,
        member: discord.Member | None = None,
        skill: str = "",
        expertise: str | None = None,
    ) -> None:
        result = await get_sheet_for_owner(ctx, member)
        if result is None:
            return
        owner_id, sheet = result

        if not skill:
            await command_reply(
                ctx,
                f"Missing skill. Usage: `{PREFIX}sheet prof skill [@player] <skill> [expertise]`",
            )
            return

        matched = lookup_skill(skill)
        if matched is None:
            await command_reply(
                ctx,
                "Unknown skill. Use English (`stealth`) or French (`discrétion`).",
            )
            return
        skill = matched

        label = target_label(member, sheet)
        skill_label = format_skill_name(skill)
        if expertise and expertise.lower() == "expertise":
            try:
                added = sheet.toggle_skill_expertise(skill=skill)
            except ValueError as exc:
                await command_reply(ctx, str(exc))
                return
            status = "added" if added else "removed"
            await command_reply(ctx, f"{label}: expertise for **{skill_label}** {status}.")
        else:
            added = sheet.toggle_skill_proficiency(skill=skill)
            status = "added" if added else "removed"
            await command_reply(ctx, f"{label}: proficiency for **{skill_label}** {status}.")

        save_owner_sheet(ctx, owner_id, sheet)
        await delete_command(ctx)
