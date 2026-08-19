def format_player_category_name(
    name: str,
    *,
    width: int = 25,
    emoji: str = "🐉",
) -> str:
    """Build `🐉-----------LEO-----------🐉` style category names."""
    label = name.strip().upper()
    if not label:
        raise ValueError("Player name cannot be empty.")

    min_dashes_each_side = 3
    max_label_len = width - (min_dashes_each_side * 2)
    if max_label_len < 1:
        raise ValueError("player_category_width is too small in config.json.")
    if len(label) > max_label_len:
        label = label[:max_label_len]

    padding = width - len(label)
    left = padding // 2
    right = padding - left
    return f"{emoji}{'-' * left}{label}{'-' * right}{emoji}"
