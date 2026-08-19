import unittest

from sheets.ddb_pdf import _parse_class_and_level, extract_ddb_fields, parse_ddb_pdf


class TestDdbPdf(unittest.TestCase):
    def test_rejects_non_pdf_bytes(self) -> None:
        with self.assertRaises(ValueError):
            parse_ddb_pdf(b"not a pdf")

    def test_extract_fields_from_pdf_bytes(self) -> None:
        sample = (
            b"%PDF-1.4\n"
            b"/T(CharacterName)/V(Magnus)"
            b"/T(CLASS  LEVEL)/V(Cleric 8)"
            b"/T(STR)/V(17)"
            b"/T(GP)/V(160)"
        )
        fields = extract_ddb_fields(sample)
        self.assertEqual(fields["CharacterName"], "Magnus")
        self.assertEqual(fields["CLASS  LEVEL"], "Cleric 8")
        self.assertEqual(fields["STR"], "17")
        self.assertEqual(fields["GP"], "160")

    def test_parse_class_and_level_with_subclass(self) -> None:
        char_class, level, subclass = _parse_class_and_level("Cleric 8 (Life Domain)")
        self.assertEqual(char_class, "Cleric")
        self.assertEqual(level, 8)
        self.assertEqual(subclass, "Life Domain")

    def test_parse_class_without_subclass(self) -> None:
        char_class, level, subclass = _parse_class_and_level("Fighter 3")
        self.assertEqual(char_class, "Fighter")
        self.assertEqual(level, 3)
        self.assertEqual(subclass, "")


if __name__ == "__main__":
    unittest.main()
