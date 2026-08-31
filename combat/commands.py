import io
import logging
from pathlib import Path

import discord
from discord.ext.commands.bot import Bot
from discord.ext.commands.context import Context

from bot.checks import admin_only, guild_only
from bot.command_helpers import command_reply, delete_command
from bot.help_text import command_help
from bot.messaging import send_message
from combat.discord_sync import (
    BoardEditResult,
    bind_bot,
    bind_pusher,
    clip_discord_content,
    discord_edit_lock,
    forget_stale_ended,
    get_bot,
    remember_stale_ended,
    take_stale_ended,
)
from combat.display import board_attachments, build_combat_embed
from combat.editor_server import (
    MAP_EDITOR_FILE,
    combat_board_url,
    editor_is_running,
    editor_public_url,
)
from combat.engine import (
    add_combatant,
    conclude_if_over,
    start_combat,
)
from combat.custom_maps import (
    DEFAULT_MAP_HEIGHT,
    DEFAULT_MAP_WIDTH,
    MAX_MAP_BYTES,
    MAX_MAP_HEIGHT,
    MAX_MAP_WIDTH,
    THEMES,
    CustomMapData,
    custom_map_from_state,
    delete_custom_map,
    extract_map_source,
    format_map_text,
    get_custom_map,
    list_custom_maps,
    parse_map_text,
    parse_size_token,
    save_custom_map,
    slugify_map_id,
    validate_map_id,
)
from combat.map import (
    apply_template,
    parse_cell,
    toggle_walls,
)
from combat.scope import PLAYER_COMBAT_ONLY, scope_id_for_channel
from combat.setup import advance_section_clock, ensure_section_fight, parse_start_args
from players.discover import is_sandbox_channel
from combat.storage import (
    CombatState,
    clear_combat,
    get_combat,
    lock_for,
    save_combat,
    set_board_message,
)
from combat.templates import TEMPLATES, lookup_template
from combat.view import build_combat_view
from combat.text import discord_board_unavailable, play_in_browser
from config import PREFIX
from sheets.context import infer_player_id, parse_mention_and_text

logger = logging.getLogger(__name__)

_PLAY_ON_BOARD = command_help(
    "Le tour se joue uniquement dans le navigateur.",
    f"`{PREFIX}combat board`",
)


def _scope_id(ctx: Context) -> int | None:
    assert ctx.guild is not None
    return scope_id_for_channel(guild=ctx.guild, channel=ctx.channel)


async def _require_player_scope(ctx: Context) -> int | None:
    scope_id = _scope_id(ctx)
    if scope_id is None:
        await command_reply(ctx, PLAYER_COMBAT_ONLY)
        await delete_command(ctx)
        return None
    return scope_id


async def _forget_board_message(state: CombatState, *, ended: bool) -> None:
    state.board_message_id = None
    if ended:
        return
    await set_board_message(
        guild_id=state.guild_id,
        scope_id=state.scope_id,
        message_id=None,
    )


async def edit_combat_board_message(
    state: CombatState,
    *,
    content: str | None = None,
    ended: bool = False,
    replace_view: bool = False,
) -> BoardEditResult:
    bot = get_bot()
    if bot is None or state.board_message_id is None:
        return BoardEditResult.SKIPPED
    try:
        channel = bot.get_channel(state.channel_id)
        if channel is None:
            channel = await bot.fetch_channel(state.channel_id)
        if not hasattr(channel, "get_partial_message"):
            return BoardEditResult.FAILED
        message = channel.get_partial_message(state.board_message_id)
        files = [] if ended else board_attachments(state)
        kwargs: dict = {
            "embed": build_combat_embed(state, ended=ended),
            "attachments": files,
        }
        if ended:
            kwargs["view"] = None
        elif replace_view:
            kwargs["view"] = build_combat_view(state)
        clipped = clip_discord_content(content)
        if clipped is not None:
            kwargs["content"] = clipped
        await message.edit(**kwargs)
        return BoardEditResult.UPDATED
    except discord.NotFound:
        await _forget_board_message(state, ended=ended)
        return BoardEditResult.MISSING
    except discord.HTTPException as exc:
        if getattr(exc, "status", None) == 404:
            await _forget_board_message(state, ended=ended)
            return BoardEditResult.MISSING
        if getattr(exc, "status", None) == 429:
            logger.warning("Discord rate-limited combat message edit")
            return BoardEditResult.FAILED
        logger.exception("Failed to edit Discord combat message")
        return BoardEditResult.FAILED


