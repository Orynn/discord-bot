import discord

_next_component_id = 0


def fresh_component_id() -> int:
    """Rotate Discord component ids so the client remounts a select after use.

    Discord does not fire a select callback when the chosen value is unchanged,
    so a one-item dropdown cannot be picked again until the component is replaced.
    """
    global _next_component_id
    _next_component_id += 1
    if _next_component_id > 2_147_483_647:
        _next_component_id = 1
    return _next_component_id


def select_menus_from_message(message: discord.Message | None) -> list:
    if message is None:
        return []
    menus = []
    for row in message.components:
        for child in getattr(row, "children", ()) or ():
            if getattr(child, "options", None) is not None:
                menus.append(child)
    return menus


async def replace_message_view(interaction: discord.Interaction, view: discord.ui.View) -> None:
    message = interaction.message
    if message is None:
        return
    try:
        await message.edit(view=view)
    except discord.HTTPException:
        pass
