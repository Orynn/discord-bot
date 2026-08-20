import asyncio

import discord
from discord import app_commands
from discord.ext.commands.bot import Bot
from discord.ext.commands.context import Context

from bot.checks import admin_only, guild_only
from bot.command_helpers import command_reply, delete_command
from bot.help_text import HELP_COLOR, HELP_LOOKUP_COLOR
from bot.messaging import send_message
from campaign.forums import (
    CampaignForumError,
    ensure_campaign_category,
    format_forum_channel_name,
    format_forum_list,
    list_campaign_forums,
    locate_campaign_thread,
    match_campaign_forum,
    normalize_section_key,
    parse_post_spec,
    post_jump_markdown,
    require_manage_channels,
    starter_content,
)
from campaign.audit import audit_campaign_posts, audit_report_file
from campaign.importing import import_wiki_cluster, repair_placeholder_posts
from campaign.inventory import write_channel_export
from campaign.lore import (
    CampaignEntry,
    clear_campaign_cache,
    fetch_campaign_entries,
    filter_campaign_entries,
)
from campaign.moving import forum_for_thread, move_campaign_post
from campaign.parchment import ParchmentError, parse_document_text, render_parchment
from campaign.wiki import (
    WikiError,
    WikiNotFoundError,
    WikiPage,
    fetch_wiki_page,
    split_import_query,
    suggest_pages,
)
from config import PREFIX

_EMBED_DESCRIPTION_LIMIT = 4000


def _chunk_text(text: str, *, limit: int = _EMBED_DESCRIPTION_LIMIT) -> list[str]:
    if len(text) <= limit:
        return [text]

    chunks: list[str] = []
    remaining = text
    while remaining:
        if len(remaining) <= limit:
            chunks.append(remaining)
            break
        split_at = remaining.rfind("\n", 0, limit)
        if split_at < limit // 2:
            split_at = limit
        chunks.append(remaining[:split_at].rstrip())
        remaining = remaining[split_at:].lstrip()
    return chunks


def _index_embeds(entries: list[CampaignEntry]) -> list[discord.Embed]:
    by_section: dict[str, list[CampaignEntry]] = {}
    for entry in entries:
        by_section.setdefault(entry.section, []).append(entry)

    lines: list[str] = []
    for section, section_entries in by_section.items():
        lines.append(f"**{section}** ({len(section_entries)})")
        for entry in section_entries:
            lines.append(f"• {entry.link}")
        lines.append("")

    embeds: list[discord.Embed] = []
    for index, chunk in enumerate(_chunk_text("\n".join(lines).strip())):
        title = "📜 Campaign — index" if index == 0 else f"📜 Campaign — index ({index + 1})"
        embeds.append(
            discord.Embed(
                title=title,
                description=chunk,
                color=HELP_COLOR,
            )
        )
    return embeds


def _entry_embeds(entry: CampaignEntry) -> list[discord.Embed]:
    body = entry.body.strip() if entry.body.strip() else "_(no text in this thread)_"
    chunks = _chunk_text(body)
    embeds: list[discord.Embed] = []
    for index, chunk in enumerate(chunks):
        embed = discord.Embed(
            title=f"📖 {entry.title}" if index == 0 else f"📖 {entry.title} (suite)",
            url=entry.jump_url if index == 0 else None,
            description=chunk,
            color=HELP_LOOKUP_COLOR,
        )
        if index == 0:
            embed.set_author(name=f"📂 {entry.section}")
        embeds.append(embed)
    return embeds


def _match_list_embed(query: str, matched: list[CampaignEntry]) -> discord.Embed:
    lines = [
        "Précise ta recherche pour voir le détail :",
        *(f"• **{entry.section}** — {entry.link}" for entry in matched),
    ]
    return discord.Embed(
        title=f"🔎 Campaign — {len(matched)} result(s) for “{query}”",
        description="\n".join(lines),
        color=HELP_COLOR,
    )