async def _send_board(
    ctx: Context,
    state: CombatState,
    *,
    content: str | None = None,
    combat_over: bool = False,
) -> None:
    ended = combat_over
    if not ended:
        victory = conclude_if_over(state)
        if victory is not None:
            ended = True
            content = (
                f"{content}\n{victory.message}" if content else victory.message
            )
    clipped = clip_discord_content(content)
    async with discord_edit_lock(guild_id=state.guild_id, scope_id=state.scope_id):
        if not ended:
            latest = get_combat(
                guild_id=state.guild_id, scope_id=state.scope_id
            )
            if latest is not None:
                state = latest
        if state.board_message_id:
            result = await edit_combat_board_message(
                state,
                content=clipped,
                ended=ended,
                replace_view=True,
            )
            if result is BoardEditResult.FAILED:
                if ended:
                    remember_stale_ended(state, content=clipped)
                await command_reply(ctx, discord_board_unavailable())
                return
            if ended:
                forget_stale_ended(
                    guild_id=state.guild_id, scope_id=state.scope_id
                )
            if result is BoardEditResult.UPDATED:
                return
        files = board_attachments(state)
        message = await send_message(
            ctx,
            content=clipped,
            embed=build_combat_embed(state, ended=ended),
            view=None if ended else build_combat_view(state),
            definition_menu=False,
            **({"file": files[0]} if files else {}),
        )
        if ended:
            forget_stale_ended(
                guild_id=state.guild_id, scope_id=state.scope_id
            )
            return
        state.board_message_id = message.id
        state.channel_id = message.channel.id
        await set_board_message(
            guild_id=state.guild_id,
            scope_id=state.scope_id,
            message_id=message.id,
            channel_id=message.channel.id,
        )


async def _redirect_play_to_browser(ctx: Context) -> None:
    scope_id = await _require_player_scope(ctx)
    if scope_id is None:
        return
    assert ctx.guild is not None
    state = get_combat(guild_id=ctx.guild.id, scope_id=scope_id)
    if state is None:
        await command_reply(ctx, "Aucun combat en cours. Lance `;combat start` d’abord.")
        await delete_command(ctx)
        return
    await command_reply(ctx, play_in_browser(combat_board_url(ctx.guild.id, scope_id)))
    await delete_command(ctx)


