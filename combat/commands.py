"""`;combat` — the text combat tracker (initiative, HP, conditions)."""

import dataclasses
from dataclasses import dataclass
import random
import re

import discord
from discord import app_commands
from discord.ext.commands.bot import Bot
from discord.ext.commands.context import Context

from bot.checks import is_staff
from bot.command_helpers import command_reply, delete_command
from bot.help_text import command_help
from combat.encounter import (
    Combatant,
    Encounter,
    MONSTER,
    PLAYER,
    condition_key,
    condition_label,
    delete_encounter,
    load_encounter,
    roll_initiative,
    save_encounter,
)
from combat.attacks import (
    UNARMED_NAMES,
    roll_damage_part,
    WEAPON_ALIASES_FR,
    Attack,
    AttackContext,
    AttackOutcome,
    DamagePart,
    damage_type_key,
    damage_type_label,
    format_damage_line,
    resolve_attack,
    unarmed_attack,
    weapon_attack,
)
from combat.effects import (
    add_condition,
    concentration_breaks_on,
    condition_keys,
    end_concentration,
    link_to_concentration,
    player_has_condition,
    remove_condition,
    roll_save,
    set_player_condition,
    start_concentration,
)
from combat.spells import (
    SpellInfo,
    caster_numbers,
    damage_for_cast,
    heal_for_cast,
    lookup_spell,
    projectile_count,
)
from combat.hp import damage_combatant, heal_combatant, roll_death_save, set_temp_hp
from combat.monsters import MonsterStats, lookup_monster, roll_hp
from combat.render import tracker_embed
from config import PREFIX
from sheets.context import resolve_owner
from sheets.containers import STORED_HANDS
from sheets.data import CharacterSheet, fold_lookup_key
from sheets.equipment import ITEM_KIND_WEAPON, InventoryItem, _indexed_equipment
from sheets.dice import DICE_PATTERN, execute_roll, parse_dice
from sheets.storage import get_sheet, update_sheet

MAX_MONSTERS_PER_ADD = 20
_MENTION = re.compile(r"<@!?(\d+)>")
_COUNT = re.compile(r"^(?:x(\d+)|(\d+)x)$", re.IGNORECASE)
_HALF_TOKENS = frozenset({"moitie", "moitié", "half", "demi"})
_AVERAGE_TOKENS = frozenset({"moy", "moyenne", "avg", "average"})
_HP_WORDS = frozenset({"pv", "hp"})
_AC_WORDS = frozenset({"ca", "ac"})
_INIT_WORDS = frozenset({"init", "initiative"})
_ALLOWED_MENTIONS = discord.AllowedMentions(users=True, roles=False, everyone=False)

NO_COMBAT = f"Pas de combat dans ce salon. Lance-le avec `{PREFIX}combat start`."
STAFF_ONLY = "Seul le MJ peut faire ça."

ATTACK_HELP = command_help(
    "Attaque une cible : jet contre sa CA, dégâts appliqués, critiques doublés. "
    "Arme de ta fiche, ou attaque du monstre dont c’est le tour.",
    f"`{PREFIX}atk <cible> [arme] [adv|dis] [+N] [xN]`",
    f"`{PREFIX}atk gobelin 1` · `{PREFIX}atk gob 1 dague adv` · `{PREFIX}atk ogre épée longue 2m`",
    f"`{PREFIX}atk Pip` — MJ, pendant le tour d’un monstre · `{PREFIX}atk gobelin 2 -> Pip x2`",
    f"`{PREFIX}atk gobelin 1 +5 1d8+3 tranchant` — bonus et dégâts à la main",
)

CAST_HELP = command_help(
    "Lance un sort (5etools) ou une action à sauvegarde d’un monstre : DD et attaque "
    "de la fiche, emplacement dépensé, jets de sauvegarde, dégâts, soins, états, concentration.",
    f"`{PREFIX}cast <sort> [niv N] [adv] sur <cible, cible…>`",
    f"`{PREFIX}cast boule de feu sur gob 1, gob 2` · `{PREFIX}cast fireball niv 5 sur ogre`",
    f"`{PREFIX}cast trait de feu sur gobelin 1` · `{PREFIX}cast mot de guérison sur Pip`",
    f"`{PREFIX}cast bénédiction sur Pip, Thorin, moi` · `{PREFIX}cast immobilisation de personne sur bandit`",
    f"`{PREFIX}cast fire breath sur Pip, Thorin` — MJ, pendant le tour du dragon",
    f"`{PREFIX}cast prêtre -> sacred flame dc 13 sur Pip` — lanceur et DD précisés",
)

COMBAT_HELP = command_help(
    "Combat au tour par tour : initiative, PV et états, un combat par salon.",
    f"`{PREFIX}combat start [monstres]`",
    f"`{PREFIX}combat add gobelin x3` · `{PREFIX}combat add ogre moy, @Pip` — MJ",
    f"`{PREFIX}combat add bandit pv 11 ca 12 init 1 # Chef bandit` — monstre maison",
    f"`{PREFIX}combat join [initiative]` — ton personnage rejoint le combat",
    f"`{PREFIX}next` — tour suivant (MJ, ou toi pendant ton tour)",
    f"`{PREFIX}combat dmg gobelin 1 8` · `{PREFIX}combat dmg gob 1, gob 2 8d6 moitié`",
    f"`{PREFIX}combat heal Pip 2d4+2` · `{PREFIX}combat temp Pip 5` (PV temporaires)",
    f"`{PREFIX}atk gobelin 1 [arme] [adv]` — attaque contre la CA, dégâts appliqués",
    f"`{PREFIX}mort` — jet contre la mort à 0 PV",
    f"`{PREFIX}cast boule de feu sur gob 1, gob 2` — sorts et souffles, sauvegardes comprises",
    f"`{PREFIX}atk gobelin 1 reac` — attaque d’opportunité · `{PREFIX}combat reac` · `{PREFIX}combat conc`",
    f"`{PREFIX}combat cond gobelin 2 à terre 1` — état (ici 1 round) ; à nouveau pour l’enlever",
    f"`{PREFIX}combat init Pip 18` · `{PREFIX}combat remove gobelin 3`",
    f"`{PREFIX}combat mj` — PV exacts et CA des monstres, pour toi seul",
    f"`{PREFIX}combat show` · `{PREFIX}combat end`",
)


# --- helpers -------------------------------------------------------------


def _is_component(ctx: Context) -> bool:
    return getattr(ctx, "is_component", False) is True


async def _done(ctx: Context) -> None:
    """Acknowledge the command: delete it, or silently ack a button click."""
    if _is_component(ctx):
        if not ctx.interaction.response.is_done():
            await ctx.interaction.response.defer()
        return
    await delete_command(ctx)


async def _fail(ctx: Context, message: str) -> None:
    if _is_component(ctx):
        await ctx.send(content=message, ephemeral=True)
        return
    await command_reply(ctx, message, linkify=False, definition_menu=False)
    await delete_command(ctx)


async def _reply(ctx: Context, lines: list[str]) -> None:
    await command_reply(ctx, "\n".join(lines), linkify=False, definition_menu=False)
    await _done(ctx)


def _tracker_view(encounter: Encounter) -> discord.ui.View:
    from combat.views import TrackerView

    return TrackerView(encounter)


async def _require_encounter(ctx: Context) -> Encounter | None:
    if ctx.guild is None:
        await _fail(ctx, "Cette commande marche seulement sur le serveur.")
        return None
    encounter = load_encounter(guild_id=ctx.guild.id, channel_id=ctx.channel.id)
    if encounter is None:
        await _fail(ctx, NO_COMBAT)
    return encounter


def _sheets_for(encounter: Encounter) -> dict[int, CharacterSheet | None]:
    return {
        combatant.user_id: get_sheet(
            user_id=combatant.user_id, guild_id=encounter.guild_id
        )
        for combatant in encounter.combatants
        if combatant.user_id is not None
    }


def _remember_tracker(encounter: Encounter, message: discord.Message) -> None:
    # Reload: another command may have changed the encounter while we awaited.
    latest = load_encounter(
        guild_id=encounter.guild_id, channel_id=encounter.channel_id
    )
    if latest is not None:
        latest.tracker_message_id = message.id
        save_encounter(latest)


