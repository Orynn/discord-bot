import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from srd.fivetools import index_cache, loader


class TestIndexCache(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self._tmp.name) / "cache"
        self._patch = patch.object(index_cache, "CACHE_DIR", self.dir)
        self._patch.start()

    def tearDown(self) -> None:
        self._patch.stop()
        self._tmp.cleanup()

    def test_round_trip_and_stale_cleanup(self) -> None:
        old = index_cache.cache_path("aaaa")
        index_cache.save_cached_index(old, {"v": 1})
        new = index_cache.cache_path("bbbb")
        self.assertNotEqual(old, new)
        index_cache.save_cached_index(new, {"v": 2})
        self.assertEqual(index_cache.load_cached_index(new), {"v": 2})
        self.assertFalse(old.exists())
        self.assertIsNone(index_cache.load_cached_index(old))

    def test_unreadable_cache_is_ignored(self) -> None:
        path = index_cache.cache_path("cccc")
        self.dir.mkdir(parents=True)
        path.write_bytes(b"not a pickle")
        self.assertIsNone(index_cache.load_cached_index(path))

    def test_build_uses_cache_then_rebuilds_on_demand(self) -> None:
        sentinel = loader.FiveToolsIndex()
        sentinel.loaded_sources.append("cached")
        with patch("srd.fivetools.paths.content_fingerprint", return_value="dddd"):
            index_cache.save_cached_index(index_cache.cache_path("dddd"), sentinel)
            with patch.object(loader.FiveToolsIndex, "load") as load:
                cached = loader._build_index()
                self.assertEqual(cached.loaded_sources, ["cached"])
                load.assert_not_called()
                rebuilt = loader._build_index(use_cache=False)
                load.assert_called_once()
        self.assertEqual(rebuilt.loaded_sources, [])
        self.assertEqual(
            index_cache.load_cached_index(
                index_cache.cache_path("dddd")
            ).loaded_sources,
            [],
        )


if __name__ == "__main__":
    unittest.main()