def setup_combat(bot: Bot) -> None:
    bind_bot(bot)
    bind_pusher(edit_combat_board_message)

    @bot.hybrid_group(
        name="combat",
        invoke_without_command=True,
        fallback="menu",
        help=command_help(
            "Carte, déplacements, attaques et cartes de combat.",
            f"`{PREFIX}combat board`",
            f"Guide : `{PREFIX}help combat`",
        ),
    )
    @guild_only
    async def combat_group(ctx: Context) -> None:
        scope_id = await _require_player_scope(ctx)
        if scope_id is None:
            return
        state = get_combat(guild_id=ctx.guild.id, scope_id=scope_id)
        if state is None:
            await command_reply(
                ctx,
                (
                    f"**Combat map** — this player's section only. Guide: `{PREFIX}help combat`\n\n"
                    f"1. `{PREFIX}init add @player` — initiative\n"
                    f"2. `{PREFIX}combat start [monster] [tavern] [2h]` — *(admin)*\n"
                    f"3. `{PREFIX}combat board` — ouvrir le plateau navigateur"
                ),
            )
        else:
            await _send_board(ctx, state)
        await delete_command(ctx)

    @combat_group.command(
        name="start",
        help=command_help(
            "Lance le combat de cette section (staff).",
            f"`{PREFIX}combat start [monstre] [tavern] [2h]`",
        ),
    )
    @guild_only
    @admin_only
    async def combat_start(ctx: Context, *, args: str = "") -> None:
        scope_id = await _require_player_scope(ctx)
        if scope_id is None:
            return
        monster_name, minutes, map_id = parse_start_args(
            args, guild_id=ctx.guild.id
        )
        player_id = infer_player_id(ctx)
        clock_note = None
        try:
            async with lock_for(guild_id=ctx.guild.id, scope_id=scope_id):
                await ensure_section_fight(
                    guild_id=ctx.guild.id,
                    channel_id=ctx.channel.id,
                    scope_id=scope_id,
                    player_id=player_id,
                    monster_name=monster_name,
                )
                state = await start_combat(
                    guild_id=ctx.guild.id,
                    channel_id=ctx.channel.id,
                    scope_id=scope_id,
                    map_id=map_id,
                    restore_hp=is_sandbox_channel(ctx.channel),
                )
            if minutes and player_id is not None:
                clock_note = advance_section_clock(
                    guild_id=ctx.guild.id,
                    user_id=player_id,
                    minutes=minutes,
                )
        except ValueError as exc:
            await command_reply(ctx, str(exc))
            await delete_command(ctx)
            return

        await _send_board(ctx, state, content=clock_note)
        await delete_command(ctx)

    @combat_group.command(
        name="board",
        help=command_help(
            "Ouvre le plateau de combat dans le navigateur.",
            f"`{PREFIX}combat board`",
        ),
    )
    @guild_only
    async def combat_board(ctx: Context) -> None:
        scope_id = await _require_player_scope(ctx)
        if scope_id is None:
            return
        assert ctx.guild is not None
        state = get_combat(guild_id=ctx.guild.id, scope_id=scope_id)
        if state is None:
            stale = take_stale_ended(guild_id=ctx.guild.id, scope_id=scope_id)
            if stale is None:
                await command_reply(
                    ctx, "Aucun combat en cours. Lance `;combat start` d’abord."
                )
                await delete_command(ctx)
                return
            snapshot, note = stale
            await _send_board(
                ctx, snapshot, content=note, combat_over=True
            )
            await delete_command(ctx)
            return

        await _send_board(ctx, state)
        await delete_command(ctx)

    @combat_group.command(
        name="hand",
        help=_PLAY_ON_BOARD,
    )
    @guild_only
    async def combat_hand(ctx: Context) -> None:
        await _redirect_play_to_browser(ctx)

    @combat_group.command(
        name="play",
        help=_PLAY_ON_BOARD,
    )
    @guild_only
    async def combat_play(ctx: Context, card: str = "", *, target: str = "") -> None:
        await _redirect_play_to_browser(ctx)

    @combat_group.command(
        name="move",
        help=_PLAY_ON_BOARD,
    )
    @guild_only
    async def combat_move(ctx: Context, *, dest: str = "") -> None:
        await _redirect_play_to_browser(ctx)

    @combat_group.command(
        name="attack",
        help=_PLAY_ON_BOARD,
    )
    @guild_only
    async def combat_attack(ctx: Context, *, target: str = "") -> None:
        await _redirect_play_to_browser(ctx)

    @combat_group.command(
        name="map",
        help=command_help(
            "Thèmes, murs et cartes perso.",
            f"`{PREFIX}combat map [tavern|import|editor|…]`",
            f"`{PREFIX}combat map tavern` — appliquer un thème",
            f"`{PREFIX}combat map import` — coller une carte de l’éditeur",
        ),
    )
    @guild_only
    @admin_only
    async def combat_map(ctx: Context, *, args: str = "") -> None:
        scope_id = await _require_player_scope(ctx)
        if scope_id is None:
            return
        assert ctx.guild is not None
        parts = args.split()
        verb = parts[0].lower() if parts else "list"
        rest = " ".join(parts[1:]).strip()
        try:
            if verb in {"", "list"}:
                await command_reply(ctx, _map_list_message(ctx.guild.id))
            elif verb == "help":
                await command_reply(ctx, _map_help_message())
            elif verb == "editor":
                await _send_map_editor(ctx)
            elif verb == "show":
                await command_reply(ctx, _map_show_message(ctx.guild.id, rest))
            elif verb == "export":
                await _export_custom_map(ctx, rest)
            elif verb == "delete" or verb == "remove":
                await command_reply(ctx, _delete_custom_map_message(ctx.guild.id, rest))
            elif verb == "import":
                await command_reply(ctx, await _import_custom_map(ctx, rest))
            elif verb == "new":
                await command_reply(ctx, await _new_custom_map(ctx, rest))
            elif verb == "save":
                await command_reply(
                    ctx, _save_current_map(ctx.guild.id, scope_id, rest)
                )
            elif verb == "wall":
                await _toggle_map_walls(ctx, scope_id, rest)
                return
            else:
                await _apply_named_map(ctx, scope_id, verb)
                return
        except ValueError as exc:
            await command_reply(ctx, str(exc))
        await delete_command(ctx)

    @combat_group.command(
        name="end",
        help=command_help("Arrête le combat de cette section.", f"`{PREFIX}combat end`"),
    )
    @guild_only
    @admin_only
    async def combat_end(ctx: Context) -> None:
        scope_id = await _require_player_scope(ctx)
        if scope_id is None:
            return
        clear_combat(guild_id=ctx.guild.id, scope_id=scope_id)
        await command_reply(ctx, "Combat terminé.")
        await delete_command(ctx)

    @combat_group.command(
        name="add",
        help=command_help(
            "Ajoute un combattant en cours de combat.",
            f"`{PREFIX}combat add <nom> [pv]`",
            f"`{PREFIX}combat add Gobelin` — profil SRD",
            f"`{PREFIX}combat add Nom 30` — PV perso",
        ),
    )
    @guild_only
    @admin_only
    async def combat_add(
        ctx: Context,
        member: discord.Member | None = None,
        *,
        args: str = "",
    ) -> None:
        scope_id = await _require_player_scope(ctx)
        if scope_id is None:
            return
        state = get_combat(guild_id=ctx.guild.id, scope_id=scope_id)
        if state is None:
            await command_reply(ctx, "Aucun combat en cours.")
            await delete_command(ctx)
            return

        if member is None:
            member, args = parse_mention_and_text(ctx, args)
        else:
            _, args = parse_mention_and_text(ctx, args)
        if member is not None:
            parts = (
                args.replace(f"<@{member.id}>", "")
                .replace(f"<@!{member.id}>", "")
                .strip()
                .rsplit(maxsplit=1)
            )
            hp = int(parts[-1]) if parts and parts[-1].isdigit() else None
            try:
                combatant = await add_combatant(
                    state,
                    name=member.display_name,
                    hp=hp,
                    user_id=member.id,
                )
            except ValueError as exc:
                await command_reply(ctx, str(exc))
                await delete_command(ctx)
                return
        else:
            cleaned = args.strip()
            if not cleaned:
                await command_reply(ctx, f"Usage : `{PREFIX}combat add <nom> [pv]`")
                await delete_command(ctx)
                return
            parts = cleaned.rsplit(maxsplit=1)
            if len(parts) == 2 and parts[1].isdigit():
                monster_name, hp = parts[0], int(parts[1])
            else:
                monster_name, hp = cleaned, None
            try:
                combatant = await add_combatant(state, name=monster_name, hp=hp)
            except ValueError as exc:
                await command_reply(ctx, str(exc))
                await delete_command(ctx)
                return

        if combatant.user_id is None:
            traits = f" · {', '.join(combatant.traits)}" if combatant.traits else ""
            reply = (
                f"**{combatant.name}** ajouté{traits} avec {len(combatant.hand)} cartes."
            )
        else:
            reply = f"**{combatant.name}** ajouté ({combatant.hp} PV) avec {len(combatant.hand)} cartes."
        await command_reply(ctx, reply)
        await delete_command(ctx)

    @combat_group.command(
        name="pass", help=_PLAY_ON_BOARD
    )
    @guild_only
    async def combat_pass(ctx: Context) -> None:
        await _redirect_play_to_browser(ctx)


