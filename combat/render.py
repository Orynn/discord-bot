from __future__ import annotations

import io
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from combat.map import (
    COLUMNS,
    cell_label,
    ensure_positions,
    is_wall,
    map_height,
    map_width,
    attack_targets_in_range,
    reachable_cells,
    remaining_squares,
    same_side,
    speed_squares,
    weapon_range_squares,
)
from combat.monster_sheet import display_monster_name
from combat.storage import CombatState, CombatantState
from combat.templates import template_for_state
from combat.tokens import load_monster_token
from sheets.portrait import load_portrait_image

CELL = 128
MARGIN_LEFT = 56
MARGIN_TOP = 56
LEGEND_WIDTH = 300
MARGIN_BOTTOM = 40
TOKEN_RADIUS = 42
MAP_FILENAME = "combat-map.png"

BG = (18, 20, 24)
GRID = (58, 64, 76)
LABEL = (210, 214, 222)
ACTIVE = (72, 196, 96)
DOWN = (120, 124, 132)
TOKEN_TEXT = (248, 249, 250)
PC_FILL = (58, 122, 196)
NPC_FILL = (176, 52, 45)
LEGEND_MUTED = (154, 158, 166)
MOVE_FILL = (86, 196, 220, 38)
MOVE_EDGE = (168, 222, 236, 220)
RANGE_EDGE = (228, 92, 68, 230)
ALLY_EDGE = (86, 160, 228, 230)
SELF_EDGE = (72, 196, 96, 230)
NAMEPLATE = (12, 14, 18, 210)
SHADOW = (0, 0, 0, 110)

FLOOR_TONES = {
    "arena": ((60, 66, 80), (32, 36, 44)),
    "tavern": ((92, 68, 50), (50, 36, 26)),
    "dungeon": ((56, 60, 68), (28, 32, 36)),
    "camp": ((62, 80, 52), (34, 46, 30)),
}
WALL_TONES = {
    "arena": ((78, 64, 52), (96, 80, 64), (52, 42, 34)),
    "tavern": ((92, 66, 46), (112, 84, 58), (64, 46, 32)),
    "dungeon": ((62, 60, 66), (78, 76, 82), (42, 40, 46)),
    "camp": ((70, 60, 44), (88, 76, 54), (48, 40, 30)),
}

_FONT_CANDIDATES = (
    Path("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"),
    Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
    Path("/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf"),
    Path("/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf"),
)


def _font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    for path in _FONT_CANDIDATES:
        if path.is_file():
            return ImageFont.truetype(str(path), size)
    return ImageFont.load_default()


def token_initials(name: str) -> str:
    parts = [part for part in name.replace("_", " ").split() if part]
    if len(parts) >= 2:
        return f"{parts[0][0]}{parts[1][0]}".upper()
    cleaned = "".join(char for char in name if char.isalnum())
    return (cleaned[:2] or "?").upper()


def _is_down(combatant: CombatantState) -> bool:
    if combatant.user_id is None:
        return combatant.hp <= 0
    return combatant.hp <= 0 or combatant.death_save_failures >= 3


def cell_px(state: CombatState) -> int:
    longest = max(map_width(state), map_height(state))
    if longest <= 8:
        return CELL
    if longest <= 12:
        return 96
    return 72


def _cell_box(x: int, y: int, cell: int) -> tuple[int, int, int, int]:
    left = MARGIN_LEFT + x * cell
    top = MARGIN_TOP + y * cell
    return left, top, left + cell, top + cell


def _cell_center(x: int, y: int, cell: int) -> tuple[int, int]:
    left, top, _, _ = _cell_box(x, y, cell)
    return left + cell // 2, top + cell // 2


def circular_token(src: Image.Image, size: int) -> Image.Image:
    image = src.convert("RGBA")
    width, height = image.size
    side = min(width, height)
    left = (width - side) // 2
    top = (height - side) // 2
    cropped = image.crop((left, top, left + side, top + side))
    resized = cropped.resize((size, size), Image.Resampling.LANCZOS)
    mask = Image.new("L", (size, size), 0)
    ImageDraw.Draw(mask).ellipse((1, 1, size - 2, size - 2), fill=255)
    token = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    token.paste(resized, (0, 0))
    token.putalpha(mask)
    return token


