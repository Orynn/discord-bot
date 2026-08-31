from discord.ext.commands.bot import Bot
from discord.ext.commands.context import Context

from bot.checks import is_admin
from bot.command_helpers import delete_command
from bot.help_text import build_sheet_help_sections, command_help
from bot.help_view import HelpView
from bot.messaging import send_message
from config import PREFIX
from sheets.commands.core import register_core_commands
from sheets.commands.equipment import register_equipment_commands
from sheets.commands.import_cmd import register_import_commands
from sheets.commands.money import register_money_commands
from sheets.commands.proficiencies import register_proficiency_commands
from sheets.commands.slots import register_slot_commands
from sheets.commands.spells import register_spell_commands
from sheets.commands.status import register_status_commands, setup_status_shortcut


def setup_sheet(bot: Bot) -> None:
    @bot.hybrid_group(
        name="sheet",
        invoke_without_command=True,
        fallback="menu",
        help=command_help(
            "Gère ta fiche de personnage D&D.",
            f"`{PREFIX}sheet`",
            f"Guide : `{PREFIX}help sheet`",
        ),
    )
    async def sheet_group(ctx: Context) -> None:
        view = HelpView(
            title="Character sheet",
            sections=build_sheet_help_sections(
                prefix=PREFIX,
                is_admin=is_admin(ctx),
            ),
        )
        message = await send_message(
            ctx,
            embed=view.current_embed(),
            view=view,
            definition_menu=False,
        )
        view.message = message
        await delete_command(ctx)

    register_core_commands(sheet_group)
    register_import_commands(sheet_group)
    register_money_commands(sheet_group)
    register_equipment_commands(sheet_group)
    register_proficiency_commands(sheet_group)
    register_spell_commands(sheet_group)
    register_slot_commands(sheet_group)
    register_status_commands(sheet_group)
    setup_status_shortcut(bot)