def _map_help_message() -> str:
    return (
        f"**Cartes de combat** ({DEFAULT_MAP_WIDTH}×{DEFAULT_MAP_HEIGHT} de base, "
        f"jusqu’à {MAX_MAP_WIDTH}×{MAX_MAP_HEIGHT}, `.` sol, `#` mur)\n"
        f"`{PREFIX}combat map` — liste\n"
        f"`{PREFIX}combat map tavern` — appliquer (combat en cours)\n"
        f"`{PREFIX}combat map wall C3 D4` — poser / retirer des murs\n"
        f"`{PREFIX}combat map save crypt Crypte dungeon` — enregistrer le plateau\n"
        f"`{PREFIX}combat map new crypt Crypte 12x12 dungeon` — carte vide\n"
        f"`{PREFIX}combat map import [crypt]` — fichier `.map` / `.json` ou bloc ```\n"
        f"`{PREFIX}combat map editor` — lien vers l’éditeur (tant qu’Arkann tourne)\n"
        f"`{PREFIX}combat map export crypt` · `{PREFIX}combat map show crypt`\n"
        f"`{PREFIX}combat map delete crypt`\n"
        f"`{PREFIX}combat start Gobelin crypt` — démarrer sur une carte perso"
    )


def _map_list_message(guild_id: int) -> str:
    built = " · ".join(f"`{key}` {item.label}" for key, item in TEMPLATES.items())
    customs = list_custom_maps(guild_id=guild_id)
    if customs:
        custom = "\n".join(
            f"• `{entry.map_id}` — {entry.label} "
            f"({entry.width}×{entry.height}, {entry.theme})"
            for entry in customs
        )
    else:
        custom = "*(aucune — importe un `.map` ou enregistre le plateau)*"
    return (
        f"**De base** — {built}\n"
        f"**Perso**\n{custom}\n"
        f"`{PREFIX}combat map help` pour créer / importer."
    )