def _gray_keep_alpha(token: Image.Image) -> Image.Image:
    red, green, blue, alpha = token.split()
    gray = Image.merge("RGB", (red, green, blue)).convert("L")
    return Image.merge("RGBA", (gray, gray, gray, alpha))


def _portrait_for(
    state: CombatState, combatant: CombatantState
) -> Image.Image | None:
    if combatant.user_id is None:
        return load_monster_token(display_monster_name(combatant.name))
    return load_portrait_image(guild_id=state.guild_id, user_id=combatant.user_id)


def _hp_pip_color(combatant: CombatantState) -> tuple[int, int, int]:
    if combatant.max_hp <= 0 or combatant.hp <= 0:
        return (88, 90, 96)
    ratio = combatant.hp / combatant.max_hp
    if ratio > 0.5:
        return (72, 176, 96)
    if ratio > 0.25:
        return (220, 176, 48)
    return (196, 64, 56)


def render_combat_map(state: CombatState) -> io.BytesIO:
    ensure_positions(state)
    cell = cell_px(state)
    cols = map_width(state)
    rows = map_height(state)
    width = MARGIN_LEFT + cols * cell + LEGEND_WIDTH
    height = MARGIN_TOP + rows * cell + MARGIN_BOTTOM
    image = Image.new("RGBA", (width, height), (*BG, 255))
    draw = ImageDraw.Draw(image)
    label_font = _font(22 if cell >= 96 else 16)
    token_font = _font(28 if cell >= 96 else 20)
    legend_font = _font(18)
    title_font = _font(22)
    plate_font = _font(14)

    _draw_board(draw, state, label_font, cell)
    _draw_overlays(image, state, cell)

    portraits: dict[str, Image.Image | None] = {
        key: _portrait_for(state, combatant)
        for key, combatant in state.combatants.items()
    }
    by_cell: dict[tuple[int, int], list[CombatantState]] = {}
    for combatant in state.combatants.values():
        if combatant.x is None or combatant.y is None:
            continue
        by_cell.setdefault((combatant.x, combatant.y), []).append(combatant)

    active = state.active_combatant()
    draw = ImageDraw.Draw(image)
    for (x, y), group in by_cell.items():
        cx, cy = _cell_center(x, y, cell)
        for index, combatant in enumerate(group):
            offset = (index - (len(group) - 1) / 2) * max(10, cell // 7)
            _draw_token(
                image,
                draw,
                combatant,
                cx + int(offset),
                cy - 6,
                active=active is not None
                and combatant.name.lower() == active.name.lower(),
                font=token_font,
                plate_font=plate_font,
                portrait=portraits.get(combatant.name.lower()),
                radius=max(16, min(TOKEN_RADIUS, cell // 3)),
            )

    _draw_legend(image, draw, state, title_font, legend_font, portraits, cell)
    rgb = Image.new("RGB", image.size, BG)
    rgb.paste(image, mask=image.split()[-1])
    buffer = io.BytesIO()
    rgb.save(buffer, format="PNG")
    buffer.seek(0)
    return buffer


def _draw_board(
    draw: ImageDraw.ImageDraw,
    state: CombatState,
    label_font: ImageFont.FreeTypeFont | ImageFont.ImageFont,
    cell: int,
) -> None:
    theme = template_for_state(state).theme
    floor_a, floor_b = FLOOR_TONES.get(theme, FLOOR_TONES["arena"])
    wall, wall_hi, wall_lo = WALL_TONES.get(theme, WALL_TONES["arena"])
    cols = map_width(state)
    rows = map_height(state)
    grid_bottom = MARGIN_TOP + rows * cell
    grid_right = MARGIN_LEFT + cols * cell

    for y in range(rows):
        for x in range(cols):
            left, top, right, bottom = _cell_box(x, y, cell)
            if is_wall(state, x, y):
                draw.rectangle((left, top, right - 1, bottom - 1), fill=wall)
                draw.line((left, top, right - 1, top), fill=wall_hi, width=2)
                draw.line(
                    (left, bottom - 1, right - 1, bottom - 1), fill=wall_lo, width=2
                )
            else:
                fill = floor_a if (x + y) % 2 == 0 else floor_b
                draw.rectangle((left, top, right - 1, bottom - 1), fill=fill)

    for x in range(cols + 1):
        px = MARGIN_LEFT + x * cell
        draw.line((px, MARGIN_TOP, px, grid_bottom), fill=GRID, width=1)
    for y in range(rows + 1):
        py = MARGIN_TOP + y * cell
        draw.line((MARGIN_LEFT, py, grid_right, py), fill=GRID, width=1)

    for x, letter in enumerate(COLUMNS[:cols]):
        cx = MARGIN_LEFT + x * cell + cell // 2
        draw.text((cx, 16), letter, fill=LABEL, font=label_font, anchor="mt")
    for y in range(rows):
        cy = MARGIN_TOP + y * cell + cell // 2
        draw.text((24, cy), str(y + 1), fill=LABEL, font=label_font, anchor="mm")


def _draw_overlays(image: Image.Image, state: CombatState, cell: int) -> None:
    overlay = Image.new("RGBA", image.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    active = state.active_combatant()
    moves = reachable_cells(state, active) if active is not None else set()
    threatened: set[tuple[int, int]] = set()
    friendly: set[tuple[int, int]] = set()
    if active is not None and not active.acted:
        for target in attack_targets_in_range(
            state, active, weapon_range_squares(active)
        ):
            if target.x is None or target.y is None:
                continue
            if same_side(active, target):
                friendly.add((target.x, target.y))
            else:
                threatened.add((target.x, target.y))

    for x, y in moves:
        if is_wall(state, x, y):
            continue
        left, top, right, bottom = _cell_box(x, y, cell)
        draw.rectangle((left + 1, top + 1, right - 2, bottom - 2), fill=MOVE_FILL)
        draw.rectangle(
            (left + 3, top + 3, right - 4, bottom - 4),
            outline=MOVE_EDGE,
            width=2,
        )
    pad = max(6, cell // 12)
    for x, y in threatened:
        left, top, right, bottom = _cell_box(x, y, cell)
        draw.ellipse(
            (left + pad, top + pad, right - pad, bottom - pad),
            outline=RANGE_EDGE,
            width=3,
        )
    for x, y in friendly:
        left, top, right, bottom = _cell_box(x, y, cell)
        draw.ellipse(
            (left + pad, top + pad, right - pad, bottom - pad),
            outline=ALLY_EDGE,
            width=3,
        )
    if active is not None and active.x is not None and active.y is not None:
        left, top, right, bottom = _cell_box(active.x, active.y, cell)
        draw.ellipse(
            (left + pad, top + pad, right - pad, bottom - pad),
            outline=SELF_EDGE,
            width=3,
        )
    image.alpha_composite(overlay)


def _draw_token(
    image: Image.Image,
    draw: ImageDraw.ImageDraw,
    combatant: CombatantState,
    cx: int,
    cy: int,
    *,
    active: bool,
    font: ImageFont.FreeTypeFont | ImageFont.ImageFont,
    plate_font: ImageFont.FreeTypeFont | ImageFont.ImageFont,
    portrait: Image.Image | None,
    radius: int = TOKEN_RADIUS,
) -> None:
    down = _is_down(combatant)
    fill = DOWN if down else (PC_FILL if combatant.user_id is not None else NPC_FILL)
    draw.ellipse(
        (cx - radius + 4, cy - radius + 8, cx + radius + 4, cy + radius + 8),
        fill=SHADOW,
    )
    if active and not down:
        draw.ellipse(
            (cx - radius - 6, cy - radius - 6, cx + radius + 6, cy + radius + 6),
            outline=ACTIVE,
            width=4,
        )
    if portrait is not None:
        token = circular_token(portrait, radius * 2)
        if down:
            token = _gray_keep_alpha(token)
        image.paste(token, (cx - radius, cy - radius), token)
    else:
        draw.ellipse(
            (cx - radius, cy - radius, cx + radius, cy + radius),
            fill=fill,
            outline=(12, 12, 14),
            width=3,
        )
        draw.text(
            (cx, cy),
            token_initials(combatant.name),
            fill=TOKEN_TEXT,
            font=font,
            anchor="mm",
        )
    draw.ellipse(
        (cx - radius, cy - radius, cx + radius, cy + radius),
        outline=(12, 12, 14),
        width=2,
    )
    if combatant.user_id is not None:
        pip = 8
        px = cx + radius - 6
        py = cy + radius - 6
        draw.ellipse(
            (px - pip, py - pip, px + pip, py + pip),
            fill=_hp_pip_color(combatant),
            outline=(12, 12, 14),
            width=2,
        )
    _draw_nameplate(draw, combatant.name, cx, cy + radius + 4, plate_font)


def _draw_nameplate(
    draw: ImageDraw.ImageDraw,
    name: str,
    cx: int,
    top: int,
    font: ImageFont.FreeTypeFont | ImageFont.ImageFont,
) -> None:
    label = name if len(name) <= 14 else f"{name[:13]}…"
    bbox = draw.textbbox((0, 0), label, font=font)
    width = bbox[2] - bbox[0]
    height = bbox[3] - bbox[1]
    pad_x, pad_y = 7, 3
    box = (
        cx - width // 2 - pad_x,
        top,
        cx + width // 2 + pad_x,
        top + height + pad_y * 2,
    )
    draw.rounded_rectangle(box, radius=6, fill=NAMEPLATE)
    draw.text((cx, top + pad_y), label, fill=LABEL, font=font, anchor="mt")


def _draw_legend(
    image: Image.Image,
    draw: ImageDraw.ImageDraw,
    state: CombatState,
    title_font: ImageFont.FreeTypeFont | ImageFont.ImageFont,
    legend_font: ImageFont.FreeTypeFont | ImageFont.ImageFont,
    portraits: dict[str, Image.Image | None],
    cell: int,
) -> None:
    left = MARGIN_LEFT + map_width(state) * cell + 20
    room = template_for_state(state).label
    draw.text((left, 18), room, fill=LABEL, font=title_font)
    y = 56
    max_y = MARGIN_TOP + map_height(state) * cell - 48
    for name in state.turn_order:
        if y > max_y:
            break
        combatant = state.combatants.get(name.lower())
        if combatant is None:
            continue
        marker = "➤" if name == state.active_name else "•"
        label = cell_label(combatant.x, combatant.y, state)
        color = ACTIVE if name == state.active_name else LABEL
        if _is_down(combatant):
            color = DOWN
        portrait = portraits.get(combatant.name.lower())
        if portrait is not None:
            token = circular_token(portrait, 22)
            if _is_down(combatant):
                token = _gray_keep_alpha(token)
            image.paste(token, (left, y), token)
            text_x = left + 28
        else:
            text_x = left
        hp = ""
        if combatant.user_id is not None:
            hp = f"  {combatant.hp}/{combatant.max_hp}"
        line = f"{marker} {combatant.name}  {label}{hp}"
        draw.text((text_x, y + 2), line[:26], fill=color, font=legend_font)
        y += 28

    active = state.active_combatant()
    if active is None:
        return
    left_sq = remaining_squares(active)
    total = speed_squares(active.speed)
    action = "faite" if active.acted else "prête"
    footer = f"{left_sq}/{total} cases · action {action}"
    draw.text(
        (left, MARGIN_TOP + map_height(state) * cell - 4),
        footer,
        fill=LEGEND_MUTED,
        font=legend_font,
        anchor="ls",
    )