async def post_tracker(ctx: Context, encounter: Encounter, content: str = "") -> None:
    """Post the tracker at the bottom of the channel, replacing the old one.

    Sent to the channel, not as the slash response: `delete_command` acks and
    removes that response afterwards.
    """
    if encounter.tracker_message_id is not None:
        try:
            await ctx.channel.get_partial_message(encounter.tracker_message_id).delete()
        except discord.HTTPException:
            pass
    message = await ctx.channel.send(
        content=content or None,
        embed=tracker_embed(encounter, _sheets_for(encounter)),
        view=_tracker_view(encounter),
        allowed_mentions=_ALLOWED_MENTIONS,
    )
    _remember_tracker(encounter, message)
    await _done(ctx)


async def refresh_tracker(ctx: Context, encounter: Encounter) -> None:
    """Edit the tracker in place (repost it if it was deleted)."""
    embed = tracker_embed(encounter, _sheets_for(encounter))
    if encounter.tracker_message_id is not None:
        try:
            await ctx.channel.get_partial_message(encounter.tracker_message_id).edit(
                embed=embed, view=_tracker_view(encounter)
            )
            return
        except discord.HTTPException:
            pass
    message = await ctx.channel.send(embed=embed, view=_tracker_view(encounter))
    _remember_tracker(encounter, message)


def _target(encounter: Encounter, text: str) -> Combatant:
    mention = _MENTION.fullmatch(text.strip())
    if mention:
        found = encounter.player(int(mention.group(1)))
        if found is None:
            raise ValueError("Ce joueur n’est pas dans le combat.")
        return found
    return encounter.find(text)


def _target_prefix(
    encounter: Encounter, tokens: list[str]
) -> tuple[Combatant, list[str]]:
    if tokens and _MENTION.fullmatch(tokens[0]):
        return _target(encounter, tokens[0]), tokens[1:]
    return encounter.find_prefix(tokens)


def _can_act_on(ctx: Context, combatant: Combatant) -> bool:
    return is_staff(ctx) or (combatant.is_player and combatant.user_id == ctx.author.id)


def _dex_bonus(sheet: CharacterSheet) -> int:
    return (sheet.abilities.get("dex", 10) - 10) // 2


def _player_combatant(
    sheet: CharacterSheet, user_id: int, initiative: int | None
) -> Combatant:
    bonus = _dex_bonus(sheet)
    return Combatant(
        id="",
        name=sheet.name,
        kind=PLAYER,
        initiative=initiative if initiative is not None else roll_initiative(bonus),
        init_bonus=bonus,
        user_id=user_id,
    )


def _add_player(encounter: Encounter, user_id: int, initiative: int | None) -> str:
    sheet = get_sheet(user_id=user_id, guild_id=encounter.guild_id)
    if sheet is None:
        return f"⚠️ <@{user_id}> n’a pas de fiche."
    existing = encounter.player(user_id)
    if existing is not None:
        if initiative is None:
            return f"**{existing.name}** est déjà dans le combat."
        existing.initiative = initiative
        return f"🔁 **{existing.name}** : initiative {initiative}."
    combatant = encounter.add(_player_combatant(sheet, user_id, initiative))
    return f"➕ **{combatant.name}** rejoint le combat (initiative {combatant.initiative})."


# --- monster specs --------------------------------------------------------


class MonsterSpec:
    def __init__(
        self, *, stats: MonsterStats, count: int, average: bool, name: str
    ) -> None:
        self.stats = stats
        self.count = count
        self.average = average
        self.name = name


def _take_number(tokens: list[str], index: int, word: str) -> int:
    value = tokens[index + 1] if index + 1 < len(tokens) else ""
    if not re.fullmatch(r"[+-]?\d+", value):
        raise ValueError(f"Il manque un nombre après `{word}`.")
    return int(value)


async def parse_monster_spec(spec: str) -> MonsterSpec:
    body, _, custom_name = spec.partition("#")
    tokens = body.split()
    count = 1
    average = False
    hp: int | None = None
    ac: int | None = None
    init: int | None = None
    name_tokens: list[str] = []
    index = 0
    while index < len(tokens):
        token = tokens[index]
        lowered = token.lower()
        count_match = _COUNT.match(token)
        if count_match:
            count = int(count_match.group(1) or count_match.group(2))
        elif lowered in _AVERAGE_TOKENS:
            average = True
        elif lowered in _HP_WORDS:
            hp = _take_number(tokens, index, token)
            index += 1
        elif lowered in _AC_WORDS:
            ac = _take_number(tokens, index, token)
            index += 1
        elif lowered in _INIT_WORDS:
            init = _take_number(tokens, index, token)
            index += 1
        else:
            name_tokens.append(token)
        index += 1

    if not 1 <= count <= MAX_MONSTERS_PER_ADD:
        raise ValueError(f"Entre 1 et {MAX_MONSTERS_PER_ADD} monstres à la fois.")
    query = " ".join(name_tokens)
    if hp is not None:
        if hp < 1:
            raise ValueError("Les PV doivent être d’au moins 1.")
        label = custom_name.strip() or query.strip()
        if not label:
            raise ValueError("Donne un nom au monstre : `bandit pv 11 ca 12`.")
        stats = MonsterStats(
            name=label, hp_average=hp, hp_formula=None, ac=ac, init_bonus=init or 0
        )
    else:
        if not query:
            raise ValueError("Quel monstre ? Exemple : `gobelin x3`.")
        stats = await lookup_monster(query)
        if ac is not None or init is not None:
            stats = dataclasses.replace(
                stats,
                ac=ac if ac is not None else stats.ac,
                init_bonus=init if init is not None else stats.init_bonus,
            )
    return MonsterSpec(
        stats=stats,
        count=count,
        average=average,
        name=" ".join(custom_name.split()) or stats.name,
    )


def add_monsters(encounter: Encounter, spec: MonsterSpec) -> list[Combatant]:
    # Same-kind monsters share one initiative roll, as in the rules.
    initiative = roll_initiative(spec.stats.init_bonus)
    # One shared tiebreak, nudged so the group acts in number order.
    tiebreak = random.random() * 0.9
    added: list[Combatant] = []
    for offset, name in enumerate(encounter.monster_names(spec.name, spec.count)):
        hp = roll_hp(spec.stats, average=spec.average)
        added.append(
            encounter.add(
                Combatant(
                    id="",
                    name=name,
                    kind=MONSTER,
                    initiative=initiative,
                    init_bonus=spec.stats.init_bonus,
                    hp=hp,
                    hp_max=hp,
                    ac=spec.stats.ac,
                    source=spec.stats.name,
                    tiebreak=tiebreak + offset * 1e-6,
                    attacks=[attack.to_dict() for attack in spec.stats.attacks],
                    resist=list(spec.stats.resist),
                    immune=list(spec.stats.immune),
                    vulnerable=list(spec.stats.vulnerable),
                    saves=dict(spec.stats.saves),
                    save_actions=[
                        action.to_dict() for action in spec.stats.save_actions
                    ],
                    spell_dc=spec.stats.spell_dc,
                    spell_attack=spec.stats.spell_attack,
                )
            )
        )
    return added


async def _collect_additions(
    ctx: Context, args: str
) -> tuple[list[int], list[MonsterSpec], list[str]]:
    """Mentions to add as players, monster specs, and errors to report."""
    user_ids = [int(raw) for raw in _MENTION.findall(args)]
    errors: list[str] = []
    specs: list[MonsterSpec] = []
    for chunk in _MENTION.sub("", args).split(","):
        if not chunk.strip():
            continue
        try:
            specs.append(await parse_monster_spec(chunk))
        except ValueError as exc:
            errors.append(f"⚠️ {exc}")
    return user_ids, specs, errors


def _apply_additions(
    encounter: Encounter, user_ids: list[int], specs: list[MonsterSpec]
) -> list[str]:
    lines = [_add_player(encounter, user_id, None) for user_id in user_ids]
    for spec in specs:
        added = add_monsters(encounter, spec)
        names = ", ".join(f"**{c.name}**" for c in added)
        source = (
            f" ({spec.stats.name}{f', {spec.stats.source}' if spec.stats.source else ''})"
            if spec.stats.name != spec.name or spec.stats.source
            else ""
        )
        lines.append(f"➕ {names}{source} — initiative {added[0].initiative}")
    return lines


# --- HP and conditions on players (stored on the sheet) --------------------


# --- amounts --------------------------------------------------------------


def roll_amount(text: str) -> tuple[int, str | None]:
    """`8` → (8, None); `2d6+3` → (total, "2d6+3 → 11")."""
    cleaned = "".join(text.split())
    if cleaned.isdigit():
        return int(cleaned), None
    if not DICE_PATTERN.match(cleaned.lower()):
        raise ValueError(
            f"Montant invalide : `{text}`. Exemples : `8`, `2d6+3`, `8d6 moitié`."
        )
    result = execute_roll(
        dice=parse_dice(cleaned), sheet=None, modifier_tokens=[], advantage=None
    )
    return max(0, result.total), f"🎲 `{result.dice_notation}` → **{result.total}**"


