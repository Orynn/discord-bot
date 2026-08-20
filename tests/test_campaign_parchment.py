import unittest

from PIL import Image

from campaign.parchment import MAX_TEXT_LENGTH, ParchmentError, parse_document_text, render_parchment


class TestParseDocumentText(unittest.TestCase):
    def test_rejects_empty_text(self) -> None:
        with self.assertRaises(ParchmentError):
            parse_document_text("   ")

    def test_splits_title_and_body(self) -> None:
        title, body = parse_document_text("Décret royal -- Par ordre du roi, fermez les portes.")
        self.assertEqual(title, "Décret royal")
        self.assertEqual(body, "Par ordre du roi, fermez les portes.")

    def test_treats_plain_text_as_body(self) -> None:
        title, body = parse_document_text("Par ordre du roi.")
        self.assertIsNone(title)
        self.assertEqual(body, "Par ordre du roi.")

    def test_rejects_overlong_text(self) -> None:
        with self.assertRaises(ParchmentError):
            parse_document_text("a" * (MAX_TEXT_LENGTH + 1))


class TestRenderParchment(unittest.TestCase):
    def test_renders_png_with_title_and_body(self) -> None:
        png = render_parchment(title="Décret", body="Par ordre du roi, Padhiver est en alerte.")
        self.assertTrue(png.getvalue().startswith(b"\x89PNG"))
        image = Image.open(png)
        self.assertEqual(image.format, "PNG")
        self.assertGreaterEqual(image.width, 800)
        self.assertGreaterEqual(image.height, 600)

    def test_wraps_long_french_text(self) -> None:
        body = (
            "Que tous les habitants de Padhiver sachent que les portes de la ville "
            "seront closes dès la tombée de la nuit, jusqu'à ce que la menace "
            "qui rôde dans les bois soit écartée."
        ) * 4
        png = render_parchment(title=None, body=body)
        image = Image.open(png)
        self.assertLessEqual(image.height, 2400)

    def test_rejects_empty_render(self) -> None:
        with self.assertRaises(ParchmentError):
            render_parchment(title=None, body="  ")


if __name__ == "__main__":
    unittest.main()
