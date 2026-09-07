import unittest

from initiative.storage import (
    InitiativeEntry,
    InitiativeState,
    already_listed,
    match_initiative_entries,
)


class TestAlreadyListed(unittest.TestCase):
    def test_matches_user_id_or_name(self) -> None:
        state = InitiativeState(
            channel_id=1,
            active_index=0,
            order=[InitiativeEntry(name="Arthur", total=12, user_id=7)],
        )
        self.assertTrue(already_listed(state, user_id=7))
        self.assertTrue(already_listed(state, name="arthur"))
        self.assertFalse(already_listed(state, user_id=8))
        self.assertFalse(already_listed(state, name="Gobelin"))


class TestMatchInitiativeEntries(unittest.TestCase):
    def test_exact_match_is_casefold(self) -> None:
        order = [
            InitiativeEntry(name="Arthur", total=12),
            InitiativeEntry(name="Art", total=10),
        ]
        matches = match_initiative_entries(order, "art")
        self.assertEqual([entry.name for entry in matches], ["Art"])

    def test_mid_name_substring_does_not_match(self) -> None:
        order = [InitiativeEntry(name="Martin", total=12)]
        self.assertEqual(match_initiative_entries(order, "art"), [])

    def test_unique_prefix_matches(self) -> None:
        order = [
            InitiativeEntry(name="Gobelin", total=8),
            InitiativeEntry(name="Hero", total=15),
        ]
        matches = match_initiative_entries(order, "gob")
        self.assertEqual([entry.name for entry in matches], ["Gobelin"])

    def test_ambiguous_prefix_matches_nothing(self) -> None:
        order = [
            InitiativeEntry(name="Martin", total=8),
            InitiativeEntry(name="Martha", total=9),
        ]
        self.assertEqual(match_initiative_entries(order, "mar"), [])