def parse_hp_args(args: str) -> tuple[list[str], str, bool, str]:
    """`gob 1, gob 2 8d6 feu moitié` → (["gob 1", "gob 2"], "8d6", True, "fire")."""
    tokens = args.split()
    half = False
    damage_type = ""
    while tokens:
        last = tokens[-1].lower()
        if last in _HALF_TOKENS:
            half = True
        elif damage_type_key(last) and len(tokens) > 2:
            damage_type = damage_type_key(last) or ""
        else:
            break
        tokens.pop()
    if len(tokens) < 2:
        raise ValueError("Précise la cible et le montant : `gobelin 1 8`.")
    amount = tokens.pop()
    targets = [part.strip() for part in " ".join(tokens).split(",") if part.strip()]
    return targets, amount, half, damage_type


def _defended_amount(
    target: Combatant, amount: int, damage_type: str
) -> tuple[int, str]:
    if not damage_type:
        return amount, ""
    if damage_type in target.immune:
        return 0, " (immunité)"
    if damage_type in target.resist:
        return amount // 2, " (résistance)"
    if damage_type in target.vulnerable:
        return amount * 2, " (vulnérabilité)"
    return amount, ""


async def _change_hp(ctx: Context, args: str, *, healing: bool) -> None:
    encounter = await _require_encounter(ctx)
    if encounter is None:
        return
    try:
        target_texts, amount_text, half, damage_type = parse_hp_args(args)
        targets = [_target(encounter, text) for text in target_texts]
        amount, roll_line = roll_amount(amount_text)
    except ValueError as exc:
        await _fail(ctx, str(exc))
        return
    if not all(_can_act_on(ctx, target) for target in targets):
        await _fail(ctx, "Tu ne peux changer que les PV de ton personnage.")
        return
    if half:
        amount //= 2

    lines: list[str] = []
    kind = f" {damage_type_label(damage_type)}" if damage_type and not healing else ""
    if roll_line:
        lines.append(roll_line + (f" · moitié : **{amount}**" if half else "") + kind)
    elif half:
        lines.append(f"Moitié : **{amount}**{kind}")
    for target in targets:
        try:
            if healing:
                lines.extend(heal_combatant(encounter, target, amount))
                continue
            dealt, note = _defended_amount(target, amount, damage_type)
            if note:
                lines.append(f"**{target.name}**{note} : {dealt}")
            lines.extend(damage_combatant(encounter, target, dealt))
        except ValueError as exc:
            lines.append(f"⚠️ {exc}")
    save_encounter(encounter)
    await _reply(ctx, lines)
    await refresh_tracker(ctx, encounter)


# --- command handlers -----------------------------------------------------


async def handle_start(ctx: Context, args: str) -> None:
    if ctx.guild is None:
        await _fail(ctx, "Cette commande marche seulement sur le serveur.")
        return
    if not is_staff(ctx):
        await _fail(ctx, STAFF_ONLY)
        return
    if load_encounter(guild_id=ctx.guild.id, channel_id=ctx.channel.id) is not None:
        await _fail(
            ctx,
            f"Un combat est déjà en cours ici. `{PREFIX}combat show` pour le voir, "
            f"`{PREFIX}combat end` pour le terminer.",
        )
        return
    user_ids, specs, errors = await _collect_additions(ctx, args)
    encounter = Encounter(guild_id=ctx.guild.id, channel_id=ctx.channel.id)
    lines = _apply_additions(encounter, user_ids, specs) + errors
    save_encounter(encounter)
    await post_tracker(
        ctx, encounter, "\n".join(["⚔️ **Le combat commence !**", *lines])
    )


async def handle_add(ctx: Context, args: str) -> None:
    if not is_staff(ctx):
        await _fail(ctx, STAFF_ONLY + f" Les joueurs utilisent `{PREFIX}combat join`.")
        return
    if await _require_encounter(ctx) is None:
        return
    if not args.strip():
        await _fail(ctx, f"Qui ajouter ? `{PREFIX}combat add gobelin x3, @Pip`")
        return
    user_ids, specs, errors = await _collect_additions(ctx, args)
    encounter = await _require_encounter(ctx)
    if encounter is None:
        return
    lines = _apply_additions(encounter, user_ids, specs) + errors
    save_encounter(encounter)
    await _reply(ctx, lines)
    await refresh_tracker(ctx, encounter)


async def handle_join(ctx: Context, args: str) -> None:
    encounter = await _require_encounter(ctx)
    if encounter is None:
        return
    mention = _MENTION.search(args)
    member = (
        ctx.guild.get_member(int(mention.group(1)))
        if mention and ctx.guild is not None
        else None
    )
    owner_id = await resolve_owner(ctx, member)
    if owner_id is None:
        return
    rest = _MENTION.sub("", args).strip()
    if rest and not rest.isdigit():
        await _fail(
            ctx, f"L’initiative doit être un nombre : `{PREFIX}combat join 17`."
        )
        return
    line = _add_player(encounter, owner_id, int(rest) if rest else None)
    save_encounter(encounter)
    await _reply(ctx, [line])
    await refresh_tracker(ctx, encounter)


async def handle_next(ctx: Context) -> None:
    encounter = await _require_encounter(ctx)
    if encounter is None:
        return
    current = encounter.current()
    allowed = is_staff(ctx) or (
        current is not None and current.is_player and current.user_id == ctx.author.id
    )
    if not allowed:
        await _fail(
            ctx, "Seul le MJ, ou le joueur dont c’est le tour, peut passer au suivant."
        )
        return
    try:
        change = encounter.advance()
    except ValueError as exc:
        await _fail(ctx, str(exc))
        return
    lines: list[str] = []
    if change.new_round:
        lines.append(f"🔔 **Round {encounter.round}**")
    for combatant, key in change.expired:
        if combatant.is_player:
            set_player_condition(encounter, combatant, key, present=False)
        lines.append(f"⏱️ **{combatant.name}** : fin de {condition_label(key)}")
    turn = change.current
    if turn.is_player and turn.user_id is not None:
        lines.append(f"▶ Au tour de <@{turn.user_id}> (**{turn.name}**)")
        sheet = get_sheet(user_id=turn.user_id, guild_id=encounter.guild_id)
        if sheet is not None and sheet.hp_max and sheet.hp_current <= 0:
            lines.append(
                f"🛌 À terre : jet de sauvegarde contre la mort (`{PREFIX}mort`)."
            )
    else:
        lines.append(f"▶ Au tour de **{turn.name}**")
    save_encounter(encounter)
    await post_tracker(ctx, encounter, "\n".join(lines))


async def handle_condition(ctx: Context, args: str) -> None:
    encounter = await _require_encounter(ctx)
    if encounter is None:
        return
    tokens = args.split()
    rounds: int | None = None
    if tokens and tokens[-1].isdigit():
        rounds = int(tokens.pop())
    try:
        target, rest = _target_prefix(encounter, tokens)
    except ValueError as exc:
        await _fail(ctx, f"{exc}\nExemple : `{PREFIX}combat cond gobelin 2 à terre 1`")
        return
    if not rest:
        await _fail(
            ctx, f"Quel état ? Exemple : `{PREFIX}combat cond {target.name} à terre`"
        )
        return
    if not _can_act_on(ctx, target):
        await _fail(ctx, "Tu ne peux changer que les états de ton personnage.")
        return
    key = condition_key(" ".join(rest))
    label = condition_label(key)
    present = key in target.conditions or player_has_condition(encounter, target, key)
    lines: list[str] = []
    if present and rounds is None:
        remove_condition(encounter, target, key)
        lines.append(f"✅ **{target.name}** n’est plus {label}.")
    else:
        add_condition(encounter, target, key, rounds)
        duration = (
            f" ({rounds} round{'s' if rounds and rounds > 1 else ''})" if rounds else ""
        )
        lines.append(f"**{target.name}** : {label}{duration}")
        if concentration_breaks_on(key):
            lines.extend(end_concentration(encounter, target, reason=label))
    save_encounter(encounter)
    await _reply(ctx, lines)
    await refresh_tracker(ctx, encounter)


