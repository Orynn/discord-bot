import unittest
from types import SimpleNamespace

from bot.selects import fresh_component_id, select_menus_from_message
from srd.definition_view import (
    DEFINITION_SELECT_ID,
    DefinitionSelectView,
    definition_view_from_message,
    entries_from_select_options,
)
from srd.glossary import GlossaryEntry
from sheets.spell_view import SPELL_SELECT_PREFIX, SpellSelectView, spell_view_from_message


def _entry(name: str = "Fireball") -> GlossaryEntry:
    return GlossaryEntry(name=name, kind="spell", slug=name.lower(), url="", parent_slug=None)


class _FakeRow:
    def __init__(self, children) -> None:
        self.children = children


class _FakeMessage:
    def __init__(self, components) -> None:
        self.components = components


class TestFreshComponentId(unittest.TestCase):
    def test_ids_are_unique(self) -> None:
        first = fresh_component_id()
        second = fresh_component_id()
        self.assertNotEqual(first, second)
        self.assertGreater(first, 0)
        self.assertGreater(second, 0)


class TestDefinitionSelectReset(unittest.TestCase):
    def test_single_option_is_not_preselected(self) -> None:
        view = DefinitionSelectView([_entry()])
        select = view.children[0]
        self.assertEqual(len(select.options), 1)
        self.assertFalse(select.options[0].default)
        self.assertEqual(select.custom_id, DEFINITION_SELECT_ID)

    def test_parses_option_values_including_pipes_in_name(self) -> None:
        entries = entries_from_select_options(
            [
                SimpleNamespace(value="noop"),
                SimpleNamespace(value="subclass|wizard|wizard|School of Evocation"),
                SimpleNamespace(value="item|bag-of-holding||Bag | Holding"),
            ]
        )
        self.assertEqual(len(entries), 2)
        self.assertEqual(entries[0].kind, "subclass")
        self.assertEqual(entries[0].parent_slug, "wizard")
        self.assertEqual(entries[1].name, "Bag | Holding")

    def test_rebuilds_view_from_message_without_defaults(self) -> None:
        original = DefinitionSelectView([_entry(), _entry("Mage Armor")])
        original.children[0].options[0].default = True
        message = _FakeMessage([_FakeRow(original.children)])

        rebuilt = definition_view_from_message(message)
        self.assertIsNotNone(rebuilt)
        rebuilt_select = rebuilt.children[0]
        self.assertEqual(
            [option.value for option in rebuilt_select.options],
            [option.value for option in original.children[0].options],
        )
        self.assertTrue(all(not option.default for option in rebuilt_select.options))
        self.assertNotEqual(rebuilt_select.id, original.children[0].id)

    def test_ignores_empty_persistent_stub(self) -> None:
        stub = DefinitionSelectView()
        message = _FakeMessage([_FakeRow(stub.children)])
        self.assertIsNone(definition_view_from_message(message))


class TestSpellSelectReset(unittest.TestCase):
    def test_rebuilds_all_chunks_from_message(self) -> None:
        entries = [(f"slug-{index}", f"Spell {index:02d}", "1st-level") for index in range(26)]
        original = SpellSelectView(entries)
        self.assertEqual(len(original.children), 2)
        message = _FakeMessage([_FakeRow([child]) for child in original.children])

        rebuilt = spell_view_from_message(message)
        self.assertIsNotNone(rebuilt)
        rebuilt_values = [option.value for child in rebuilt.children for option in child.options]
        original_values = [option.value for child in original.children for option in child.options]
        self.assertEqual(sorted(rebuilt_values), sorted(original_values))
        self.assertTrue(
            all(not option.default for child in rebuilt.children for option in child.options)
        )
        self.assertTrue(all(child.custom_id.startswith(SPELL_SELECT_PREFIX) for child in rebuilt.children))

    def test_single_spell_is_not_preselected(self) -> None:
        view = SpellSelectView([("fireball", "Fireball", "3rd-level")])
        select = view.children[0]
        self.assertEqual(len(select.options), 1)
        self.assertFalse(select.options[0].default)


class TestSelectMenusFromMessage(unittest.TestCase):
    def test_reads_action_row_children(self) -> None:
        select = SimpleNamespace(options=[SimpleNamespace(value="a")], custom_id="x")
        message = _FakeMessage([_FakeRow([select])])
        self.assertEqual(select_menus_from_message(message), [select])

    def test_returns_empty_without_message(self) -> None:
        self.assertEqual(select_menus_from_message(None), [])
