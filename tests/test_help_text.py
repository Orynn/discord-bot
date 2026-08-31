import unittest

from bot.help_text import (
    build_combat_help_sections,
    build_help_sections,
    build_hunger_help_sections,
    build_roleplay_help_sections,
    build_sheet_help_sections,
    build_srd_help_sections,
)


class TestHelpSections(unittest.TestCase):
    def test_main_help_includes_overview_and_combat(self) -> None:
        sections = build_help_sections(prefix=";", is_admin=False)
        keys = [section.key for section in sections]
        self.assertEqual(keys[0], "overview")
        self.assertIn("combat", keys)
        self.assertIn("initiative", keys)

    def test_combat_help_has_play_section(self) -> None:
        sections = build_combat_help_sections(prefix=";", is_admin=False)
        keys = [section.key for section in sections]
        self.assertEqual(keys[:4], ["start", "play", "deck", "init"])

    def test_combat_help_admin_section_only_for_admins(self) -> None:
        player_sections = build_combat_help_sections(prefix=";", is_admin=False)
        admin_sections = build_combat_help_sections(prefix=";", is_admin=True)
        self.assertEqual(len(player_sections), 4)
        self.assertEqual(len(admin_sections), 5)
        self.assertEqual(admin_sections[-1].key, "admin")

    def test_help_mentions_detailed_guides(self) -> None:
        overview = build_help_sections(prefix=";", is_admin=False)[0]
        self.assertIn(";help combat", overview.body)
        self.assertIn(";help sheet", overview.body)
        self.assertIn(";help srd", overview.body)
        self.assertIn(";help hunger", overview.body)
        self.assertIn(";help roleplay", overview.body)
        self.assertIn(";help all", overview.body)
        self.assertIn(";commande -h", overview.body)

    def test_srd_help_has_examples_not_pipe_list(self) -> None:
        lookup = next(
            section
            for section in build_help_sections(prefix=";", is_admin=False)
            if section.key == "lookup"
        )
        self.assertNotIn("spell|species", lookup.body)
        self.assertIn(";srd <type> <name>", lookup.body)
        self.assertIn(";help srd", lookup.body)

        sections = build_srd_help_sections(prefix=";")
        self.assertEqual([section.key for section in sections], ["lookup", "search"])
        self.assertIn(";srd <type> <name>", sections[0].body)
        self.assertIn("`monster`", sections[0].body)
        self.assertIn(";srd spell fireball", sections[0].footer or "")
        self.assertNotIn("spell|species", sections[0].body)

    def test_help_ties_hunger_to_the_clock(self) -> None:
        roleplay = next(
            section
            for section in build_help_sections(prefix=";", is_admin=False)
            if section.key == "roleplay"
        )
        self.assertIn("la faim suit cette horloge", roleplay.body)
        self.assertIn(";get naked", roleplay.body)
        self.assertIn(";image", roleplay.body)
        self.assertIn(";dessine", roleplay.body)
        self.assertIn(";think", roleplay.body)
        self.assertIn(";whisper", roleplay.body)
        self.assertIn(";scene set", roleplay.body)
        self.assertIn(";arrive", roleplay.body)

        guide = build_roleplay_help_sections(prefix=";")
        self.assertEqual(
            [section.key for section in guide], ["speech", "scene", "table"]
        )
        self.assertIn(";pense", guide[0].body)
        self.assertIn(";scene set La taverne", guide[1].body)

        sheet = next(
            section
            for section in build_sheet_help_sections(prefix=";", is_admin=False)
            if section.key == "status"
        )
        self.assertIn(";time", sheet.body)
        self.assertIn("jour de calendrier", sheet.body)
        self.assertIn(";sheet status", sheet.body)
        self.assertIn(";status", sheet.body)

        admin = next(
            section
            for section in build_help_sections(prefix=";", is_admin=True)
            if section.key == "admin"
        )
        self.assertIn("fait avancer la faim de ce joueur", admin.body)
        self.assertIn(";hunger skip @joueur", admin.body)

        player = build_hunger_help_sections(prefix=";", is_admin=False)[0]
        self.assertIn("horloge de campagne", player.body)
        self.assertNotIn(";hunger skip", player.body)

        dm = build_hunger_help_sections(prefix=";", is_admin=True)[0]
        self.assertIn(";time advance 1d", dm.body)
        self.assertIn(";hunger skip @joueur", dm.body)

    def test_sheet_help_mentions_leaving_gear(self) -> None:
        resources = next(
            section
            for section in build_sheet_help_sections(prefix=";", is_admin=False)
            if section.key == "resources"
        )
        self.assertIn(";sheet gear let", resources.body)
        self.assertIn("let <objet|all>", resources.body)
        self.assertIn(";sheet gear take", resources.body)
        self.assertIn(";sheet gear custom", resources.body)
        self.assertIn(";sheet gear bag", resources.body)
        self.assertIn("créer un sac perso", resources.body)
        self.assertIn("met à jour la CA", resources.body)

    def test_combat_help_requires_player_section(self) -> None:
        start = next(
            section
            for section in build_combat_help_sections(prefix=";", is_admin=False)
            if section.key == "start"
        )
        self.assertIn("salon OOC ou roleplay du joueur", start.body)
        admin = next(
            section
            for section in build_combat_help_sections(prefix=";", is_admin=True)
            if section.key == "admin"
        )
        self.assertIn("salon OOC/roleplay du joueur", admin.body)

    def test_help_embed_uses_section_color_and_fields(self) -> None:
        from bot.help_text import HELP_SHEET_COLOR, build_help_embed

        sections = build_help_sections(prefix=";", is_admin=False)
        overview = build_help_embed(
            title="Arkann — commands", sections=sections, index=0
        )
        sheet = build_help_embed(title="Arkann — commands", sections=sections, index=2)

        self.assertIn("📖", overview.title)
        self.assertIn("Pour commencer", overview.description or "")
        self.assertTrue(overview.fields)
        self.assertEqual(sheet.color.value, HELP_SHEET_COLOR)
        self.assertIn("📋", sheet.title)

    def test_lookup_help_does_not_repeat_slash(self) -> None:
        lookup = next(
            section
            for section in build_help_sections(prefix=";", is_admin=False)
            if section.key == "lookup"
        )
        names = [name for name, _value in lookup.fields]
        self.assertEqual(names, ["📖 5etools"])
        self.assertEqual(lookup.body.count("/srd"), 1)

    def test_sheet_resources_splits_gear_and_skills(self) -> None:
        resources = next(
            section
            for section in build_sheet_help_sections(prefix=";", is_admin=False)
            if section.key == "resources"
        )
        names = [name for name, _value in resources.fields]
        self.assertIn("🎒 Équipement", names)
        self.assertIn("🎯 Compétences", names)