async def handle_init(ctx: Context, args: str) -> None:
    encounter = await _require_encounter(ctx)
    if encounter is None:
        return
    tokens = args.split()
    if len(tokens) < 2 or not re.fullmatch(r"-?\d+", tokens[-1]):
        await _fail(ctx, f"Exemple : `{PREFIX}combat init Pip 18`")
        return
    value = int(tokens.pop())
    try:
        target, rest = _target_prefix(encounter, tokens)
    except ValueError as exc:
        await _fail(ctx, str(exc))
        return
    if rest:
        await _fail(ctx, f"Je ne comprends pas `{' '.join(rest)}`.")
        return
    if not _can_act_on(ctx, target):
        await _fail(ctx, "Tu ne peux changer que l’initiative de ton personnage.")
        return
    target.initiative = value
    save_encounter(encounter)
    await _reply(ctx, [f"🔁 **{target.name}** : initiative {value}."])
    await refresh_tracker(ctx, encounter)


async def handle_remove(ctx: Context, args: str) -> None:
    encounter = await _require_encounter(ctx)
    if encounter is None:
        return
    if not is_staff(ctx):
        await _fail(ctx, STAFF_ONLY)
        return
    try:
        target = _target(encounter, args)
    except ValueError as exc:
        await _fail(ctx, str(exc))
        return
    for key, rounds in list(target.conditions.items()):
        if target.is_player and rounds is not None:
            set_player_condition(encounter, target, key, present=False)
    encounter.remove(target)
    save_encounter(encounter)
    await _reply(ctx, [f"➖ **{target.name}** quitte le combat."])
    await refresh_tracker(ctx, encounter)


async def handle_end(ctx: Context) -> None:
    encounter = await _require_encounter(ctx)
    if encounter is None:
        return
    if not is_staff(ctx):
        await _fail(ctx, STAFF_ONLY)
        return
    # Timed conditions belong to this fight; untimed ones stay on the sheets.
    for combatant in encounter.combatants:
        for key, rounds in combatant.conditions.items():
            if combatant.is_player and rounds is not None:
                set_player_condition(encounter, combatant, key, present=False)
    delete_encounter(guild_id=encounter.guild_id, channel_id=encounter.channel_id)
    if encounter.tracker_message_id is not None:
        try:
            await ctx.channel.get_partial_message(encounter.tracker_message_id).edit(
                embed=tracker_embed(encounter, _sheets_for(encounter), ended=True),
                view=None,
            )
        except discord.HTTPException:
            pass
    await _reply(ctx, [f"🏁 Combat terminé après {encounter.round} round(s)."])


async def handle_show(ctx: Context) -> None:
    encounter = await _require_encounter(ctx)
    if encounter is None:
        return
    await post_tracker(ctx, encounter)


async def handle_mj(ctx: Context) -> None:
    encounter = await _require_encounter(ctx)
    if encounter is None:
        return
    if not is_staff(ctx):
        await _fail(ctx, STAFF_ONLY)
        return
    embed = tracker_embed(encounter, _sheets_for(encounter), mj=True)
    if ctx.interaction is not None:
        await ctx.send(embed=embed, ephemeral=True)
        return
    try:
        await ctx.author.send(embed=embed)
    except discord.Forbidden:
        await _fail(ctx, "Je ne peux pas t’envoyer de MP : ouvre tes messages privés.")
        return
    await delete_command(ctx)


# --- attacks --------------------------------------------------------------

_ARROW = re.compile(r"\s*(?:->|→|>)\s*")
_HIT_BONUS = re.compile(r"^[+-]\d+$")
_TWO_HANDED_TOKENS = frozenset({"2m", "2h", "deux_mains", "a_deux_mains", "two_handed"})
_REPEAT = re.compile(r"^(?:x(\d+)|(\d+)x)$", re.IGNORECASE)
MAX_ATTACKS = 6


@dataclass
class AttackRequest:
    attacker: Combatant
    target: Combatant
    query: str = ""
    advantage: bool | None = None
    hit_bonus: int = 0
    manual_dice: str = ""
    manual_type: str = ""
    two_handed: bool = False
    repeat: int = 1
    reaction: bool = False


_REACTION_TOKENS = frozenset(
    {"reac", "reaction", "ao", "opportunite", "attaque_d_opportunite", "opportunity"}
)


def _split_attack_flags(tokens: list[str]) -> tuple[list[str], dict[str, object]]:
    flags: dict[str, object] = {"hit_bonus": 0, "repeat": 1}
    kept: list[str] = []
    for token in tokens:
        key = fold_lookup_key(token)
        repeat = _REPEAT.match(token)
        if key in _REACTION_TOKENS:
            flags["reaction"] = True
        elif key in ("adv", "avantage", "advantage"):
            if flags.get("advantage") is False:
                raise ValueError(
                    "Impossible d’avoir avantage et désavantage à la fois."
                )
            flags["advantage"] = True
        elif key in ("dis", "desavantage", "disadvantage", "desav"):
            if flags.get("advantage") is True:
                raise ValueError(
                    "Impossible d’avoir avantage et désavantage à la fois."
                )
            flags["advantage"] = False
        elif _HIT_BONUS.match(token):
            flags["hit_bonus"] = int(flags["hit_bonus"]) + int(token)
        elif repeat:
            count = int(repeat.group(1) or repeat.group(2))
            if not 1 <= count <= MAX_ATTACKS:
                raise ValueError(f"Entre 1 et {MAX_ATTACKS} attaques à la fois.")
            flags["repeat"] = count
        elif key in _TWO_HANDED_TOKENS:
            flags["two_handed"] = True
        elif DICE_PATTERN.match(token.lower()):
            flags["manual_dice"] = token
        elif damage_type_key(token) and kept:
            flags["manual_type"] = damage_type_key(token)
        else:
            kept.append(token)
    return kept, flags


def parse_attack(ctx: Context, encounter: Encounter, args: str) -> AttackRequest:
    attacker: Combatant | None = None
    parts = _ARROW.split(args.strip(), maxsplit=1)
    if len(parts) == 2:
        attacker = _target(encounter, parts[0])
        rest = parts[1]
    else:
        rest = parts[0]
    if attacker is None:
        own = encounter.player(ctx.author.id)
        current = encounter.current()
        if not is_staff(ctx):
            attacker = own
        else:
            attacker = current or own
    if attacker is None:
        if is_staff(ctx):
            raise ValueError(
                "Qui attaque ? Personne n’a la main : précise l’attaquant, "
                f"`{PREFIX}atk gobelin 1 -> Pip`."
            )
        raise ValueError(
            f"Ton personnage n’est pas dans le combat : `{PREFIX}combat join`."
        )
    if not _can_act_on(ctx, attacker):
        raise ValueError("Tu ne peux attaquer qu’avec ton personnage.")

    tokens, flags = _split_attack_flags(rest.split())
    if not tokens:
        raise ValueError(f"Qui vises-tu ? Exemple : `{PREFIX}atk gobelin 1`.")
    target, weapon_tokens = _target_prefix(encounter, tokens)
    return AttackRequest(
        attacker=attacker,
        target=target,
        query=" ".join(weapon_tokens),
        advantage=flags.get("advantage"),  # type: ignore[arg-type]
        hit_bonus=int(flags["hit_bonus"]),
        manual_dice=str(flags.get("manual_dice") or ""),
        manual_type=str(flags.get("manual_type") or ""),
        two_handed=bool(flags.get("two_handed")),
        repeat=int(flags["repeat"]),
        reaction=bool(flags.get("reaction")),
    )


def _matches(query: str, *names: str) -> bool:
    key = fold_lookup_key(query).replace("_", "")
    return any(
        fold_lookup_key(name).replace("_", "").startswith(key) for name in names if name
    )


def _sheet_weapons(sheet: CharacterSheet) -> list[InventoryItem]:
    weapons = [item for item in sheet.equipment.items if item.kind == ITEM_KIND_WEAPON]
    # Weapons in hand first, then equipped ones, then the rest of the pack.
    return sorted(
        weapons,
        key=lambda item: (item.stored_in != STORED_HANDS, not item.equipped),
    )


def player_attack(sheet: CharacterSheet, query: str, *, two_handed: bool) -> Attack:
    if fold_lookup_key(query) in UNARMED_NAMES:
        return unarmed_attack(sheet)
    weapons = _sheet_weapons(sheet)
    if query:
        aliased = WEAPON_ALIASES_FR.get(fold_lookup_key(query), "")
        weapons = [
            item
            for item in weapons
            if _matches(query, item.name, item.slug)
            or (aliased and _matches(aliased, item.name, item.slug.replace("-", " ")))
        ]
        if not weapons:
            raise ValueError(
                f"Pas d’arme `{query}` sur la fiche de **{sheet.name}**. "
                f"Donne les dés à la main : `{PREFIX}atk <cible> +5 1d8+3`, ou `mains nues`."
            )
    elif not weapons:
        raise ValueError(
            f"Aucune arme sur la fiche de **{sheet.name}**. "
            f"Donne les dés à la main : `{PREFIX}atk <cible> +5 1d8+3`, ou `mains nues`."
        )
    item = weapons[0]
    indexed = _indexed_equipment(item.slug)
    attack = weapon_attack(
        sheet,
        name=item.name,
        raw=indexed[1] if indexed else None,
        two_handed=two_handed,
    )
    if attack is None:
        raise ValueError(
            f"Je ne connais pas les dégâts de **{item.name}** (arme maison ?). "
            f"Donne-les à la main : `{PREFIX}atk <cible> {item.name} +5 1d8+3 tranchant`."
        )
    return attack


