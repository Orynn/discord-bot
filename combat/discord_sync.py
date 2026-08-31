from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from copy import deepcopy
from dataclasses import dataclass
from enum import Enum

from combat.storage import CombatState, get_combat

logger = logging.getLogger(__name__)

DISCORD_CONTENT_MAX = 2000


class BoardEditResult(str, Enum):
    UPDATED = "updated"
    MISSING = "missing"
    SKIPPED = "skipped"
    FAILED = "failed"


Pusher = Callable[..., Awaitable[BoardEditResult]]

_bot = None
_pusher: Pusher | None = None


@dataclass
class _PendingEdit:
    guild_id: int
    scope_id: int
    content: str | None
    ended: bool
    snapshot: CombatState | None


_pending: dict[tuple[int, int], _PendingEdit] = {}
_inflight: set[tuple[int, int]] = set()
_tasks: set[asyncio.Task] = set()
_stale_ended: dict[tuple[int, int], _PendingEdit] = {}
_edit_locks: dict[tuple[int, int], asyncio.Lock] = {}


def bind_bot(bot) -> None:
    global _bot
    _bot = bot


def get_bot():
    return _bot


def bind_pusher(pusher: Pusher | None) -> None:
    global _pusher
    _pusher = pusher


def clip_discord_content(content: str | None) -> str | None:
    if content is None:
        return None
    if len(content) <= DISCORD_CONTENT_MAX:
        return content
    return content[: DISCORD_CONTENT_MAX - 1] + "…"


def _key(guild_id: int, scope_id: int) -> tuple[int, int]:
    return (int(guild_id), int(scope_id))


def discord_edit_lock(*, guild_id: int, scope_id: int) -> asyncio.Lock:
    key = _key(guild_id, scope_id)
    lock = _edit_locks.get(key)
    if lock is None:
        lock = asyncio.Lock()
        _edit_locks[key] = lock
    return lock


def remember_stale_ended(state: CombatState, *, content: str | None) -> None:
    if state.board_message_id is None:
        return
    key = _key(state.guild_id, state.scope_id)
    _stale_ended[key] = _PendingEdit(
        guild_id=int(state.guild_id),
        scope_id=int(state.scope_id),
        content=content,
        ended=True,
        snapshot=deepcopy(state),
    )


def forget_stale_ended(*, guild_id: int, scope_id: int) -> None:
    _stale_ended.pop(_key(guild_id, scope_id), None)


def take_stale_ended(
    *, guild_id: int, scope_id: int
) -> tuple[CombatState, str | None] | None:
    item = _stale_ended.pop(_key(guild_id, scope_id), None)
    if item is None or item.snapshot is None:
        return None
    return item.snapshot, item.content


def sync_combat_message(
    state: CombatState | None,
    *,
    content: str | None = None,
    ended: bool = False,
) -> None:
    """Queue a coalesced Discord board edit. Does not wait for HTTP."""
    if state is None or state.board_message_id is None or _pusher is None:
        return
    key = _key(state.guild_id, state.scope_id)
    if not ended:
        forget_stale_ended(guild_id=state.guild_id, scope_id=state.scope_id)
    _pending[key] = _PendingEdit(
        guild_id=int(state.guild_id),
        scope_id=int(state.scope_id),
        content=content,
        ended=ended,
        snapshot=deepcopy(state) if ended else None,
    )
    _start_drain(key)


def _start_drain(key: tuple[int, int]) -> None:
    if key in _inflight:
        return
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        logger.exception("No running loop to update Discord combat message")
        return
    _inflight.add(key)
    task = loop.create_task(_drain(key))
    _tasks.add(task)
    task.add_done_callback(_tasks.discard)


async def _drain(key: tuple[int, int]) -> None:
    try:
        while True:
            item = _pending.pop(key, None)
            if item is None:
                return
            await _apply_pending(item)
    except Exception:
        logger.exception("Failed to update Discord combat message")
    finally:
        _inflight.discard(key)
        if key in _pending:
            _start_drain(key)


def _record_ended_result(
    item: _PendingEdit, result: object
) -> None:
    if result is BoardEditResult.FAILED and item.snapshot is not None:
        remember_stale_ended(item.snapshot, content=item.content)
        return
    forget_stale_ended(guild_id=item.guild_id, scope_id=item.scope_id)


async def _apply_pending(item: _PendingEdit) -> None:
    if _pusher is None:
        return
    async with discord_edit_lock(guild_id=item.guild_id, scope_id=item.scope_id):
        if item.ended:
            if item.snapshot is None:
                return
            result = await _pusher(
                item.snapshot, content=item.content, ended=True
            )
            _record_ended_result(item, result)
            return
        state = get_combat(guild_id=item.guild_id, scope_id=item.scope_id)
        if state is None or state.board_message_id is None:
            return
        await _pusher(state, content=item.content, ended=False)


async def flush_discord_sync() -> None:
    """Wait until queued Discord edits finish. Tests only."""
    while _tasks:
        await asyncio.gather(*list(_tasks), return_exceptions=True)