async def _send_embeds(ctx: Context, embeds: list[discord.Embed]) -> None:
    # Discord allows up to 10 embeds per message.
    for start in range(0, len(embeds), 10):
        batch = embeds[start : start + 10]
        await send_message(ctx, embeds=batch, definition_menu=False, linkify=False)


async def _run_campaign_lookup(ctx: Context, query: str | None) -> None:
    assert ctx.guild is not None

    async with ctx.typing():
        entries = await fetch_campaign_entries(ctx.guild)

    if not entries:
        await command_reply(
            ctx,
            "No CAMPAIGN forums found yet. Restart the bot to recreate the category, "
            "or use `;campaign import Eauprofonde`.",
        )
        await delete_command(ctx)
        return

    if not query or not query.strip():
        await _send_embeds(ctx, _index_embeds(entries))
        await delete_command(ctx)
        return

    matched = filter_campaign_entries(entries, query)
    if not matched:
        await command_reply(
            ctx,
            f"No campaign entry matched `{query.strip()}`.\n"
            f"Try `{PREFIX}campaign` for the full index.",
        )
        await delete_command(ctx)
        return

    if len(matched) == 1:
        await _send_embeds(ctx, _entry_embeds(matched[0]))
        await delete_command(ctx)
        return

    if len(matched) > 3:
        await _send_embeds(ctx, [_match_list_embed(query.strip(), matched)])
        await delete_command(ctx)
        return

    await command_reply(
        ctx,
        f"**🔎 Campaign — {len(matched)} result(s) for “{query.strip()}”**",
    )
    for entry in matched:
        await _send_embeds(ctx, _entry_embeds(entry))

    await delete_command(ctx)


async def _collect_post_files(
    ctx: Context,
    extra: discord.Attachment | None,
) -> list[discord.File]:
    files: list[discord.File] = []
    seen: set[int] = set()
    attachments: list[discord.Attachment] = []
    if extra is not None:
        attachments.append(extra)
    if ctx.message is not None:
        attachments.extend(ctx.message.attachments)
    for attachment in attachments:
        if attachment.id in seen:
            continue
        seen.add(attachment.id)
        files.append(await attachment.to_file())
        if len(files) >= 10:
            break
    return files


def _created_embed(*, title: str, description: str) -> discord.Embed:
    return discord.Embed(title=title, description=description, color=HELP_COLOR)


def _wiki_preview_embeds(page: WikiPage) -> list[discord.Embed]:
    parts = [page.summary]
    if page.body:
        parts.append(page.body)
    text = "\n\n".join(part for part in parts if part).strip() or f"**{page.title}**"
    chunks = _chunk_text(text)

    embeds: list[discord.Embed] = []
    for index, chunk in enumerate(chunks[:10]):
        embed = discord.Embed(
            title=f"📖 {page.title}" if index == 0 else f"📖 {page.title} (suite)",
            url=page.url if index == 0 else None,
            description=chunk,
            color=HELP_LOOKUP_COLOR,
        )
        if index == 0:
            embed.add_field(
                name="📂 Forum",
                value=f"`{page.section}` — `{PREFIX}campaign import {page.title}`",
                inline=False,
            )
            if page.suggested_from:
                embed.add_field(
                    name="🔎 Suggestion",
                    value=(
                        f"Pas de page **{page.suggested_from}** — "
                        f"affichage de **{page.title}**."
                    ),
                    inline=False,
                )
            embed.set_footer(text="Wiki Le Monde des Royaumes Oubliés · CC BY-SA")
            if page.thumbnail_url:
                embed.set_thumbnail(url=page.thumbnail_url)
        embeds.append(embed)
    return embeds


async def _forum_section_choices(
    interaction: discord.Interaction,
    current: str,
) -> list[app_commands.Choice[str]]:
    if interaction.guild is None:
        return []
    needle = current.casefold().strip()
    choices: list[app_commands.Choice[str]] = []
    for forum in list_campaign_forums(interaction.guild):
        label = forum.name[:100]
        key = normalize_section_key(forum.name)
        if needle and needle not in forum.name.casefold() and needle not in key:
            continue
        choices.append(app_commands.Choice(name=label, value=key[:100]))
        if len(choices) >= 25:
            break
    return choices