def monster_attack(combatant: Combatant, query: str) -> Attack | None:
    attacks = [Attack.from_dict(data) for data in combatant.attacks]
    if query:
        attacks = [attack for attack in attacks if _matches(query, attack.name)]
        if not attacks:
            known = (
                ", ".join(Attack.from_dict(a).name for a in combatant.attacks)
                or "aucune"
            )
            raise ValueError(
                f"**{combatant.name}** n’a pas d’attaque `{query}`. Attaques : {known}."
            )
    return attacks[0] if attacks else None


def choose_attack(request: AttackRequest, sheet: CharacterSheet | None) -> Attack:
    attacker = request.attacker
    base: Attack | None = None
    try:
        if attacker.is_player and sheet is not None:
            base = player_attack(sheet, request.query, two_handed=request.two_handed)
        elif not attacker.is_player:
            base = monster_attack(attacker, request.query)
    except ValueError:
        if not request.manual_dice:
            raise
    if request.manual_dice:
        return Attack(
            name=request.query or (base.name if base else "Attaque"),
            hit=base.hit if base and not request.query else 0,
            damage=[DamagePart(dice=request.manual_dice, type=request.manual_type)],
            ranged=base.ranged if base else False,
        )
    if base is None:
        raise ValueError(
            f"**{attacker.name}** n’a pas d’attaque connue. Donne bonus et dégâts : "
            f"`{PREFIX}atk {request.target.name} +4 1d6+2 tranchant`."
        )
    return base


def _d20_text(outcome: AttackOutcome) -> str:
    roll = outcome.roll
    if roll.d20_pair is not None:
        kept = max(roll.d20_pair) if roll.advantage else min(roll.d20_pair)
        dropped = min(roll.d20_pair) if roll.advantage else max(roll.d20_pair)
        arrow = "⬆️" if roll.advantage else "⬇️"
        return f"{arrow} {kept} ~~{dropped}~~"
    return str(roll.kept_rolls[0])


def format_attack(
    attacker: Combatant, target: Combatant, outcome: AttackOutcome
) -> list[str]:
    attack = outcome.attack
    roll = outcome.roll
    extras = "".join(
        f" {'+' if extra.sign > 0 else '-'} {sum(values)}"
        for extra, values in roll.extra_rolls
    )
    modifier = f" {'+' if roll.flat_modifier >= 0 else '-'} {abs(roll.flat_modifier)}"
    against = f" contre CA {outcome.target_ac}" if outcome.target_ac is not None else ""
    if outcome.critical:
        verdict = "💥 **Critique !**"
    elif outcome.fumble:
        verdict = "💀 Échec critique"
    elif outcome.hit is None:
        verdict = "❓ CA inconnue : au MJ de trancher"
    elif outcome.hit:
        verdict = "✅ Touché"
    else:
        verdict = "❌ Raté"
    lines = [
        f"⚔️ **{attacker.name}** → **{target.name}** · {attack.name}",
        f"🎲 {_d20_text(outcome)}{extras}{modifier} = **{roll.total}**{against} → {verdict}",
    ]
    notes = [condition_note(note) for note in outcome.advantage_notes]
    notes += list(roll.effect_notes)
    if roll.lucky_used:
        notes.append("🍀 Chanceux")
    if roll.spent_inspiration:
        notes.append("✨ Inspiration dépensée")
    if notes:
        lines.append("· " + " · ".join(notes))
    for item in outcome.damage:
        lines.append(f"🩸 {format_damage_line(item)}")
    for part in outcome.skipped:
        lines.append(f"· {part.dice} en plus seulement avec avantage")
    return lines


def use_reaction(combatant: Combatant, wanted: bool) -> str:
    if not wanted:
        return ""
    if combatant.reaction_used:
        raise ValueError(
            f"**{combatant.name}** a déjà utilisé sa réaction depuis son dernier tour."
        )
    combatant.reaction_used = True
    return f"↩️ Réaction de **{combatant.name}**"


def condition_note(note: str) -> str:
    """`⬆️ cible prone` → `⬆️ cible 🛌 à terre`."""
    arrow, _, rest = note.partition(" ")
    side, _, key = rest.partition(" ")
    if side in ("attaquant", "cible") and key:
        return f"{arrow} {side} {condition_label(key)}"
    return note


async def handle_attack(ctx: Context, args: str) -> None:
    encounter = await _require_encounter(ctx)
    if encounter is None:
        return
    try:
        request = parse_attack(ctx, encounter, args)
        attacker_sheet = (
            get_sheet(user_id=request.attacker.user_id, guild_id=encounter.guild_id)
            if request.attacker.user_id is not None
            else None
        )
        attack = choose_attack(request, attacker_sheet)
        reaction_line = use_reaction(request.attacker, request.reaction)
    except ValueError as exc:
        await _fail(ctx, str(exc))
        return

    target = request.target
    target_sheet = (
        get_sheet(user_id=target.user_id, guild_id=encounter.guild_id)
        if target.user_id is not None
        else None
    )
    target_ac = target_sheet.ac if target_sheet is not None else target.ac
    lines: list[str] = [reaction_line] if reaction_line else []
    spent_inspiration = False
    for index in range(request.repeat):
        if target.dead or target.is_out:
            lines.append(f"**{target.name}** est déjà hors combat.")
            break
        context = AttackContext(
            attacker_conditions=condition_keys(encounter, request.attacker),
            target_conditions=condition_keys(encounter, target),
            requested=request.advantage,
        )
        outcome = resolve_attack(
            attack,
            attacker_sheet=attacker_sheet,
            context=context,
            target_ac=target_ac,
            hit_bonus=request.hit_bonus,
            resist=target.resist,
            immune=target.immune,
            vulnerable=target.vulnerable,
        )
        spent_inspiration = spent_inspiration or outcome.roll.spent_inspiration
        if request.repeat > 1:
            lines.append(f"__Attaque {index + 1}__")
        lines.extend(format_attack(request.attacker, target, outcome))
        if outcome.hit and outcome.total_damage:
            lines.extend(
                damage_combatant(
                    encounter, target, outcome.total_damage, critical=outcome.critical
                )
            )
        elif outcome.hit and outcome.damage:
            lines.append(f"**{target.name}** ne subit aucun dégât.")
    if spent_inspiration and attacker_sheet is not None:
        _save_spent_inspiration(encounter, request.attacker, attacker_sheet)
    save_encounter(encounter)
    await _reply(ctx, lines)
    await refresh_tracker(ctx, encounter)


def _save_spent_inspiration(
    encounter: Encounter, combatant: Combatant, sheet: CharacterSheet
) -> None:
    """`execute_roll` spends inspiration on the in-memory sheet; persist it."""
    if combatant.user_id is None:
        return

    def updater(stored: CharacterSheet) -> None:
        stored.inspired = sheet.inspired

    try:
        update_sheet(
            user_id=combatant.user_id, guild_id=encounter.guild_id, updater=updater
        )
    except ValueError:
        pass


async def handle_death_save(ctx: Context, args: str) -> None:
    encounter = await _require_encounter(ctx)
    if encounter is None:
        return
    try:
        if args.strip():
            target = _target(encounter, args)
        else:
            own = encounter.player(ctx.author.id)
            current = encounter.current()
            target = own or (current if is_staff(ctx) else None)
            if target is None:
                raise ValueError(
                    f"Ton personnage n’est pas dans le combat : `{PREFIX}combat join`."
                )
        if not _can_act_on(ctx, target):
            raise ValueError("Tu ne peux lancer que tes propres jets contre la mort.")
        lines = roll_death_save(encounter, target)
    except ValueError as exc:
        await _fail(ctx, str(exc))
        return
    save_encounter(encounter)
    await _reply(ctx, lines)
    await refresh_tracker(ctx, encounter)


