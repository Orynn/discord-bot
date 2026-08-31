from discord.errors import Forbidden, HTTPException
from discord.ext.commands.bot import Bot
from discord.ext.commands.context import Context

from bot.command_helpers import SERVER_ONLY, command_reply, delete_command
from bot.help_text import command_help
from bot.messaging import send_message
from bot.speech import (
    format_emote,
    format_ooc,
    format_thought,
    format_whisper_private,
    format_whisper_public,
)
from campaign.clock_storage import get_clock
from config import PREFIX
from pc.identity import (
    WHISPER_USAGE,
    resolve_acting_character,
    resolve_whisper_target,
)
from scene.state import (
    SceneState,
    build_scene_embed,
    get_scene,
    mark_absent,
    mark_present,
    parse_scene_set,
    save_scene,
)
from sheets.context import infer_player_id, parse_mention_and_text


def _channel_id(ctx: Context) -> int | None:
    return getattr(ctx.channel, "id", None)


def _maybe_mark_present(ctx: Context, guild_id: int, owner_id: int, name: str) -> None:
    if ctx.guild is None:
        return
    channel_id = _channel_id(ctx)
    if channel_id is None:
        return
    mark_present(
        guild_id=guild_id,
        channel_id=channel_id,
        user_id=owner_id,
        name=name,
    )


def _scene_clock_line(ctx: Context, *, guild_id: int, channel_id: int) -> str | None:
    user_id = infer_player_id(ctx)
    if user_id is None:
        scene = get_scene(guild_id=guild_id, channel_id=channel_id)
        if not scene.present:
            return None
        try:
            user_id = int(next(iter(scene.present)))
        except (TypeError, ValueError):
            return None
    return get_clock(guild_id, user_id).format_line()


async def _require_guild_channel(ctx: Context) -> tuple[int, int] | None:
    if ctx.guild is None:
        await command_reply(ctx, SERVER_ONLY)
        return None
    channel_id = _channel_id(ctx)
    if channel_id is None:
        await command_reply(ctx, SERVER_ONLY)
        return None
    return ctx.guild.id, channel_id


async def show_scene(ctx: Context) -> None:
    scope = await _require_guild_channel(ctx)
    if scope is None:
        return
    guild_id, channel_id = scope
    scene = get_scene(guild_id=guild_id, channel_id=channel_id)
    await send_message(
        ctx,
        embed=build_scene_embed(
            scene,
            clock_line=_scene_clock_line(ctx, guild_id=guild_id, channel_id=channel_id),
            prefix=PREFIX,
        ),
        linkify=False,
        definition_menu=False,
    )
    await delete_command(ctx)


async def send_ic_line(ctx: Context, content: str) -> None:
    await send_message(
        ctx,
        content=content,
        linkify=False,
        definition_menu=False,
    )
    await delete_command(ctx)