class TestCommandHelpEmbed(unittest.TestCase):
    def test_splits_usage_and_examples(self) -> None:
        from bot.help_text import command_help, split_command_help

        text = command_help(
            "Lance des dés.",
            "`;roll 1d20`",
            "`;roll athletics` — compétence",
        )
        description, usage, extras = split_command_help(text)
        self.assertEqual(description, "Lance des dés.")
        self.assertEqual(usage, "`;roll 1d20`")
        self.assertEqual(extras, ("`;roll athletics` — compétence",))

    def test_glued_backtick_usage(self) -> None:
        from bot.help_text import split_command_help

        description, usage, extras = split_command_help(
            "Start combat. `;combat start [tavern]`"
        )
        self.assertEqual(description, "Start combat.")
        self.assertEqual(usage, "`;combat start [tavern]`")
        self.assertEqual(extras, ())

    def test_glued_usage_keeps_trailing_note(self) -> None:
        from bot.help_text import split_command_help

        _description, usage, extras = split_command_help(
            "Create a bag. `;sheet gear bag <name>` (15 kg)"
        )
        self.assertEqual(usage, "`;sheet gear bag <name>`")
        self.assertEqual(extras, ("(15 kg)",))

    def test_embed_has_usage_examples_and_aliases(self) -> None:
        from bot.help_text import build_command_help_embed, command_help

        embed = build_command_help_embed(
            qualified_name="roll",
            help_text=command_help(
                "Jets de dés.",
                "`;roll 1d20`",
                "`;roll athletics`",
            ),
            usage="`;roll`",
            aliases=["`;r`"],
        )
        names = [field.name for field in embed.fields]
        self.assertEqual(names, ["⌨️ Usage", "📌 Exemples", "🏷️ Alias"])
        self.assertEqual(embed.description, "Jets de dés.")
        self.assertEqual(embed.fields[0].value, "`;roll 1d20`")
        self.assertIn("-h", embed.footer.text or "")

    def test_summary_omits_usage(self) -> None:
        from bot.help_text import command_help, command_help_summary

        summary = command_help_summary(
            command_help("Ajoute un objet.", "`;sheet gear add <nom>`")
        )
        self.assertEqual(summary, "Ajoute un objet.")
        self.assertNotIn("Usage", summary)

    def test_group_embed_lists_subcommands(self) -> None:
        from bot.help_text import build_group_help_embed

        embed = build_group_help_embed(
            qualified_name="init",
            help_text="Ordre de tour.",
            usage="`;init`",
            subcommands=[("`;init add`", "Ajoute quelqu’un"), ("`;init next`", "")],
            aliases=[],
        )
        names = [field.name for field in embed.fields]
        self.assertEqual(names, ["⌨️ Usage", "📂 Sous-commandes"])
        self.assertIn("`;init add` — Ajoute quelqu’un", embed.fields[1].value)
        self.assertIn("• `;init next`", embed.fields[1].value)
