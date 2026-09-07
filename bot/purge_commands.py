from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

import discord
from discord.ext.commands.bot import Bot
from discord.ext.commands.context import Context

from bot.checks import admin_only, guild_only
from bot.command_helpers import command_reply, delete_command
from bot.help_text import command_help
from bot.messaging import send_interaction_message, send_message
from bot.rate_limits import is_rate_limited, retry_on_rate_limit
from config import PREFIX

logger = logging.getLogger(__name__)

_CONFIRM_TIMEOUT = 60.0
_COUNT_CAP = 501
_PURGE_BATCH = 50
_PURGE_ATTEMPTS = 8
_PURGE_WAIT_CAP = 120.0
_BULK_MAX_AGE = timedelta(days=14)


def _is_bulk_deletable(message: discord.Message) -> bool:
    created = getattr(message, "created_at", None)
    if created is None:
        return True
    if created.tzinfo is None:
        created = created.replace(tzinfo=timezone.utc)
    return datetime.now(timezone.utc) - created < _BULK_MAX_AGE


async def estimate_message_count(
    channel: discord.abc.Messageable,
    *,
    before: discord.Message | None = None,
) -> int:
    history = getattr(channel, "history", None)
    if history is None:
        return 0
    count = 0
    async for _message in history(limit=_COUNT_CAP, before=before):
        count += 1
    return count


async def purge_messages(
    channel: discord.abc.Messageable,
    *,
    before: discord.Message | None = None,
) -> list[discord.Message]:
    purge = getattr(channel, "purge", None)
    if not callable(purge):
        raise TypeError(f"Cannot purge messages in {channel!r}")
    deleted: list[discord.Message] = []
    while True:
        batch = await retry_on_rate_limit(
            lambda: purge(
                limit=_PURGE_BATCH,
                before=before,
                oldest_first=False,
                check=_is_bulk_deletable,
            ),
            attempts=_PURGE_ATTEMPTS,
            cap=_PURGE_WAIT_CAP,
        )
        if not batch:
            break
        deleted.extend(batch)
        if len(batch) < _PURGE_BATCH:
            break
    return deleted


def _count_label(count: int) -> str:
    if count >= _COUNT_CAP:
        return f"plus de {_COUNT_CAP - 1}"
    if count == 0:
        return "aucun"
    if count == 1:
        return "1 message"
    return f"{count} messages"


def _build_confirm_embed(
    *, count: int, channel: discord.abc.GuildChannel
) -> discord.Embed:
    label = _count_label(count)
    description = (
        f"Supprimer **{label}** dans {channel.mention} ?\n"
        "Cette action est **irréversible**."
    )
    if count >= _COUNT_CAP:
        description += (
            "\n\nLes messages de plus de 14 jours peuvent prendre plus de temps "
            "ou ne pas être supprimables en masse."
        )
    return discord.Embed(
        title="🗑️ Confirmer la purge",
        description=description,
        color=0xC0392B,
    )


def _resolve_purge_channel(
    interaction: discord.Interaction, channel_id: int
) -> discord.abc.Messageable | None:
    guild = interaction.guild
    if guild is not None:
        found = guild.get_channel(channel_id)
        if found is None:
            getter = getattr(guild, "get_thread", None)
            found = getter(channel_id) if callable(getter) else None
        if found is not None and callable(getattr(found, "purge", None)):
            return found
    client = interaction.client
    cached = getattr(client, "get_channel", lambda _id: None)(channel_id)
    if cached is not None and callable(getattr(cached, "purge", None)):
        return cached
    channel = interaction.channel
    if (
        channel is not None
        and getattr(channel, "id", None) == channel_id
        and callable(getattr(channel, "purge", None))
    ):
        return channel
    return None