async def handle_temp_hp(ctx: Context, args: str) -> None:
    encounter = await _require_encounter(ctx)
    if encounter is None:
        return
    tokens = args.split()
    if len(tokens) < 2 or not tokens[-1].isdigit():
        await _fail(ctx, f"Exemple : `{PREFIX}combat temp Pip 5`")
        return
    amount = int(tokens.pop())
    try:
        target, rest = _target_prefix(encounter, tokens)
        if rest:
            raise ValueError(f"Je ne comprends pas `{' '.join(rest)}`.")
    except ValueError as exc:
        await _fail(ctx, str(exc))
        return
    if not _can_act_on(ctx, target):
        await _fail(ctx, "Tu ne peux changer que les PV de ton personnage.")
        return
    line = set_temp_hp(target, amount)
    save_encounter(encounter)
    await _reply(ctx, [line])
    await refresh_tracker(ctx, encounter)


# --- spells and save actions ----------------------------------------------

_TARGET_SPLIT = re.compile(r"\s+(?:sur|on)\s+|\s*:\s*", re.IGNORECASE)
_SELF_WORDS = frozenset({"moi", "me", "soi", "self", "moi_meme"})


@dataclass
class CastRequest:
    caster: Combatant
    query: str
    targets: list[Combatant]
    level: int | None = None
    dc: int | None = None
    attack_bonus: int | None = None
    advantage: bool | None = None
    reaction: bool = False


def _take_int(tokens: list[str], index: int, word: str) -> int:
    value = tokens[index + 1] if index + 1 < len(tokens) else ""
    if not re.fullmatch(r"[+-]?\d+", value):
        raise ValueError(f"Il manque un nombre après `{word}`.")
    return int(value)


def parse_cast(ctx: Context, encounter: Encounter, args: str) -> CastRequest:
    parts = _ARROW.split(args.strip(), maxsplit=1)
    caster: Combatant | None = None
    if len(parts) == 2:
        caster = _target(encounter, parts[0])
        rest = parts[1]
    else:
        rest = parts[0]
    if caster is None:
        own = encounter.player(ctx.author.id)
        caster = (encounter.current() or own) if is_staff(ctx) else own
    if caster is None:
        if is_staff(ctx):
            raise ValueError(
                f"Qui lance le sort ? Précise-le : `{PREFIX}cast mage -> fireball sur Pip`."
            )
        raise ValueError(
            f"Ton personnage n’est pas dans le combat : `{PREFIX}combat join`."
        )
    if not _can_act_on(ctx, caster):
        raise ValueError("Tu ne peux lancer de sort qu’avec ton personnage.")

    pieces = _TARGET_SPLIT.split(rest, maxsplit=1)
    spell_part = pieces[0]
    target_part = pieces[1] if len(pieces) > 1 else ""
    tokens = spell_part.split()
    request = CastRequest(caster=caster, query="", targets=[])
    name_tokens: list[str] = []
    index = 0
    while index < len(tokens):
        token = tokens[index]
        key = fold_lookup_key(token)
        if key in ("niv", "niveau", "lvl", "level", "n"):
            request.level = _take_int(tokens, index, token)
            index += 1
        elif key in ("dc", "dd"):
            request.dc = _take_int(tokens, index, token)
            index += 1
        elif key in ("atk", "attaque", "toucher"):
            request.attack_bonus = _take_int(tokens, index, token)
            index += 1
        elif key in ("adv", "avantage", "advantage"):
            request.advantage = True
        elif key in ("dis", "desavantage", "disadvantage"):
            request.advantage = False
        elif key in _REACTION_TOKENS:
            request.reaction = True
        else:
            name_tokens.append(token)
        index += 1
    request.query = " ".join(name_tokens)
    if not request.query:
        raise ValueError(
            f"Quel sort ? Exemple : `{PREFIX}cast boule de feu sur gob 1, gob 2`."
        )
    for text in target_part.split(","):
        if not text.strip():
            continue
        if fold_lookup_key(text) in _SELF_WORDS:
            request.targets.append(caster)
        else:
            request.targets.append(_target(encounter, text))
    return request


async def resolve_spell(request: CastRequest) -> SpellInfo:
    caster = request.caster
    if not caster.is_player:
        for data in caster.save_actions:
            action = SpellInfo.from_dict(data)
            if _matches(request.query, action.name):
                return action
    return await lookup_spell(request.query)


def _spend_slot(encounter: Encounter, caster: Combatant, level: int) -> str:
    if caster.user_id is None or level < 1:
        return ""
    note: list[str] = []

    def updater(sheet: CharacterSheet) -> None:
        if not sheet.spell_slots.has_slots():
            note.append("emplacements non suivis sur la fiche")
            return
        available = sheet.spell_slots.get_current(level)
        if available < 1:
            higher = (
                sheet.spell_slots.lowest_available(level + 1) if level < 9 else None
            )
            hint = f" Lance-le plus haut : `niv {higher}`." if higher else ""
            raise ValueError(
                f"Plus d’emplacement de sort de niveau {level} disponible.{hint}"
            )
        sheet.spell_slots.use(level)
        note.append(
            f"emplacement niv. {level} : {available - 1}/{sheet.spell_slots.get_maximum(level)}"
        )

    update_sheet(user_id=caster.user_id, guild_id=encounter.guild_id, updater=updater)
    return note[0] if note else ""


def _ac_of(encounter: Encounter, combatant: Combatant) -> int | None:
    if combatant.user_id is not None:
        sheet = get_sheet(user_id=combatant.user_id, guild_id=encounter.guild_id)
        if sheet is not None:
            return sheet.ac
    return combatant.ac


def _round_robin(targets: list[Combatant], count: int) -> list[Combatant]:
    return [targets[index % len(targets)] for index in range(count)]