def _map_data_or_builtin(guild_id: int, raw_id: str) -> CustomMapData:
    key = slugify_map_id(raw_id)
    if key in TEMPLATES:
        template = TEMPLATES[key]
        return CustomMapData(
            map_id=template.map_id,
            label=template.label,
            blocked=template.blocked,
            pc_column=template.pc_column,
            npc_column=template.npc_column,
            theme=template.theme,
            width=template.width,
            height=template.height,
        )
    data = get_custom_map(guild_id=guild_id, map_id=key)
    if data is None:
        raise ValueError(f"Carte inconnue `{raw_id}`.")
    return data


def _map_show_message(guild_id: int, raw_id: str) -> str:
    if not raw_id.strip():
        raise ValueError(f"Usage : `{PREFIX}combat map show crypt`.")
    data = _map_data_or_builtin(guild_id, raw_id)
    return f"**{data.label}** (`{data.map_id}`)\n```\n{format_map_text(data)}```"


def _delete_custom_map_message(guild_id: int, raw_id: str) -> str:
    if not raw_id.strip():
        raise ValueError(f"Usage : `{PREFIX}combat map delete crypt`.")
    key = slugify_map_id(raw_id)
    if key in TEMPLATES:
        raise ValueError("Impossible de supprimer une carte de base.")
    if not delete_custom_map(guild_id=guild_id, map_id=key):
        raise ValueError(f"Carte perso `{key}` introuvable.")
    return f"Carte **{key}** supprimée."


