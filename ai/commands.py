import logging
from dataclasses import replace

from discord.ext import commands
from discord.ext.commands.bot import Bot
from discord.ext.commands.context import Context

from ai.context import gather_campaign_lore, gather_recent_messages, lore_query
from ai.gemini import GeminiError, generate_text
from ai.prompt import (
    SYSTEM_NARRATE,
    SYSTEM_NPC,
    SceneBrief,
    build_narrate_prompt,
    build_npc_prompt,
    looks_formatted,
    merge_ai_context,
    parse_ai_request,
    parse_npc_reply,
    strip_roll_asks,
)
from ai.storage import (
    CONTEXT_LIMIT,
    clear_ai_context,
    get_ai_context,
    save_ai_context,
)
from bot.checks import staff_only
from bot.command_helpers import SERVER_ONLY, command_reply, delete_command
from bot.help_commands import tokens_request_help
from bot.help_text import command_help
from bot.messaging import send_message
from bot.speech import format_npc_speech
from campaign.clock_storage import get_clock
from config import GEMINI_COOLDOWN_SECONDS, GEMINI_HISTORY_LIMIT, PREFIX
from image.commands import scene_place
from npc.storage import register_npc_name
from scene.commands import _format_description
from scene.state import get_scene, present_names
from sheets.context import infer_player_id, resolve_guild_id

logger = logging.getLogger(__name__)


def _cooldown():
    return commands.cooldown(
        1, max(1, GEMINI_COOLDOWN_SECONDS), commands.BucketType.channel
    )


def _channel_topic(channel: object) -> str:
    return (getattr(channel, "topic", None) or "").strip()


async def _brief_from_ctx(ctx: Context, *, no_context: bool = False) -> SceneBrief:
    if no_context:
        topic = _channel_topic(ctx.channel)
        return SceneBrief(place=topic or scene_place(ctx.channel) or "")
    guild_id = resolve_guild_id(ctx) or 0
    channel_id = getattr(ctx.channel, "id", None)
    scene = (
        get_scene(guild_id=guild_id, channel_id=channel_id)
        if channel_id is not None and guild_id
        else None
    )
    clock = ""
    if ctx.guild is not None and channel_id is not None:
        user_id = infer_player_id(ctx)
        if user_id is None and scene is not None and scene.present:
            try:
                user_id = int(next(iter(scene.present)))
            except (TypeError, ValueError):
                user_id = None
        if user_id is not None:
            clock = get_clock(ctx.guild.id, user_id).format_line()
    lines = await gather_recent_messages(ctx, limit=GEMINI_HISTORY_LIMIT)
    extra = (
        get_ai_context(guild_id=guild_id, channel_id=channel_id)
        if channel_id is not None
        else ""
    )
    return SceneBrief(
        title=scene.title if scene else "",
        mood=scene.mood if scene else "",
        note=scene.note if scene else "",
        present=tuple(present_names(scene)) if scene else (),
        clock=clock,
        place=scene_place(ctx.channel) or "",
        context=extra,
        lines=tuple(lines[-GEMINI_HISTORY_LIMIT:]),
    )


def _channel_scope(ctx: Context) -> tuple[int, int] | None:
    channel_id = getattr(ctx.channel, "id", None)
    if channel_id is None:
        return None
    guild = getattr(ctx, "guild", None)
    guild_id = resolve_guild_id(ctx) or getattr(guild, "id", None) or 0
    return int(guild_id), int(channel_id)


async def _run_gemini(ctx: Context, *, system: str, user: str) -> str | None:
    if ctx.interaction is not None and not ctx.interaction.response.is_done():
        await ctx.defer()
    try:
        async with ctx.typing():
            return await generate_text(system=system, user=user)
    except GeminiError as exc:
        await command_reply(ctx, str(exc))
        await delete_command(ctx)
        return None
    except Exception:
        logger.exception("Gemini run failed")
        await command_reply(ctx, "Gemini a échoué. Réessaie.")
        await delete_command(ctx)
        return None


def _brief_with_prompt(brief: SceneBrief, prompt: str) -> tuple[SceneBrief, str, bool]:
    instruction, extra, no_context = parse_ai_request(prompt)
    if no_context:
        return brief, instruction, True
    merged = merge_ai_context(brief.context, extra)
    if merged != brief.context:
        brief = replace(brief, context=merged)
    return brief, instruction, False


async def _brief_for_prompt(
    ctx: Context, prompt: str, *extra_query: str
) -> tuple[SceneBrief, str]:
    _instruction, _extra, no_context = parse_ai_request(prompt)
    brief, cleaned, _ = _brief_with_prompt(
        await _brief_from_ctx(ctx, no_context=no_context), prompt
    )
    lore = await gather_campaign_lore(
        ctx.guild,
        lore_query(
            cleaned,
            brief.title,
            brief.mood,
            brief.note,
            brief.place,
            brief.context,
            " ".join(brief.present),
            *extra_query,
        ),
    )
    if lore:
        brief = replace(brief, lore=lore)
    return brief, cleaned