def cast_spell(
    encounter: Encounter,
    request: CastRequest,
    info: SpellInfo,
    caster_sheet: CharacterSheet | None,
) -> list[str]:
    caster = request.caster
    is_action = info.dc is not None and not caster.is_player
    cast_level = request.level if request.level is not None else info.level
    if not is_action and info.level and cast_level < info.level:
        raise ValueError(f"{info.name} est un sort de niveau {info.level} au minimum.")
    if cast_level > 9:
        raise ValueError("Les emplacements de sort vont jusqu’au niveau 9.")

    if caster_sheet is not None:
        dc, attack_bonus, modifier = caster_numbers(caster_sheet)
        character_level = caster_sheet.level
    else:
        dc = info.dc or caster.spell_dc
        attack_bonus = (
            caster.spell_attack
            if caster.spell_attack is not None
            else (dc - 8 if dc else None)
        )
        modifier, character_level = 0, 1
    dc = request.dc if request.dc is not None else dc
    attack_bonus = (
        request.attack_bonus if request.attack_bonus is not None else attack_bonus
    )

    targets = request.targets
    if not targets and info.heal_dice:
        targets = [caster]
    if (info.save or info.attack or info.damage or info.conditions) and not targets:
        raise ValueError(
            f"Sur qui ? Exemple : `{PREFIX}cast {info.name.lower()} sur gobelin 1, gobelin 2`."
        )
    if info.save and dc is None:
        raise ValueError(
            f"Je ne connais pas le DD de **{caster.name}** : ajoute `dc 15`."
        )
    if info.attack and attack_bonus is None:
        raise ValueError(
            f"Je ne connais pas le bonus d’attaque de **{caster.name}** : ajoute `atk +6`."
        )

    lines: list[str] = []
    reaction = use_reaction(caster, request.reaction)
    if reaction:
        lines.append(reaction)
    slot_note = "" if is_action else _spend_slot(encounter, caster, cast_level)
    header = f"✨ **{caster.name}** lance **{info.name}**"
    if cast_level > info.level and not is_action:
        header += f" au niveau {cast_level}"
    if slot_note:
        header += f" ({slot_note})"
    lines.append(header)
    if info.concentration:
        lines.extend(start_concentration(encounter, caster, info.name))

    damage = damage_for_cast(
        info, cast_level=cast_level, character_level=character_level
    )
    rounds = None if info.concentration else info.duration_rounds
    count = projectile_count(
        info, cast_level=cast_level, character_level=character_level
    )

    def apply_conditions(target: Combatant) -> None:
        for key in info.conditions:
            add_condition(encounter, target, key, rounds)
            if info.concentration:
                link_to_concentration(caster, target, key)
            lines.append(f"· **{target.name}** : {condition_label(key)}")
            if concentration_breaks_on(key):
                lines.extend(
                    end_concentration(encounter, target, reason=condition_label(key))
                )

    if info.attack:
        attack = Attack(
            name=info.name,
            hit=int(attack_bonus or 0),
            damage=damage,
            ranged=info.attack == "R",
        )
        for index, target in enumerate(_round_robin(targets, count)):
            if target.is_out:
                lines.append(f"**{target.name}** est déjà hors combat.")
                continue
            outcome = resolve_attack(
                attack,
                attacker_sheet=caster_sheet,
                context=AttackContext(
                    attacker_conditions=condition_keys(encounter, caster),
                    target_conditions=condition_keys(encounter, target),
                    requested=request.advantage,
                ),
                target_ac=_ac_of(encounter, target),
                resist=target.resist,
                immune=target.immune,
                vulnerable=target.vulnerable,
            )
            if count > 1:
                lines.append(f"__Rayon {index + 1}__")
            lines.extend(format_attack(caster, target, outcome)[1:])
            if outcome.hit:
                if outcome.total_damage:
                    lines.extend(
                        damage_combatant(
                            encounter,
                            target,
                            outcome.total_damage,
                            critical=outcome.critical,
                        )
                    )
                apply_conditions(target)
        return lines

    if info.save:
        # Area damage is rolled once for every target.
        rolled = [
            roll_damage_part(part, critical=False, resist=[], immune=[], vulnerable=[])
            for part in damage
        ]
        if rolled:
            lines.append(
                "🩸 "
                + " + ".join(
                    f"`{item.notation}` → {item.rolled}"
                    + (
                        f" {damage_type_label(item.part.type)}"
                        if item.part.type
                        else ""
                    )
                    for item in rolled
                )
            )
        label = SAVE_LABELS.get(info.save, info.save.upper())
        for target in targets:
            if target.is_out:
                lines.append(f"· **{target.name}** est déjà hors combat.")
                continue
            result = roll_save(encounter, target, info.save, int(dc))
            line = f"· **{target.name}** — sauvegarde {label} : {result.text(int(dc))}"
            total = 0
            for item in rolled:
                amount = item.rolled
                if result.success:
                    amount = amount // 2 if info.half_on_save else 0
                amount, _note = _defended_amount(target, amount, item.part.type)
                total += amount
            if rolled:
                line += f" → {total} dégâts"
            lines.append(line)
            if total:
                lines.extend(damage_combatant(encounter, target, total))
            if not result.success:
                apply_conditions(target)
        if info.concentration and info.conditions:
            lines.append(
                "↻ Les cibles refont souvent le jet à la fin de leur tour : "
                f"`{PREFIX}combat cond <cible> <état>` pour retirer l’état."
            )
        return lines

    heal = heal_for_cast(info, cast_level=cast_level)
    if heal:
        amount, roll_line = roll_amount(heal)
        if info.heal_adds_modifier:
            amount += modifier
        lines.append(
            (roll_line or f"🎲 {heal}")
            + (
                f" + {modifier} (caractéristique)"
                if info.heal_adds_modifier and modifier
                else ""
            )
            + f" = **{amount}** PV"
        )
        for target in targets:
            lines.extend(heal_combatant(encounter, target, amount))
        return lines

    if damage:
        # Automatic hits (Magic Missile): one roll per dart, spread over the targets.
        totals: dict[str, int] = {}
        for target in _round_robin(targets, count):
            for part in damage:
                item = roll_damage_part(
                    part,
                    critical=False,
                    resist=target.resist,
                    immune=target.immune,
                    vulnerable=target.vulnerable,
                )
                totals[target.id] = totals.get(target.id, 0) + item.applied
        if count > 1:
            lines.append(f"🎯 {count} projectiles, répartis entre les cibles.")
        for target in targets:
            if target.id in totals:
                lines.append(f"· **{target.name}** : {totals[target.id]} dégâts")
                lines.extend(damage_combatant(encounter, target, totals[target.id]))
        return lines

    if info.conditions:
        for target in targets:
            apply_conditions(target)
        return lines

    lines.append("· Effet à gérer à la main (pas de jet ni de dégâts automatiques).")
    return lines


SAVE_LABELS = {
    "str": "FOR",
    "dex": "DEX",
    "con": "CON",
    "int": "INT",
    "wis": "SAG",
    "cha": "CHA",
}


async def handle_cast(ctx: Context, args: str) -> None:
    encounter = await _require_encounter(ctx)
    if encounter is None:
        return
    try:
        request = parse_cast(ctx, encounter, args)
        info = await resolve_spell(request)
    except ValueError as exc:
        await _fail(ctx, str(exc))
        return
    # Reload: the spell lookup awaited, another command may have saved meanwhile.
    fresh = load_encounter(guild_id=encounter.guild_id, channel_id=encounter.channel_id)
    if fresh is None:
        await _fail(ctx, NO_COMBAT)
        return
    encounter = fresh
    request.caster = encounter.get(request.caster.id) or request.caster
    request.targets = [encounter.get(t.id) or t for t in request.targets]
    caster_sheet = (
        get_sheet(user_id=request.caster.user_id, guild_id=encounter.guild_id)
        if request.caster.user_id is not None
        else None
    )
    try:
        lines = cast_spell(encounter, request, info, caster_sheet)
    except ValueError as exc:
        await _fail(ctx, str(exc))
        return
    save_encounter(encounter)
    await _reply(ctx, lines)
    await refresh_tracker(ctx, encounter)


async def handle_reaction(ctx: Context, args: str) -> None:
    encounter = await _require_encounter(ctx)
    if encounter is None:
        return
    try:
        target = (
            _target(encounter, args)
            if args.strip()
            else encounter.player(ctx.author.id)
        )
        if target is None:
            raise ValueError(
                f"Ton personnage n’est pas dans le combat : `{PREFIX}combat join`."
            )
        if not _can_act_on(ctx, target):
            raise ValueError("Tu ne peux changer que la réaction de ton personnage.")
    except ValueError as exc:
        await _fail(ctx, str(exc))
        return
    target.reaction_used = not target.reaction_used
    line = (
        f"↩️ **{target.name}** a utilisé sa réaction."
        if target.reaction_used
        else f"↩️ **{target.name}** récupère sa réaction."
    )
    save_encounter(encounter)
    await _reply(ctx, [line])
    await refresh_tracker(ctx, encounter)


async def handle_concentration(ctx: Context, args: str) -> None:
    encounter = await _require_encounter(ctx)
    if encounter is None:
        return
    tokens = args.split()
    try:
        if tokens:
            target, rest = _target_prefix(encounter, tokens)
        else:
            target, rest = encounter.player(ctx.author.id), []
        if target is None:
            raise ValueError(
                f"Exemple : `{PREFIX}combat conc Pip bénédiction` ou `… Pip fin`."
            )
        if not _can_act_on(ctx, target):
            raise ValueError(
                "Tu ne peux changer que la concentration de ton personnage."
            )
    except ValueError as exc:
        await _fail(ctx, str(exc))
        return
    spell = " ".join(rest)
    if not spell or fold_lookup_key(spell) in ("fin", "stop", "end", "aucun"):
        lines = end_concentration(encounter, target) or [
            f"**{target.name}** ne se concentre sur rien."
        ]
    else:
        lines = start_concentration(encounter, target, spell)
        lines.append(f"🧠 **{target.name}** se concentre sur {spell}.")
    save_encounter(encounter)
    await _reply(ctx, lines)
    await refresh_tracker(ctx, encounter)


# --- registration ---------------------------------------------------------