async def _wiki_title_choices(current: str) -> list[app_commands.Choice[str]]:
    if len(current.strip()) < 2:
        return []
    try:
        titles = await suggest_pages(current)
    except WikiError:
        return []
    return [app_commands.Choice(name=title[:100], value=title[:100]) for title in titles[:25]]


def setup_campaign(bot: Bot) -> None:
    @bot.hybrid_group(
        name="campaign",
        aliases=["lore", "camp"],
        invoke_without_command=True,
        fallback="search",
        help="Browse or create CAMPAIGN forum lore.",
    )
    @guild_only
    @admin_only
    async def campaign_group(ctx: Context, *, query: str | None = None) -> None:
        await _run_campaign_lookup(ctx, query)

    @campaign_group.command(
        name="post",
        help="Create a CAMPAIGN forum post. `post lieux Title -- body`",
    )
    @app_commands.describe(
        section="Forum name, e.g. lieux, pnj, quêtes",
        details="Post title, optionally `-- body text`",
        file="Optional image (shown as the post thumbnail)",
    )
    @guild_only
    @admin_only
    async def campaign_post(
        ctx: Context,
        section: str,
        *,
        details: str,
        file: discord.Attachment | None = None,
    ) -> None:
        assert ctx.guild is not None
        try:
            spec = parse_post_spec(section, details)
            forums = list_campaign_forums(ctx.guild)
            forum = match_campaign_forum(forums, spec.section)
            if forum is None:
                available = format_forum_list(forums)
                raise CampaignForumError(
                    f"No CAMPAIGN forum matched `{spec.section}`.\nForums: {available}"
                )
            files = await _collect_post_files(ctx, file)
            content = spec.body.strip()[:2000] if spec.body.strip() else None
            if content is None and not files:
                content = starter_content(title=spec.title, body="")
            kwargs: dict = {"name": spec.title}
            if content:
                kwargs["content"] = content
            if len(files) == 1:
                kwargs["file"] = files[0]
            elif files:
                kwargs["files"] = files
            created = await forum.create_thread(**kwargs)
        except CampaignForumError as exc:
            await command_reply(ctx, str(exc))
            await delete_command(ctx)
            return
        except discord.Forbidden:
            await command_reply(ctx, "Missing permission to create posts in that forum.")
            await delete_command(ctx)
            return
        except discord.HTTPException as exc:
            await command_reply(ctx, f"Discord error while creating the post: {exc}")
            await delete_command(ctx)
            return

        thread = created.thread
        clear_campaign_cache(ctx.guild.id)
        link = post_jump_markdown(title=thread.name, url=thread.jump_url)
        await send_message(
            ctx,
            embed=_created_embed(
                title="📌 Campaign post created",
                description=f"**{forum.name}** — {link}",
            ),
            definition_menu=False,
        )
        await delete_command(ctx)

    @campaign_post.autocomplete("section")
    async def campaign_post_section_autocomplete(
        interaction: discord.Interaction,
        current: str,
    ) -> list[app_commands.Choice[str]]:
        return await _forum_section_choices(interaction, current)

    @campaign_group.command(
        name="forum",
        help="Create a forum channel in CAMPAIGN. `forum lieux` → 📍 lieux",
    )
    @guild_only
    @admin_only
    async def campaign_forum(ctx: Context, *, name: str) -> None:
        assert ctx.guild is not None
        try:
            require_manage_channels(ctx.guild)
            category = await ensure_campaign_category(ctx.guild)
            channel_name = format_forum_channel_name(name)
            existing = match_campaign_forum(list_campaign_forums(ctx.guild), channel_name)
            if existing is not None:
                raise CampaignForumError(f"That forum already exists: {existing.mention}")
            forum = await ctx.guild.create_forum(
                channel_name,
                category=category,
                reason=f"Campaign forum created by {ctx.author}",
            )
        except CampaignForumError as exc:
            await command_reply(ctx, str(exc))
            await delete_command(ctx)
            return
        except discord.Forbidden:
            await command_reply(ctx, "Missing permission to create forum channels.")
            await delete_command(ctx)
            return
        except discord.HTTPException as exc:
            await command_reply(ctx, f"Discord error while creating the forum: {exc}")
            await delete_command(ctx)
            return

        clear_campaign_cache(ctx.guild.id)
        await send_message(
            ctx,
            embed=_created_embed(
                title="📂 Campaign forum created",
                description=f"{forum.mention}\nAdd posts with `{PREFIX}campaign post {name.strip()} <title>`.",
            ),
            definition_menu=False,
        )
        await delete_command(ctx)

    @campaign_group.command(
        name="document",
        aliases=["parchemin"],
        help=f"Génère un parchemin. `{PREFIX}campaign document Texte` ou `Titre -- texte`",
    )
    @app_commands.describe(text="Texte du parchemin. Utilise `Titre -- corps` pour un titre.")
    @guild_only
    @admin_only
    async def campaign_document(ctx: Context, *, text: str | None = None) -> None:
        if not text or not text.strip():
            await command_reply(
                ctx,
                f"Texte manquant. Exemple : `{PREFIX}campaign document Par ordre du roi…`",
            )
            await delete_command(ctx)
            return
        try:
            title, body = parse_document_text(text)
            png = await asyncio.to_thread(render_parchment, title=title, body=body)
        except ParchmentError as exc:
            await command_reply(ctx, str(exc))
            await delete_command(ctx)
            return

        await send_message(
            ctx,
            file=discord.File(png, filename="parchemin.png"),
            linkify=False,
            definition_menu=False,
        )
        await delete_command(ctx)

    @campaign_group.command(
        name="channels",
        help="Export every server channel with its category to a file.",
    )
    @guild_only
    @admin_only
    async def campaign_channels(ctx: Context) -> None:
        assert ctx.guild is not None
        path = write_channel_export(ctx.guild)
        json_path = path.with_suffix(".json")
        attachments = [discord.File(path)]
        if json_path.exists():
            attachments.append(discord.File(json_path))
        await send_message(
            ctx,
            content=f"📂 Channel list for **{ctx.guild.name}** — forums and every channel with its category.",
            files=attachments,
            linkify=False,
            definition_menu=False,
        )
        await delete_command(ctx)

    @campaign_group.command(
        name="audit",
        help="Vérifie que chaque post CAMPAIGN est dans le bon forum wiki.",
    )
    @app_commands.describe(mode="`fix` pour recatégoriser les posts mal classés")
    @guild_only
    @admin_only
    async def campaign_audit(ctx: Context, *, mode: str | None = None) -> None:
        assert ctx.guild is not None
        fix = (mode or "").strip().casefold() in {"fix", "corriger"}
        status: discord.Message | None = None
        try:
            status = await send_message(
                ctx,
                content="🔎 Audit des posts CAMPAIGN…",
                linkify=False,
                definition_menu=False,
            )

            async def report(text: str) -> None:
                if status is None:
                    return
                try:
                    await status.edit(content=text)
                except (discord.HTTPException, discord.NotFound):
                    pass

            items = await audit_campaign_posts(ctx.guild, fix=fix, on_progress=report)
            if fix:
                clear_campaign_cache(ctx.guild.id)
        except CampaignForumError as exc:
            if status is not None:
                try:
                    await status.edit(content=f"❌ {exc}")
                except (discord.HTTPException, discord.NotFound):
                    await command_reply(ctx, str(exc))
            else:
                await command_reply(ctx, str(exc))
            await delete_command(ctx)
            return
        except discord.Forbidden:
            await command_reply(ctx, "Missing permission to audit or move campaign posts.")
            await delete_command(ctx)
            return
        except discord.HTTPException as exc:
            await command_reply(ctx, f"Discord error while auditing: {exc}")
            await delete_command(ctx)
            return

        ok = sum(1 for item in items if item.status == "ok")
        misplaced = [item for item in items if item.status == "misplaced" and not item.moved]
        missing = [item for item in items if item.status == "missing_wiki"]
        moved_items = [item for item in items if item.moved]
        lines = [
            f"**Vérifiés :** {len(items)}",
            f"**OK :** {ok} · **Mal classés :** {len(misplaced)} · **Sans wiki :** {len(missing)}",
        ]
        if fix:
            lines.append(f"**Déplacés :** {len(moved_items)}")
        elif misplaced:
            lines.append(f"Corrige avec `{PREFIX}campaign audit fix`.")
        sample = misplaced[:8]
        if sample:
            listed = "\n".join(
                f"• {post_jump_markdown(title=item.title, url=item.jump_url)} — "
                f"`{item.current_section}` → `{item.expected_section}`"
                for item in sample
            )
            extra = len(misplaced) - len(sample)
            suffix = f"\n_… +{extra} de plus_" if extra > 0 else ""
            lines.append(f"**À déplacer :**\n{listed}{suffix}")
        embed = _created_embed(
            title="🔎 Audit CAMPAIGN",
            description="\n".join(lines),
        )
        files = [audit_report_file(items, guild_id=ctx.guild.id)]
        if status is not None:
            try:
                await status.edit(content="", embed=embed)
            except (discord.HTTPException, discord.NotFound):
                await send_message(ctx, embed=embed, definition_menu=False)
        else:
            await send_message(ctx, embed=embed, definition_menu=False)
        await send_message(ctx, files=files, linkify=False, definition_menu=False)
        await delete_command(ctx)

    @campaign_group.command(
        name="move",
        help="Déplace un post CAMPAIGN vers un autre forum et met à jour les liens.",
    )
    @app_commands.describe(
        section="Forum de destination, ex. pnj, race",
        title="Titre du post (vide = post actuel)",
    )
    @guild_only
    @admin_only
    async def campaign_move(
        ctx: Context,
        section: str,
        *,
        title: str | None = None,
    ) -> None:
        assert ctx.guild is not None
        forums = list_campaign_forums(ctx.guild)
        target = match_campaign_forum(forums, section)
        if target is None:
            await command_reply(
                ctx,
                f"Aucun forum CAMPAIGN pour `{section}`.\nForums : {format_forum_list(forums)}",
            )
            await delete_command(ctx)
            return

        needle = (title or "").strip()
        thread: discord.Thread | None = None
        if needle:
            thread = await locate_campaign_thread(forums, needle)
            if thread is None:
                await command_reply(ctx, f"Aucun post CAMPAIGN nommé `{needle}`.")
                await delete_command(ctx)
                return
        elif isinstance(ctx.channel, discord.Thread):
            if forum_for_thread(forums, ctx.channel) is not None:
                thread = ctx.channel
        if thread is None:
            await command_reply(
                ctx,
                "Indique le titre du post, ou lance la commande dans le post à déplacer.\n"
                f"Exemple : `{PREFIX}campaign move pnj Padhiver`",
            )
            await delete_command(ctx)
            return

        status: discord.Message | None = None
        try:
            status = await send_message(
                ctx,
                content=f"📦 Déplacement de **{thread.name}** vers {target.mention}…",
                linkify=False,
                definition_menu=False,
            )

            async def report(text: str) -> None:
                if status is None:
                    return
                try:
                    await status.edit(content=text)
                except (discord.HTTPException, discord.NotFound):
                    pass

            result = await move_campaign_post(
                guild=ctx.guild,
                thread=thread,
                target=target,
                on_progress=report,
                skip_message_ids={
                    message_id
                    for message_id in (
                        getattr(ctx.message, "id", None),
                        getattr(status, "id", None),
                    )
                    if message_id is not None
                },
            )
        except CampaignForumError as exc:
            if status is not None:
                try:
                    await status.edit(content=f"❌ {exc}")
                except (discord.HTTPException, discord.NotFound):
                    await command_reply(ctx, str(exc))
            else:
                await command_reply(ctx, str(exc))
            await delete_command(ctx)
            return
        except discord.Forbidden:
            await command_reply(ctx, "Missing permission to move campaign posts.")
            await delete_command(ctx)
            return
        except discord.HTTPException as exc:
            await command_reply(ctx, f"Discord error while moving the post: {exc}")
            await delete_command(ctx)
            return

        clear_campaign_cache(ctx.guild.id)
        link = post_jump_markdown(title=result.thread.name, url=result.thread.jump_url)
        action = "copié" if result.created else "fusionné avec un post existant"
        embed = _created_embed(
            title="📦 Post déplacé",
            description=(
                f"**{result.source.name}** → **{result.target.name}**\n"
                f"{link}\n"
                f"Le post a été {action}. **{result.relinked}** connexion(s) mise(s) à jour."
            ),
        )
        try:
            await send_message(result.thread, embed=embed, definition_menu=False)
        except (discord.NotFound, discord.HTTPException):
            pass
        invoked_in_source = (
            isinstance(ctx.channel, discord.Thread) and ctx.channel.id == result.old_thread.id
        )
        if not invoked_in_source:
            if status is not None:
                try:
                    await status.edit(content="", embed=embed)
                except (discord.HTTPException, discord.NotFound):
                    try:
                        await send_message(ctx, embed=embed, definition_menu=False)
                    except (discord.NotFound, discord.HTTPException):
                        pass
            else:
                try:
                    await send_message(ctx, embed=embed, definition_menu=False)
                except (discord.NotFound, discord.HTTPException):
                    pass
        await delete_command(ctx)

    @campaign_move.autocomplete("section")
    async def campaign_move_section_autocomplete(
        interaction: discord.Interaction,
        current: str,
    ) -> list[app_commands.Choice[str]]:
        return await _forum_section_choices(interaction, current)

    @campaign_move.autocomplete("title")
    async def campaign_move_title_autocomplete(
        interaction: discord.Interaction,
        current: str,
    ) -> list[app_commands.Choice[str]]:
        if interaction.guild is None:
            return []
        needle = current.casefold().strip()
        choices: list[app_commands.Choice[str]] = []
        seen: set[str] = set()
        for forum in list_campaign_forums(interaction.guild):
            for thread in forum.threads:
                name = thread.name.strip()
                key = name.casefold()
                if not name or key in seen:
                    continue
                if needle and needle not in key:
                    continue
                seen.add(key)
                choices.append(app_commands.Choice(name=name[:100], value=name[:100]))
                if len(choices) >= 25:
                    return choices
        return choices

    @campaign_group.command(
        name="wiki",
        help="Aperçu d'une page du wiki FR des Royaumes Oubliés.",
    )
    @app_commands.describe(query="Nom de page ou URL wiki, ex. Eauprofonde")
    @guild_only
    @admin_only
    async def campaign_wiki(ctx: Context, *, query: str | None = None) -> None:
        if not query or not query.strip():
            await command_reply(
                ctx,
                f"Page wiki manquante. Exemple : `{PREFIX}campaign wiki Eauprofonde`",
            )
            await delete_command(ctx)
            return
        async with ctx.typing():
            try:
                page = await fetch_wiki_page(query)
            except (WikiError, WikiNotFoundError) as exc:
                await command_reply(ctx, str(exc))
                await delete_command(ctx)
                return
        await _send_embeds(ctx, _wiki_preview_embeds(page))
        await delete_command(ctx)

    @campaign_wiki.autocomplete("query")
    async def campaign_wiki_query_autocomplete(
        interaction: discord.Interaction,
        current: str,
    ) -> list[app_commands.Choice[str]]:
        return await _wiki_title_choices(current)

    @campaign_group.command(
        name="import",
        help="Importe une page wiki. Ajoute `--liens` pour les fiches infobox.",
    )
    @app_commands.describe(
        query="Page wiki, `lieux Padhiver`, ou `Padhiver --liens`",
        liens="Créer aussi les fiches de l'infobox",
    )
    @guild_only
    @admin_only
    async def campaign_import(
        ctx: Context,
        *,
        query: str | None = None,
        liens: bool = False,
    ) -> None:
        assert ctx.guild is not None
        if not query or not query.strip():
            await command_reply(
                ctx,
                f"Page wiki manquante. Exemple : `{PREFIX}campaign import Eauprofonde`",
            )
            await delete_command(ctx)
            return
        forums = list_campaign_forums(ctx.guild)
        extra = tuple(forum.name for forum in forums)
        try:
            forced_section, page_query, follow_links = split_import_query(query, extra)
            follow_links = follow_links or liens
        except WikiError as exc:
            await command_reply(ctx, str(exc))
            await delete_command(ctx)
            return

        status: discord.Message | None = None
        try:
            status = await send_message(
                ctx,
                content="📥 Recherche de la page wiki…",
                linkify=False,
                definition_menu=False,
            )
            page = await fetch_wiki_page(page_query, suggest=False)
            if forced_section:
                page = page.with_section(forced_section)
            try:
                await status.edit(
                    content=(
                        f"📥 Import de **{page.title}**"
                        + (" — page + liens d’infobox…" if follow_links else "…")
                    )
                )
            except (discord.HTTPException, discord.NotFound):
                pass

            async def report(text: str) -> None:
                if status is None:
                    return
                try:
                    await status.edit(content=text)
                except (discord.HTTPException, discord.NotFound):
                    pass

            result = await import_wiki_cluster(
                guild=ctx.guild,
                root=page,
                follow_links=follow_links,
                on_progress=report,
            )
        except (WikiError, WikiNotFoundError, CampaignForumError) as exc:
            if status is not None:
                try:
                    await status.edit(content=f"❌ {exc}")
                except (discord.HTTPException, discord.NotFound):
                    await command_reply(ctx, str(exc))
            else:
                await command_reply(ctx, str(exc))
            await delete_command(ctx)
            return
        except discord.Forbidden:
            await command_reply(ctx, "Missing permission to create campaign posts or forums.")
            await delete_command(ctx)
            return
        except discord.HTTPException as exc:
            await command_reply(ctx, f"Discord error while importing: {exc}")
            await delete_command(ctx)
            return

        posts = result.posts
        clear_campaign_cache(ctx.guild.id)
        created = [post for post in posts if post.created]
        reused = [post for post in posts if not post.created]
        refilled = [post for post in posts if post.needs_fill and not post.created]
        root_post = posts[0]
        lines = [
            f"**{root_post.forum.name}** — {post_jump_markdown(title=root_post.thread.name, url=root_post.thread.jump_url)}",
            f"[Source]({root_post.page.url})",
            f"**Créés :** {len(created)} · **Déjà présents :** {len(reused)} · **Total :** {len(posts)}",
        ]
        if refilled:
            lines.append(f"**Placeholder rempli :** {len(refilled)}")
        if follow_links and any(
            not post.created and not post.needs_fill and post.thread.id == root_post.thread.id
            for post in posts
        ):
            lines.append("**Liens du post existant mis à jour.**")
        extra_created = [post for post in created if post.thread.id != root_post.thread.id]
        if extra_created:
            sample = extra_created[:8]
            linked = ", ".join(
                post_jump_markdown(title=post.thread.name, url=post.thread.jump_url)
                for post in sample
            )
            leftover = len(extra_created) - len(sample)
            suffix = f" … +{leftover} de plus" if leftover > 0 else ""
            lines.append(f"**Nouveaux posts :** {linked}{suffix}")
        if result.truncated:
            lines.append(
                f"_Arrêt à {result.max_pages} pages. "
                f"Relance `{PREFIX}campaign import <page> --liens` sur une page liée pour continuer._"
            )
        if result.failed_wiki:
            sample = result.failed_wiki[:8]
            extra = len(result.failed_wiki) - len(sample)
            listed = ", ".join(f"`{title}`" for title in sample)
            suffix = f" … +{extra}" if extra > 0 else ""
            lines.append(f"**Erreur wiki :** {listed}{suffix}")
        if result.missing_wiki:
            sample = result.missing_wiki[:8]
            extra = len(result.missing_wiki) - len(sample)
            listed = ", ".join(f"`{title}`" for title in sample)
            suffix = f" … +{extra}" if extra > 0 else ""
            lines.append(f"**Page introuvable :** {listed}{suffix}")
        embed = _created_embed(
            title=f"📥 Import — {len(created)} nouveau(x) post(s)",
            description="\n".join(lines),
        )
        if status is not None:
            try:
                await status.edit(content="", embed=embed)
            except (discord.HTTPException, discord.NotFound):
                await send_message(ctx, embed=embed, definition_menu=False)
        else:
            await send_message(ctx, embed=embed, definition_menu=False)
        await delete_command(ctx)

    @campaign_group.command(
        name="repair",
        help="Remplit les posts « Import des liens… » et « … suite sur le wiki. ».",
    )
    @guild_only
    @admin_only
    async def campaign_repair(ctx: Context) -> None:
        assert ctx.guild is not None
        status: discord.Message | None = None
        try:
            status = await send_message(
                ctx,
                content="🔧 Recherche des posts incomplets…",
                linkify=False,
                definition_menu=False,
            )

            async def report(text: str) -> None:
                if status is None:
                    return
                try:
                    await status.edit(content=text)
                except (discord.HTTPException, discord.NotFound):
                    pass

            result = await repair_placeholder_posts(ctx.guild, on_progress=report)
        except (CampaignForumError, WikiError) as exc:
            if status is not None:
                try:
                    await status.edit(content=f"❌ {exc}")
                except (discord.HTTPException, discord.NotFound):
                    await command_reply(ctx, str(exc))
            else:
                await command_reply(ctx, str(exc))
            await delete_command(ctx)
            return
        except discord.Forbidden:
            await command_reply(ctx, "Missing permission to update campaign posts.")
            await delete_command(ctx)
            return
        except discord.HTTPException as exc:
            await command_reply(ctx, f"Discord error while repairing posts: {exc}")
            await delete_command(ctx)
            return

        clear_campaign_cache(ctx.guild.id)
        lines = [
            f"**Incomplets trouvés :** {result.scanned}",
            f"**Remplis :** {len(result.repaired)}",
        ]
        if result.missing_wiki:
            sample = result.missing_wiki[:8]
            extra = len(result.missing_wiki) - len(sample)
            listed = ", ".join(f"`{title}`" for title in sample)
            suffix = f" … +{extra}" if extra > 0 else ""
            lines.append(f"**Pas de page wiki :** {listed}{suffix}")
        if result.repaired:
            sample_posts = result.repaired[:8]
            linked = ", ".join(
                post_jump_markdown(title=thread.name, url=thread.jump_url)
                for thread in sample_posts
            )
            leftover = len(result.repaired) - len(sample_posts)
            suffix = f" … +{leftover} de plus" if leftover > 0 else ""
            lines.append(f"**Mis à jour :** {linked}{suffix}")
        elif result.scanned == 0:
            lines.append("_Aucun post incomplet (« Import des liens… » ou « … suite sur le wiki. »)._")
        embed = _created_embed(title="🔧 Repair CAMPAIGN", description="\n".join(lines))
        if status is not None:
            try:
                await status.edit(content="", embed=embed)
            except (discord.HTTPException, discord.NotFound):
                await send_message(ctx, embed=embed, definition_menu=False)
        else:
            await send_message(ctx, embed=embed, definition_menu=False)
        await delete_command(ctx)

    @campaign_import.autocomplete("query")
    async def campaign_import_query_autocomplete(
        interaction: discord.Interaction,
        current: str,
    ) -> list[app_commands.Choice[str]]:
        return await _wiki_title_choices(current)
