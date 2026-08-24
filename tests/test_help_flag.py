import unittest
from unittest.mock import AsyncMock, MagicMock

from bot.help_commands import maybe_send_command_help, wants_command_help


def _ctx(*, rest: str = "", command=True, interaction=None) -> MagicMock:
    ctx = MagicMock()
    ctx.command = object() if command else None
    ctx.interaction = interaction
    ctx.view = MagicMock()
    ctx.view.rest = rest
    ctx.send_help = AsyncMock()
    return ctx


class TestCommandHelpFlag(unittest.IsolatedAsyncioTestCase):
    def test_detects_dash_h(self) -> None:
        self.assertTrue(wants_command_help(_ctx(rest=" -h")))
        self.assertTrue(wants_command_help(_ctx(rest="--help")))
        self.assertTrue(wants_command_help(_ctx(rest="Wolf -h")))
        self.assertTrue(wants_command_help(_ctx(rest="-H")))

    def test_ignores_normal_args_and_slash(self) -> None:
        self.assertFalse(wants_command_help(_ctx(rest="")))
        self.assertFalse(wants_command_help(_ctx(rest="Wolf 2h")))
        self.assertFalse(wants_command_help(_ctx(rest="-h", command=False)))
        self.assertFalse(wants_command_help(_ctx(rest="-h", interaction=object())))

    async def test_sends_help_instead_of_running(self) -> None:
        ctx = _ctx(rest="-h")
        handled = await maybe_send_command_help(ctx)
        self.assertTrue(handled)
        ctx.send_help.assert_awaited_once_with(ctx.command)

    async def test_leaves_normal_invoke_alone(self) -> None:
        ctx = _ctx(rest="Wolf")
        handled = await maybe_send_command_help(ctx)
        self.assertFalse(handled)
        ctx.send_help.assert_not_awaited()