def setup_rp(bot: Bot) -> None:
    @bot.hybrid_command(
        name="think",
        aliases=["pense", "thought", "pensée"],
        help=command_help(
            "Pensée intérieure. Les autres peuvent l’ouvrir, ou la laisser secrète.",
            f"`{PREFIX}think <texte>`",
            f"`{PREFIX}pense Je ne lui fais pas confiance.`",
        ),
    )
    async def think_command(ctx: Context, *, text: str) -> None:
        resolved = await resolve_acting_character(ctx)
        if resolved is None:
            return
        guild_id, owner_id, name = resolved
        thought = text.strip()
        if not thought:
            await command_reply(ctx, f"Usage : `{PREFIX}think <texte>`")
            return
        _maybe_mark_present(ctx, guild_id, owner_id, name)
        await send_ic_line(ctx, format_thought(name, thought))

    @bot.hybrid_command(
        name="do",
        aliases=["me", "emote", "agir"],
        help=command_help(
            "Action à la troisième personne, au nom de ton personnage.",
            f"`{PREFIX}do <action>`",
            f"`{PREFIX}me ouvre la porte avec précaution.`",
        ),
    )
    async def do_command(ctx: Context, *, action: str) -> None:
        resolved = await resolve_acting_character(ctx)
        if resolved is None:
            return
        guild_id, owner_id, name = resolved
        cleaned = action.strip()
        if not cleaned:
            await command_reply(ctx, f"Usage : `{PREFIX}do <action>`")
            return
        _maybe_mark_present(ctx, guild_id, owner_id, name)
        await send_ic_line(ctx, format_emote(name, cleaned))

    @bot.hybrid_command(
        name="ooc",
        aliases=["horsjeu"],
        help=command_help(
            "Précise que tu parles hors personnage.",
            f"`{PREFIX}ooc <texte>`",
        ),
    )
    async def ooc_command(ctx: Context, *, text: str) -> None:
        cleaned = text.strip()
        if not cleaned:
            await command_reply(ctx, f"Usage : `{PREFIX}ooc <texte>`")
            return
        await send_message(
            ctx,
            content=format_ooc(cleaned),
            linkify=False,
            definition_menu=False,
        )
        await delete_command(ctx)

    @bot.hybrid_command(
        name="whisper",
        aliases=["chuchote", "murmure", "w"],
        help=command_help(
            "Chuchote en personnage : teaser public, texte en MP aux deux.",
            f"`{PREFIX}whisper @joueur <texte>`",
            f"`{PREFIX}chuchote Aelric Suis-moi.`",
        ),
    )
    async def whisper_command(ctx: Context, *, text: str) -> None:
        scope = await _require_guild_channel(ctx)
        if scope is None:
            return
        guild_id, _channel_id = scope
        resolved = await resolve_acting_character(ctx)
        if resolved is None:
            return
        _, owner_id, speaker = resolved
        member, cleaned = parse_mention_and_text(ctx, text)
        target = resolve_whisper_target(
            guild_id=guild_id,
            text=cleaned if member is not None else text,
            mentioned_id=member.id if member is not None else None,
            mentioned_name=member.display_name if member is not None else None,
        )
        if target is None:
            await command_reply(ctx, WHISPER_USAGE)
            return
        listener_id, listener, secret = target
        if listener_id == owner_id:
            await command_reply(ctx, "Tu ne peux pas te chuchoter à toi-même.")
            return
        _maybe_mark_present(ctx, guild_id, owner_id, speaker)
        await send_message(
            ctx,
            content=format_whisper_public(speaker, listener),
            linkify=False,
            definition_menu=False,
        )
        private = format_whisper_private(speaker, listener, secret)
        warnings: list[str] = []
        try:
            await ctx.author.send(private)
        except (Forbidden, HTTPException):
            warnings.append("Je n’ai pas pu t’envoyer le MP.")
        recipient = ctx.guild.get_member(listener_id) if ctx.guild else None
        if recipient is None:
            warnings.append(f"Je ne trouve pas **{listener}** sur le serveur.")
        else:
            try:
                await recipient.send(private)
            except (Forbidden, HTTPException):
                warnings.append(f"**{listener}** n’accepte pas les MP du serveur.")
        await delete_command(ctx)
        if warnings:
            await command_reply(ctx, " ".join(warnings))

    @bot.hybrid_command(
        name="arrive",
        aliases=["ici"],
        help=command_help(
            "Annonce que ton personnage entre dans la scène de ce salon.",
            f"`{PREFIX}arrive`",
            f"`{PREFIX}arrive par la porte de derrière`",
        ),
    )
    async def arrive_command(ctx: Context, *, note: str = "") -> None:
        scope = await _require_guild_channel(ctx)
        if scope is None:
            return
        resolved = await resolve_acting_character(ctx)
        if resolved is None:
            return
        guild_id, owner_id, name = resolved
        _, channel_id = scope
        mark_present(
            guild_id=guild_id,
            channel_id=channel_id,
            user_id=owner_id,
            name=name,
        )
        action = "arrive" if not note.strip() else f"arrive — {note.strip()}"
        await send_ic_line(ctx, format_emote(name, action))

    @bot.hybrid_command(
        name="leave",
        aliases=["pars", "part"],
        help=command_help(
            "Annonce que ton personnage quitte la scène de ce salon.",
            f"`{PREFIX}leave`",
            f"`{PREFIX}pars vers les docks`",
        ),
    )
    async def leave_command(ctx: Context, *, note: str = "") -> None:
        scope = await _require_guild_channel(ctx)
        if scope is None:
            return
        resolved = await resolve_acting_character(ctx)
        if resolved is None:
            return
        guild_id, owner_id, name = resolved
        _, channel_id = scope
        mark_absent(guild_id=guild_id, channel_id=channel_id, user_id=owner_id)
        action = "s’en va" if not note.strip() else f"s’en va — {note.strip()}"
        await send_ic_line(ctx, format_emote(name, action))

    @bot.hybrid_command(
        name="look",
        aliases=["regarde", "regarder"],
        help=command_help(
            "Sans cible : la carte de scène. Avec une cible : ton perso regarde.",
            f"`{PREFIX}look`",
            f"`{PREFIX}regarde la porte derrière le comptoir`",
        ),
    )
    async def look_command(ctx: Context, *, target: str = "") -> None:
        cleaned = target.strip()
        if not cleaned:
            await show_scene(ctx)
            return
        resolved = await resolve_acting_character(ctx)
        if resolved is None:
            return
        guild_id, owner_id, name = resolved
        _maybe_mark_present(ctx, guild_id, owner_id, name)
        await send_ic_line(ctx, format_emote(name, f"regarde {cleaned}"))

    @bot.hybrid_group(
        name="scene",
        aliases=["scène"],
        invoke_without_command=True,
        help=command_help(
            "Carte de la scène de ce salon : lieu, ambiance, présents.",
            f"`{PREFIX}scene`",
            f"`{PREFIX}scene set La taverne -- feu de cheminée`",
        ),
    )
    async def scene_group(ctx: Context) -> None:
        await show_scene(ctx)

    @scene_group.command(
        name="set",
        help=command_help(
            "Pose le lieu, et l’ambiance après `--`.",
            f"`{PREFIX}scene set <titre> -- <ambiance>`",
            f"`{PREFIX}scene set La crique`",
        ),
    )
    async def scene_set(ctx: Context, *, details: str) -> None:
        scope = await _require_guild_channel(ctx)
        if scope is None:
            return
        title, mood = parse_scene_set(details)
        if not title:
            await command_reply(
                ctx,
                f"Usage : `{PREFIX}scene set <titre> -- <ambiance>`",
            )
            return
        guild_id, channel_id = scope
        scene = get_scene(guild_id=guild_id, channel_id=channel_id)
        scene.title = title
        if mood is not None:
            scene.mood = mood
        save_scene(guild_id=guild_id, channel_id=channel_id, scene=scene)
        await show_scene(ctx)

    @scene_group.command(
        name="mood",
        aliases=["ambiance"],
        help=command_help(
            "Change seulement l’ambiance de la scène.",
            f"`{PREFIX}scene mood <ambiance>`",
        ),
    )
    async def scene_mood(ctx: Context, *, mood: str) -> None:
        scope = await _require_guild_channel(ctx)
        if scope is None:
            return
        cleaned = mood.strip()
        if not cleaned:
            await command_reply(ctx, f"Usage : `{PREFIX}scene mood <ambiance>`")
            return
        guild_id, channel_id = scope
        scene = get_scene(guild_id=guild_id, channel_id=channel_id)
        scene.mood = cleaned
        save_scene(guild_id=guild_id, channel_id=channel_id, scene=scene)
        await show_scene(ctx)

    @scene_group.command(
        name="note",
        help=command_help(
            "Ajoute une note de scène (vide pour l’effacer).",
            f"`{PREFIX}scene note <texte>`",
        ),
    )
    async def scene_note(ctx: Context, *, note: str = "") -> None:
        scope = await _require_guild_channel(ctx)
        if scope is None:
            return
        guild_id, channel_id = scope
        scene = get_scene(guild_id=guild_id, channel_id=channel_id)
        scene.note = note.strip()
        save_scene(guild_id=guild_id, channel_id=channel_id, scene=scene)
        await show_scene(ctx)

    @scene_group.command(
        name="clear",
        aliases=["reset"],
        help=command_help(
            "Efface la carte de scène de ce salon.",
            f"`{PREFIX}scene clear`",
        ),
    )
    async def scene_clear(ctx: Context) -> None:
        scope = await _require_guild_channel(ctx)
        if scope is None:
            return
        guild_id, channel_id = scope
        save_scene(guild_id=guild_id, channel_id=channel_id, scene=SceneState())
        await command_reply(ctx, "Scène effacée.")
        await delete_command(ctx)