class PurgeConfirmView(discord.ui.View):
    def __init__(self, *, invoker_id: int, channel_id: int) -> None:
        super().__init__(timeout=_CONFIRM_TIMEOUT)
        self.invoker_id = invoker_id
        self.channel_id = channel_id

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.invoker_id:
            await interaction.response.send_message(
                "Seule la personne qui a lancé la commande peut répondre.",
                ephemeral=True,
            )
            return False
        return True

    def _disable(self) -> None:
        for item in self.children:
            item.disabled = True

    async def on_timeout(self) -> None:
        self._disable()
        message = getattr(self, "message", None)
        if message is None:
            return
        try:
            await message.edit(
                content="Purge annulée — délai dépassé.",
                embed=None,
                view=self,
            )
        except discord.HTTPException:
            pass

    async def _edit_prompt(
        self, interaction: discord.Interaction, content: str
    ) -> None:
        try:
            await interaction.edit_original_response(
                content=content, embed=None, view=self
            )
        except discord.HTTPException:
            prompt = interaction.message
            if prompt is None:
                return
            try:
                await prompt.edit(content=content, embed=None, view=self)
            except discord.HTTPException:
                pass

    @discord.ui.button(
        label="Confirmer",
        style=discord.ButtonStyle.danger,
        custom_id="purge:confirm",
    )
    async def confirm(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ) -> None:
        self._disable()
        await interaction.response.edit_message(
            content="Purge en cours…",
            embed=None,
            view=self,
        )
        self.stop()
        prompt = interaction.message
        channel = _resolve_purge_channel(interaction, self.channel_id)
        if prompt is None or channel is None:
            await interaction.followup.send("Salon introuvable.", ephemeral=True)
            return
        try:
            deleted = await purge_messages(channel, before=prompt)
        except TypeError:
            await self._edit_prompt(
                interaction, "Je ne peux pas purger les messages ici."
            )
            return
        except discord.Forbidden:
            await self._edit_prompt(
                interaction,
                "Il me faut la permission de **gérer les messages**.",
            )
            return
        except discord.HTTPException as exc:
            if is_rate_limited(exc):
                logger.warning("Purge rate-limited in %s", channel)
            else:
                logger.info("Purge failed in %s: %s", channel, exc)
            await self._edit_prompt(
                interaction,
                "La purge a échoué. Réessaie ou supprime manuellement.",
            )
            return

        leftover = 0
        try:
            leftover = await estimate_message_count(channel, before=prompt)
        except discord.HTTPException:
            leftover = 0
        summary = f"**{len(deleted)}** message(s) supprimé(s)."
        if leftover:
            summary += (
                f" **{_count_label(leftover)}** trop ancien(s) "
                "(plus de 14 jours) restent — Discord refuse le bulk delete."
            )
            await self._edit_prompt(interaction, summary)
            return
        try:
            await prompt.delete()
        except discord.HTTPException:
            await self._edit_prompt(interaction, summary)

    @discord.ui.button(
        label="Annuler",
        style=discord.ButtonStyle.secondary,
        custom_id="purge:cancel",
    )
    async def cancel(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ) -> None:
        self._disable()
        self.stop()
        await interaction.response.edit_message(
            content="Purge annulée.",
            embed=None,
            view=self,
        )


async def _bot_channel_permissions(
    channel: discord.abc.GuildChannel,
) -> discord.Permissions | None:
    guild = getattr(channel, "guild", None)
    if guild is None:
        return None
    me = guild.me
    if me is None:
        return None
    try:
        return channel.permissions_for(me)
    except (AttributeError, discord.ClientException):
        return None


async def _bot_can_manage_messages(channel: discord.abc.GuildChannel) -> bool:
    perms = await _bot_channel_permissions(channel)
    return perms is not None and perms.manage_messages


async def prompt_channel_purge(ctx: Context) -> None:
    if ctx.interaction is not None and not ctx.interaction.response.is_done():
        await ctx.defer()

    channel = ctx.channel
    if not isinstance(channel, discord.abc.GuildChannel):
        await command_reply(ctx, "Cette commande marche seulement sur le serveur.")
        await delete_command(ctx)
        return

    perms = await _bot_channel_permissions(channel)
    if perms is None or not perms.read_message_history:
        await command_reply(
            ctx,
            "Il me faut la permission de **lire l’historique** dans ce salon.",
        )
        await delete_command(ctx)
        return
    if not perms.manage_messages:
        await command_reply(
            ctx,
            "Il me faut la permission de **gérer les messages** dans ce salon.",
        )
        await delete_command(ctx)
        return

    before = ctx.message
    count = await estimate_message_count(channel, before=before)
    if count == 0:
        await command_reply(ctx, "Aucun message à supprimer dans ce salon.")
        await delete_command(ctx)
        return

    view = PurgeConfirmView(invoker_id=ctx.author.id, channel_id=channel.id)
    embed = _build_confirm_embed(count=count, channel=channel)
    if ctx.interaction is not None:
        message = await send_interaction_message(
            ctx.interaction,
            embed=embed,
            view=view,
            linkify=False,
            definition_menu=False,
            edit=True,
        )
    else:
        message = await send_message(
            ctx,
            embed=embed,
            view=view,
            linkify=False,
            definition_menu=False,
        )
    view.message = message
    await delete_command(ctx)


def setup_purge(bot: Bot) -> None:
    @bot.hybrid_command(
        name="purge",
        aliases=["vider", "nettoyer"],
        help=command_help(
            "Supprime tous les messages du salon (confirmation requise).",
            f"`{PREFIX}purge` · `/purge`",
        ),
    )
    @guild_only
    @admin_only
    async def purge_command(ctx: Context) -> None:
        await prompt_channel_purge(ctx)
