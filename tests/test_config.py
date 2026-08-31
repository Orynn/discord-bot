import importlib
import json
import os
import sys
import tempfile
import unittest
import unittest.mock
from pathlib import Path


class TestConfigImport(unittest.TestCase):
    def test_import_without_discord_token(self) -> None:
        env = os.environ.copy()
        env.pop("DISCORD_TOKEN", None)
        module_name = "config"
        sys.modules.pop(module_name, None)
        try:
            with unittest.mock.patch.dict(os.environ, env, clear=True):
                with unittest.mock.patch("dotenv.load_dotenv"):
                    config = importlib.import_module(module_name)
                    self.assertIsNone(config.TOKEN)
                    with self.assertRaises(ValueError):
                        config.require_token()
        finally:
            sys.modules.pop(module_name, None)
            importlib.import_module(module_name)

    def test_set_campaign_category_id_updates_memory_and_file(self) -> None:
        import config as app_config

        previous = app_config.CAMPAIGN_CATEGORY_ID
        previous_guild = app_config.CAMPAIGN_GUILD_ID
        try:
            with tempfile.TemporaryDirectory() as tmp:
                path = Path(tmp) / "config.json"
                path.write_text("{}", encoding="utf-8")
                with unittest.mock.patch.object(app_config, "_CONFIG_PATH", path):
                    app_config.set_campaign_category_id(42, guild_id=7)
                self.assertEqual(app_config.CAMPAIGN_CATEGORY_ID, 42)
                self.assertEqual(app_config.CAMPAIGN_GUILD_ID, 7)
                stored = json.loads(path.read_text(encoding="utf-8"))
                self.assertEqual(stored["campaign_category_id"], 42)
                self.assertEqual(stored["campaign_guild_id"], 7)
        finally:
            app_config.CAMPAIGN_CATEGORY_ID = previous
            app_config.CAMPAIGN_GUILD_ID = previous_guild
            app_config.config["campaign_category_id"] = previous
            if previous_guild is None:
                app_config.config.pop("campaign_guild_id", None)
            else:
                app_config.config["campaign_guild_id"] = previous_guild


    def test_is_home_guild_uses_id_then_name(self) -> None:
        import config as app_config
        from types import SimpleNamespace

        previous_home = app_config.HOME_GUILD_ID
        previous_campaign = app_config.CAMPAIGN_GUILD_ID
        previous_name = app_config.HOME_GUILD_NAME
        try:
            app_config.HOME_GUILD_ID = 11
            self.assertTrue(app_config.is_home_guild(SimpleNamespace(id=11, name="X")))
            self.assertFalse(
                app_config.is_home_guild(SimpleNamespace(id=22, name="Potato Head"))
            )
            self.assertTrue(app_config.is_home_guild(None))

            app_config.HOME_GUILD_ID = None
            app_config.CAMPAIGN_GUILD_ID = None
            app_config.HOME_GUILD_NAME = "Potato Head"
            self.assertTrue(
                app_config.is_home_guild(SimpleNamespace(id=99, name="potato head"))
            )
            self.assertFalse(
                app_config.is_home_guild(SimpleNamespace(id=99, name="Le Moulin"))
            )
        finally:
            app_config.HOME_GUILD_ID = previous_home
            app_config.CAMPAIGN_GUILD_ID = previous_campaign
            app_config.HOME_GUILD_NAME = previous_name


if __name__ == "__main__":
    unittest.main()