def _parse_map_save_args(
    text: str,
) -> tuple[str, str | None, str | None, tuple[int, int] | None]:
    parts = text.split()
    if not parts:
        raise ValueError(
            f"Usage : `{PREFIX}combat map save crypt [nom] [12x12] [dungeon]`."
        )
    map_id = validate_map_id(parts[0])
    if map_id in TEMPLATES:
        raise ValueError("Les cartes de base ne peuvent pas être écrasées.")
    theme = None
    size = None
    label_parts: list[str] = []
    for part in parts[1:]:
        parsed = parse_size_token(part)
        if parsed is not None and size is None:
            size = parsed
        elif part.lower() in THEMES and theme is None:
            theme = part.lower()
        else:
            label_parts.append(part)
    label = " ".join(label_parts) or None
    return map_id, label, theme, size


def _save_current_map(guild_id: int, scope_id: int, text: str) -> str:
    map_id, label, theme, _size = _parse_map_save_args(text)
    state = get_combat(guild_id=guild_id, scope_id=scope_id)
    if state is None:
        raise ValueError(
            "Aucun combat en cours. "
            f"`{PREFIX}combat map new {map_id}` ou `{PREFIX}combat map import`."
        )
    data = custom_map_from_state(state, map_id=map_id, label=label, theme=theme)
    save_custom_map(guild_id=guild_id, data=data)
    return f"Carte **{data.label}** enregistrée (`{data.map_id}`)."


async def _read_map_upload(ctx: Context) -> tuple[str | None, str | None]:
    attachment = None
    if ctx.message is not None and ctx.message.attachments:
        attachment = ctx.message.attachments[0]
    if attachment is None:
        return None, None
    if attachment.size and attachment.size > MAX_MAP_BYTES:
        raise ValueError("Fichier trop lourd (32 Ko max).")
    text = (await attachment.read()).decode("utf-8-sig")
    stem = slugify_map_id(Path(attachment.filename or "carte").stem)
    return text, stem or None


async def _import_custom_map(ctx: Context, rest: str) -> str:
    assert ctx.guild is not None
    uploaded, stem = await _read_map_upload(ctx)
    tokens = rest.split(maxsplit=1)
    named = ""
    body = rest
    if tokens:
        candidate = slugify_map_id(tokens[0])
        if candidate and tokens[0][0].isalnum():
            named = candidate
            body = tokens[1] if len(tokens) > 1 else ""
    source = uploaded or extract_map_source(body) or extract_map_source(rest)
    if source is None:
        raise ValueError(
            "Joins un fichier `.map` / `.json`, ou colle une grille :\n"
            "```\n# id: crypt\n# theme: dungeon\n........\n.##..##.\n"
            ".#....#.\n........\n........\n........\n........\n........\n```"
        )
    data = parse_map_text(source, default_id=named or stem)
    if data.map_id in TEMPLATES:
        raise ValueError("Les cartes de base ne peuvent pas être écrasées.")
    save_custom_map(guild_id=ctx.guild.id, data=data)
    return f"Carte **{data.label}** importée (`{data.map_id}`)."