def setup_combat(bot: Bot) -> None:
    @bot.hybrid_group(
        name="combat",
        aliases=["fight"],
        invoke_without_command=True,
        help=COMBAT_HELP,
    )
    async def combat_group(ctx: Context) -> None:
        if ctx.guild is not None and load_encounter(
            guild_id=ctx.guild.id, channel_id=ctx.channel.id
        ):
            await handle_show(ctx)
            return
        await ctx.send_help(ctx.command)

    @combat_group.command(
        name="start",
        aliases=["debut", "début"],
        help=command_help(
            "Lance un combat dans ce salon (MJ).",
            f"`{PREFIX}combat start [monstres, @joueurs]`",
            f"`{PREFIX}combat start gobelin x3, @Pip`",
        ),
    )
    @app_commands.describe(args="Monstres et joueurs, ex. gobelin x3, @Pip")
    async def combat_start(ctx: Context, *, args: str = "") -> None:
        await handle_start(ctx, args)

    @combat_group.command(
        name="add",
        aliases=["ajout", "ajoute"],
        help=command_help(
            "Ajoute des monstres (5etools ou maison) ou des joueurs (MJ).",
            f"`{PREFIX}combat add <monstre> [xN] [moy] [pv N ca N init N] [# nom]`",
            f"`{PREFIX}combat add goblin x3` · `{PREFIX}combat add ogre moy, @Pip`",
            f"`{PREFIX}combat add bandit pv 11 ca 12 init 1 # Chef bandit`",
        ),
    )
    @app_commands.describe(args="ex. goblin x3, ogre moy, @Pip")
    async def combat_add(ctx: Context, *, args: str = "") -> None:
        await handle_add(ctx, args)

    @combat_group.command(
        name="join",
        aliases=["rejoindre"],
        help=command_help(
            "Ton personnage rejoint le combat. Initiative tirée (DEX) ou donnée.",
            f"`{PREFIX}combat join [initiative]`",
            f"`{PREFIX}combat join 17`",
        ),
    )
    @app_commands.describe(args="Ton initiative si tu l’as déjà lancée, ex. 17")
    async def combat_join(ctx: Context, *, args: str = "") -> None:
        await handle_join(ctx, args)

    @combat_group.command(
        name="next",
        aliases=["suivant"],
        help=command_help(
            "Passe au tour suivant.", f"`{PREFIX}combat next` · `{PREFIX}next`"
        ),
    )
    async def combat_next(ctx: Context) -> None:
        await handle_next(ctx)

    @combat_group.command(
        name="dmg",
        aliases=["degats", "dégâts", "damage"],
        help=command_help(
            "Inflige des dégâts : nombre ou dés, une ou plusieurs cibles.",
            f"`{PREFIX}combat dmg <cible[, cible…]> <montant> [moitié]`",
            f"`{PREFIX}combat dmg gobelin 1 8` · `{PREFIX}combat dmg gob 1, gob 2 8d6 moitié`",
        ),
    )
    @app_commands.describe(
        args="Cibles puis montant, ex. gobelin 1 8 ou gob 1, gob 2 8d6"
    )
    async def combat_dmg(ctx: Context, *, args: str = "") -> None:
        await _change_hp(ctx, args, healing=False)

    @combat_group.command(
        name="heal",
        aliases=["soin", "soigne"],
        help=command_help(
            "Rend des PV : nombre ou dés.",
            f"`{PREFIX}combat heal <cible> <montant>`",
            f"`{PREFIX}combat heal Pip 2d4+2`",
        ),
    )
    @app_commands.describe(args="Cible puis montant, ex. Pip 2d4+2")
    async def combat_heal(ctx: Context, *, args: str = "") -> None:
        await _change_hp(ctx, args, healing=True)

    @combat_group.command(
        name="cond",
        aliases=["etat", "état", "condition"],
        help=command_help(
            "Ajoute un état, pour N rounds si tu donnes un nombre. Sans nombre, "
            "un état déjà présent est retiré.",
            f"`{PREFIX}combat cond <cible> <état> [rounds]`",
            f"`{PREFIX}combat cond gobelin 2 à terre 1` · `{PREFIX}combat cond Pip béni 10`",
        ),
    )
    @app_commands.describe(args="Cible, état, rounds, ex. gobelin 2 à terre 1")
    async def combat_cond(ctx: Context, *, args: str = "") -> None:
        await handle_condition(ctx, args)

    @combat_group.command(
        name="init",
        help=command_help(
            "Change l’initiative d’un combattant.",
            f"`{PREFIX}combat init <cible> <valeur>`",
            f"`{PREFIX}combat init Pip 18`",
        ),
    )
    @app_commands.describe(args="Cible puis valeur, ex. Pip 18")
    async def combat_init(ctx: Context, *, args: str = "") -> None:
        await handle_init(ctx, args)

    @combat_group.command(
        name="remove",
        aliases=["retire", "enleve", "enlève"],
        help=command_help(
            "Retire un combattant (MJ).", f"`{PREFIX}combat remove <cible>`"
        ),
    )
    @app_commands.describe(args="Cible, ex. gobelin 3")
    async def combat_remove(ctx: Context, *, args: str = "") -> None:
        await handle_remove(ctx, args)

    @combat_group.command(
        name="end",
        aliases=["fin", "stop"],
        help=command_help("Termine le combat (MJ).", f"`{PREFIX}combat end`"),
    )
    async def combat_end(ctx: Context) -> None:
        await handle_end(ctx)

    @combat_group.command(
        name="show",
        aliases=["voir"],
        help=command_help(
            "Remet le suivi du combat en bas du salon.", f"`{PREFIX}combat show`"
        ),
    )
    async def combat_show(ctx: Context) -> None:
        await handle_show(ctx)

    @combat_group.command(
        name="mj",
        aliases=["gm", "dm"],
        help=command_help(
            "Suivi détaillé (PV exacts, CA) pour le MJ seul.", f"`{PREFIX}combat mj`"
        ),
    )
    async def combat_mj(ctx: Context) -> None:
        await handle_mj(ctx)

    @combat_group.command(
        name="attack",
        aliases=["atk", "attaque"],
        help=ATTACK_HELP,
    )
    @app_commands.describe(args="Cible, arme, options, ex. gobelin 1 dague adv")
    async def combat_attack(ctx: Context, *, args: str = "") -> None:
        await handle_attack(ctx, args)

    @combat_group.command(
        name="death",
        aliases=["mort", "jsm", "deathsave"],
        help=command_help(
            "Jet de sauvegarde contre la mort (à 0 PV). 20 : 1 PV ; 1 : deux échecs.",
            f"`{PREFIX}combat death` · `{PREFIX}mort`",
        ),
    )
    @app_commands.describe(args="Personnage (MJ seulement), sinon le tien")
    async def combat_death(ctx: Context, *, args: str = "") -> None:
        await handle_death_save(ctx, args)

    @combat_group.command(
        name="temp",
        aliases=["pvt", "thp"],
        help=command_help(
            "Donne des PV temporaires (ils ne se cumulent pas).",
            f"`{PREFIX}combat temp <cible> <PV>`",
            f"`{PREFIX}combat temp Pip 5`",
        ),
    )
    @app_commands.describe(args="Cible puis PV, ex. Pip 5")
    async def combat_temp(ctx: Context, *, args: str = "") -> None:
        await handle_temp_hp(ctx, args)

    @combat_group.command(name="cast", aliases=["sort", "lance"], help=CAST_HELP)
    @app_commands.describe(
        args="Sort, options, puis sur <cibles>, ex. fireball sur gob 1, gob 2"
    )
    async def combat_cast(ctx: Context, *, args: str = "") -> None:
        await handle_cast(ctx, args)

    @combat_group.command(
        name="reac",
        aliases=["reaction", "réaction"],
        help=command_help(
            "Marque la réaction d’un combattant comme utilisée (ou la rend).",
            f"`{PREFIX}combat reac [cible]`",
        ),
    )
    @app_commands.describe(args="Cible, sinon ton personnage")
    async def combat_reac(ctx: Context, *, args: str = "") -> None:
        await handle_reaction(ctx, args)

    @combat_group.command(
        name="conc",
        aliases=["concentration"],
        help=command_help(
            "Note ou termine une concentration (les sorts lancés avec `cast` le font seuls).",
            f"`{PREFIX}combat conc <cible> <sort>` · `{PREFIX}combat conc <cible> fin`",
        ),
    )
    @app_commands.describe(args="Cible puis sort, ou fin")
    async def combat_conc(ctx: Context, *, args: str = "") -> None:
        await handle_concentration(ctx, args)

    @bot.hybrid_command(name="cast", aliases=["sort", "lance"], help=CAST_HELP)
    @app_commands.describe(
        args="Sort, options, puis sur <cibles>, ex. fireball sur gob 1, gob 2"
    )
    async def cast_command(ctx: Context, *, args: str = "") -> None:
        await handle_cast(ctx, args)

    @bot.hybrid_command(name="atk", aliases=["attaque", "attack"], help=ATTACK_HELP)
    @app_commands.describe(args="Cible, arme, options, ex. gobelin 1 dague adv")
    async def atk_command(ctx: Context, *, args: str = "") -> None:
        await handle_attack(ctx, args)

    @bot.hybrid_command(
        name="mort",
        aliases=["jsm"],
        help=command_help(
            "Combat : jet de sauvegarde contre la mort.", f"`{PREFIX}mort`"
        ),
    )
    async def death_command(ctx: Context) -> None:
        await handle_death_save(ctx, "")

    @bot.hybrid_command(
        name="next",
        aliases=["suivant"],
        help=command_help(
            "Combat : passe au tour suivant (MJ, ou toi pendant ton tour).",
            f"`{PREFIX}next`",
        ),
    )
    async def next_command(ctx: Context) -> None:
        await handle_next(ctx)