async def _narrate(ctx: Context, instruction: str) -> None:
    brief, cleaned = await _brief_for_prompt(ctx, instruction)
    text = await _run_gemini(
        ctx,
        system=SYSTEM_NARRATE,
        user=build_narrate_prompt(brief, cleaned),
    )
    if text is None:
        return
    text = strip_roll_asks(text)
    if not text:
        await command_reply(
            ctx, "Gemini n’a renvoyé que des demandes de jet. Réessaie."
        )
        await delete_command(ctx)
        return
    guild_id = resolve_guild_id(ctx) or 0
    content = (
        text if looks_formatted(text) else _format_description(text, guild_id=guild_id)
    )
    await send_message(
        ctx,
        content=content,
        linkify=False,
        definition_menu=False,
    )
    await delete_command(ctx)


def setup_ai(bot: Bot) -> None:
    @bot.hybrid_group(
        name="ai",
        aliases=["gemini", "mj"],
        invoke_without_command=True,
        rest_is_raw=True,
        help=command_help(
            "Gemini narre la scène de ce salon (staff).",
            f"`{PREFIX}ai [consigne]`",
            f"`{PREFIX}ai un orage -- Ils ont volé le sceau`",
            f"`{PREFIX}ai --no-context Que peut-il trouver pour allumer un feu`",
            f"`{PREFIX}ai context <texte>` — contexte MJ persistant",
            f"`{PREFIX}ai npc Garret un tavernier méfiant`",
        ),
    )
    @staff_only
    @_cooldown()
    async def ai_group(ctx: Context, *, prompt: str = "") -> None:
        if tokens_request_help(prompt.split()):
            await ctx.send_help(ctx.command)
            return
        await _narrate(ctx, prompt)

    @ai_group.command(
        name="continue",
        aliases=["suite"],
        help=command_help(
            "Continue la scène sans consigne supplémentaire.",
            f"`{PREFIX}ai continue`",
        ),
    )
    @staff_only
    @_cooldown()
    async def ai_continue(ctx: Context) -> None:
        await _narrate(ctx, "")

    @ai_group.command(
        name="context",
        aliases=["contexte", "ctx"],
        help=command_help(
            "Ajoute un contexte MJ persistant pour Gemini dans ce salon.",
            f"`{PREFIX}ai context <texte>`",
            f"`{PREFIX}ai context` — afficher",
            f"`{PREFIX}ai context clear` — effacer",
        ),
    )
    @staff_only
    async def ai_context_command(ctx: Context, *, text: str = "") -> None:
        if tokens_request_help(text.split()):
            await ctx.send_help(ctx.command)
            return
        scope = _channel_scope(ctx)
        if scope is None:
            await command_reply(ctx, SERVER_ONLY)
            await delete_command(ctx)
            return
        guild_id, channel_id = scope
        cleaned = text.strip()
        if cleaned.casefold() in {"clear", "reset", "vide", "efface"}:
            clear_ai_context(guild_id=guild_id, channel_id=channel_id)
            await command_reply(ctx, "Contexte MJ effacé.")
            await delete_command(ctx)
            return
        if not cleaned:
            stored = get_ai_context(guild_id=guild_id, channel_id=channel_id)
            if not stored:
                await command_reply(ctx, "Aucun contexte MJ pour ce salon.")
            else:
                await command_reply(ctx, f"Contexte MJ :\n{stored}")
            await delete_command(ctx)
            return
        save_ai_context(guild_id=guild_id, channel_id=channel_id, text=cleaned)
        if len(cleaned) > CONTEXT_LIMIT:
            await command_reply(
                ctx,
                f"Contexte MJ enregistré (raccourci à {CONTEXT_LIMIT} caractères).",
            )
        else:
            await command_reply(ctx, "Contexte MJ enregistré.")
        await delete_command(ctx)

    @ai_group.command(
        name="npc",
        help=command_help(
            "Fait parler un PNJ via Gemini, dans le format de `;npc`.",
            f"`{PREFIX}ai npc <nom> [consigne]`",
            f"`{PREFIX}ai npc Mira elle refuse de vendre la carte`",
        ),
    )
    @staff_only
    @_cooldown()
    async def ai_npc(ctx: Context, name: str, *, brief: str = "") -> None:
        if ctx.guild is None:
            await command_reply(ctx, SERVER_ONLY)
            await delete_command(ctx)
            return
        guild_id = ctx.guild.id
        cleaned = name.strip()
        if not cleaned:
            await command_reply(ctx, f"Usage : `{PREFIX}ai npc <nom> [consigne]`")
            await delete_command(ctx)
            return
        npc_name = register_npc_name(guild_id=guild_id, name=cleaned)
        scene, instruction = await _brief_for_prompt(ctx, brief, npc_name)
        text = await _run_gemini(
            ctx,
            system=SYSTEM_NPC,
            user=build_npc_prompt(scene, name=npc_name, instruction=instruction),
        )
        if text is None:
            return
        action, dialogue = parse_npc_reply(text)
        if not dialogue:
            await command_reply(ctx, "Gemini n’a pas donné de réplique.")
            await delete_command(ctx)
            return
        await send_message(
            ctx,
            content=format_npc_speech(name=npc_name, dialogue=dialogue, action=action),
            linkify=False,
            definition_menu=False,
        )
        await delete_command(ctx)