async def _new_custom_map(ctx: Context, rest: str) -> str:
    assert ctx.guild is not None
    uploaded, stem = await _read_map_upload(ctx)
    if uploaded is not None:
        map_id, label, theme, _size = _parse_map_save_args(rest or stem or "custom")
        parsed = parse_map_text(uploaded, default_id=map_id)
        data = CustomMapData(
            map_id=map_id,
            label=label or parsed.label,
            blocked=parsed.blocked,
            pc_column=parsed.pc_column,
            npc_column=parsed.npc_column,
            theme=theme or parsed.theme,
            width=parsed.width,
            height=parsed.height,
        )
        save_custom_map(guild_id=ctx.guild.id, data=data)
        return f"Carte **{data.label}** importée (`{data.map_id}`)."
    map_id, label, theme, size = _parse_map_save_args(rest)
    width, height = size or (DEFAULT_MAP_WIDTH, DEFAULT_MAP_HEIGHT)
    data = CustomMapData(
        map_id=map_id,
        label=label or map_id.replace("-", " ").title(),
        blocked=(),
        theme=theme or "arena",
        width=width,
        height=height,
        npc_column=max(1, width - 2),
    )
    save_custom_map(guild_id=ctx.guild.id, data=data)
    return (
        f"Carte vide **{data.label}** (`{data.map_id}`). "
        f"Applique-la avec `{PREFIX}combat map {data.map_id}`, "
        f"puis `{PREFIX}combat map wall C3` et `{PREFIX}combat map save {data.map_id}`."
    )


async def _send_map_editor(ctx: Context) -> None:
    url = editor_public_url() if editor_is_running() else None
    if url:
        await command_reply(
            ctx,
            f"Éditeur de cartes : {url}\n"
            f"Peins le plateau, télécharge le `.map`, puis `{PREFIX}combat map import`.",
        )
        return
    if not MAP_EDITOR_FILE.is_file():
        raise ValueError("Éditeur introuvable (`tools/map-editor.html`).")
    await send_message(
        ctx,
        content=(
            "Éditeur hors-ligne. Ouvre le HTML, peins le plateau, "
            f"puis `{PREFIX}combat map import` avec le fichier `.map`."
        ),
        file=discord.File(MAP_EDITOR_FILE, filename="arkann-map-editor.html"),
        definition_menu=False,
    )


async def _export_custom_map(ctx: Context, raw_id: str) -> None:
    assert ctx.guild is not None
    if not raw_id.strip():
        raise ValueError(f"Usage : `{PREFIX}combat map export crypt`.")
    data = _map_data_or_builtin(ctx.guild.id, raw_id)
    buffer = io.BytesIO(format_map_text(data).encode("utf-8"))
    await send_message(
        ctx,
        content=f"Carte **{data.label}** (`{data.map_id}`).",
        file=discord.File(buffer, filename=f"{data.map_id}.map"),
        definition_menu=False,
    )


async def _toggle_map_walls(ctx: Context, scope_id: int, text: str) -> None:
    assert ctx.guild is not None
    tokens = text.split()
    if not tokens:
        raise ValueError(f"Usage : `{PREFIX}combat map wall C3 D4`.")
    async with lock_for(guild_id=ctx.guild.id, scope_id=scope_id):
        state = get_combat(guild_id=ctx.guild.id, scope_id=scope_id)
        if state is None:
            raise ValueError("Aucun combat en cours.")
        cells: list[tuple[int, int]] = []
        for token in tokens:
            cell = parse_cell(token, state)
            if cell is None:
                raise ValueError(f"Case inconnue `{token}`. Exemple : `C3`.")
            cells.append(cell)
        note = toggle_walls(state, cells)
        save_combat(state)
    await _send_board(ctx, state, content=note)
    await delete_command(ctx)


async def _apply_named_map(ctx: Context, scope_id: int, map_id: str) -> None:
    assert ctx.guild is not None
    async with lock_for(guild_id=ctx.guild.id, scope_id=scope_id):
        state = get_combat(guild_id=ctx.guild.id, scope_id=scope_id)
        if state is None:
            raise ValueError("Aucun combat en cours. Lance `;combat start` d’abord.")
        apply_template(state, map_id)
        save_combat(state)
    label = lookup_template(state.map_id, guild_id=ctx.guild.id).label
    await _send_board(ctx, state, content=f"Carte : **{label}**.")
    await delete_command(ctx)
