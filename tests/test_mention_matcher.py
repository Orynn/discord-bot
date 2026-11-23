import random
import re
import unittest

from srd import glossary


def _regex_spans(names: list[str], text: str) -> list[tuple[int, int]]:
    """The former matcher: one alternation, longest names first."""
    ordered = sorted(dict.fromkeys(n.lower() for n in names), key=len, reverse=True)
    pattern = re.compile(
        rf"(?<![\w\[])(?:{'|'.join(map(re.escape, ordered))})(?![\w\]])", re.IGNORECASE
    )
    return [(m.start(), m.end()) for m in pattern.finditer(text)]


class TestMentionMatcher(unittest.TestCase):
    NAMES = [
        "Fire",
        "Fireball",
        "Fire Bolt",
        "Hunter's Mark",
        "Potion of Healing",
        "Potion of Healing (Greater)",
        "+1 Shield",
        "Shield",
        "Prone",
        "Élan",
    ]

    def setUp(self) -> None:
        glossary.reset_store()
        for name in self.NAMES:
            glossary.register_item(name=name, kind="spell", slug=name.lower())
        glossary._store.loaded = True
        glossary._store.rebuild_index()

    def _spans(self, text: str) -> list[str]:
        return [text[s:e] for s, e, _o, _e in glossary.iter_mention_spans(text)]

    def test_cases(self) -> None:
        self.assertEqual(
            self._spans("A fire bolt, then FIREBALL!"), ["fire bolt", "FIREBALL"]
        )
        self.assertEqual(self._spans("Hunter's Mark and Firebolt"), ["Hunter's Mark"])
        self.assertEqual(
            self._spans("drink a Potion of Healing (Greater)."),
            ["Potion of Healing (Greater)"],
        )
        self.assertEqual(
            self._spans("a +1 Shield or a shield"), ["+1 Shield", "shield"]
        )
        self.assertEqual(self._spans("[Fireball](url) and Prone]"), [])
        self.assertEqual(self._spans("élan vital, Prone"), ["élan", "Prone"])

    def test_same_spans_as_the_old_regex(self) -> None:
        words = "le la a of the and [x] ( ) - ; , . ' Fire fire-bolt potion +1".split()
        rng = random.Random(7)
        matcher = glossary._store.matcher
        assert matcher is not None
        for _ in range(300):
            tokens = [
                rng.choice(self.NAMES) if rng.random() < 0.4 else rng.choice(words)
                for _ in range(30)
            ]
            text = "".join(
                t + rng.choice([" ", ",", "-", "'", "[", "]", ". "]) for t in tokens
            )
            self.assertEqual(matcher.spans(text), _regex_spans(self.NAMES, text), text)


if __name__ == "__main__":
    unittest.main()
