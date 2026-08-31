import logging
import sys

from discord.utils import stream_supports_colour

RESET = "\x1b[0m"
DIM = "\x1b[2m"
BOLD = "\x1b[1m"
LOGGER_WIDTH = 14

LEVEL_STYLES: dict[int, tuple[str, str]] = {
    logging.DEBUG: ("\x1b[36m", "DEBUG"),
    logging.INFO: ("\x1b[32m", "INFO "),
    logging.WARNING: ("\x1b[33m", "WARN "),
    logging.ERROR: ("\x1b[31m", "ERROR"),
    logging.CRITICAL: ("\x1b[41m\x1b[37m", "CRIT "),
}


def _short_logger_name(name: str) -> str:
    if name == "__main__":
        return "main".ljust(LOGGER_WIDTH)
    if len(name) > LOGGER_WIDTH:
        return name[: LOGGER_WIDTH - 1] + "…"
    return name.ljust(LOGGER_WIDTH)


def _level_label(record: logging.LogRecord) -> str:
    return LEVEL_STYLES.get(record.levelno, ("", record.levelname))[1]


class _PlainFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        ts = self.formatTime(record, "%H:%M")
        name = _short_logger_name(record.name)
        level = _level_label(record)
        message = record.getMessage()
        line = f"{ts}  {level}  {name}  {message}"
        if record.exc_info:
            if not record.exc_text:
                record.exc_text = self.formatException(record.exc_info)
            line = f"{line}\n{record.exc_text}"
            record.exc_text = None
        return line


class _ColorFormatter(_PlainFormatter):
    def format(self, record: logging.LogRecord) -> str:
        color, level = LEVEL_STYLES.get(
            record.levelno, ("\x1b[37m", record.levelname[:5].ljust(5))
        )
        ts = self.formatTime(record, "%H:%M")
        name = _short_logger_name(record.name)
        message = record.getMessage()
        line = (
            f"{DIM}{ts}{RESET}  "
            f"{color}{BOLD}{level}{RESET}  "
            f"\x1b[35m{name}{RESET}  "
            f"{message}"
        )
        if record.exc_info:
            if not record.exc_text:
                record.exc_text = self.formatException(record.exc_info)
            line = f"{line}\n\x1b[31m{record.exc_text}{RESET}"
            record.exc_text = None
        return line


def setup_logging(*, level: int = logging.INFO) -> None:
    root = logging.getLogger()
    if root.handlers:
        root.setLevel(level)
        return

    handler = logging.StreamHandler(sys.stdout)
    if stream_supports_colour(sys.stdout):
        handler.setFormatter(_ColorFormatter())
    else:
        handler.setFormatter(_PlainFormatter())

    root.addHandler(handler)
    root.setLevel(level)

    logging.getLogger("discord").setLevel(logging.WARNING)
    logging.getLogger("discord.http").setLevel(logging.WARNING)
    # discord.py adds its own handler in bot.run() by default, which duplicates
    # root logs (discord.* propagates to root). Pass log_handler=None in main.
