import unittest
from unittest.mock import patch

from srd.fivetools import loader


class TestGetIndexOnEventLoop(unittest.IsolatedAsyncioTestCase):
    async def test_refuses_sync_build_inside_running_loop(self) -> None:
        with (
            patch.object(loader, "_index", None),
            patch.object(loader, "_build_index") as build,
        ):
            with self.assertRaises(loader.IndexNotReadyError):
                loader.get_index()
        build.assert_not_called()

    async def test_ensure_index_loaded_builds_off_loop(self) -> None:
        sentinel = object()
        with (
            patch.object(loader, "_index", None),
            patch.object(loader, "_build_index", return_value=sentinel),
        ):
            self.assertIs(await loader.ensure_index_loaded(), sentinel)
            self.assertIs(loader.get_index(), sentinel)


class TestGetIndexWithoutLoop(unittest.TestCase):
    def test_builds_inline_for_scripts(self) -> None:
        sentinel = object()
        with (
            patch.object(loader, "_index", None),
            patch.object(loader, "_build_index", return_value=sentinel),
        ):
            self.assertIs(loader.get_index(), sentinel)


if __name__ == "__main__":
    unittest.main()
