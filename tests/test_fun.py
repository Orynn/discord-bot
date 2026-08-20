import unittest

from fun.commands import GIF_PATH


class TestGetNaked(unittest.TestCase):
    def test_dismay_gif_exists(self) -> None:
        self.assertTrue(GIF_PATH.is_file(), f"missing {GIF_PATH}")
        self.assertGreater(GIF_PATH.stat().st_size, 1000)


if __name__ == "__main__":
    unittest.main()
