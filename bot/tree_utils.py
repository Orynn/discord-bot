from discord import app_commands

_DESC_LIMIT = 100


def clamp_app_command_descriptions(
    tree: app_commands.CommandTree,
    *,
    limit: int = _DESC_LIMIT,
) -> None:
    """Discord rejects command descriptions longer than 100 characters."""

    def clamp(
        command: app_commands.Command | app_commands.Group | app_commands.ContextMenu,
    ) -> None:
        description = getattr(command, "description", None)
        if isinstance(description, str) and len(description) > limit:
            command.description = f"{description[: limit - 1]}…"
        children = getattr(command, "commands", None)
        if children:
            for child in children:
                clamp(child)

    for command in tree.get_commands():
        clamp(command)
