from sheets.data import CharacterSheet


def apply_hp(sheet: CharacterSheet, current: int, maximum: int | None = None) -> None:
    if current < 0:
        raise ValueError("Current HP cannot be negative.")

    sheet.hp_current = current
    if maximum is not None:
        if maximum < 1:
            raise ValueError("Max HP must be at least 1.")
        sheet.hp_max = maximum
    elif sheet.hp_max == 0:
        sheet.hp_max = current

    if sheet.hp_current > sheet.hp_max:
        sheet.hp_current = sheet.hp_max
    if sheet.hp_current > 0:
        sheet.reset_death_saves()
