import unittest

from campaign.lore import (
    CampaignEntry,
    extract_query_terms,
    filter_campaign_entries,
    markdown_channel_link,
)

SAMPLE = [
    CampaignEntry(
        section="lieux",
        title="Phandalin",
        body="Petite ville.",
        jump_url="https://discord.com/channels/1/100",
        channel_id=100,
        search_text="lieux Phandalin Petite ville",
    ),
    CampaignEntry(
        section="pnj",
        title="[Phandalin] Toblen Stonehill",
        body="Aubergiste.",
        jump_url="https://discord.com/channels/1/111",
        channel_id=111,
        search_text="pnj Toblen Stonehill Aubergiste",
    ),
    CampaignEntry(
        section="organisations",
        title="🗡️ Zentharim",
        body="Réseau criminel.",
        jump_url="https://discord.com/channels/1/222",
        channel_id=222,
        search_text="organisations Zentharim",
    ),
    CampaignEntry(
        section="pantheon",
        title="⚖️Tyr",
        body="Dieu de la justice.",
        jump_url="https://discord.com/channels/1/333",
        channel_id=333,
        search_text="pantheon Tyr",
    ),
]


class TestCampaignLore(unittest.TestCase):
    def test_extract_query_terms(self) -> None:
        self.assertEqual(extract_query_terms("info Toblen"), ["toblen"])

    def test_filter_single_npc(self) -> None:
        matched = filter_campaign_entries(SAMPLE, "Toblen")
        self.assertEqual(len(matched), 1)
        self.assertIn("Toblen", matched[0].title)

    def test_markdown_link_keeps_emoji_outside_label(self) -> None:
        self.assertEqual(
            markdown_channel_link(
                label="🗡️ Zentharim",
                url="https://discord.com/channels/1/222",
            ),
            "🗡️ [Zentharim](https://discord.com/channels/1/222)",
        )
        self.assertEqual(
            markdown_channel_link(
                label="⚖️Tyr",
                url="https://discord.com/channels/1/333",
            ),
            "⚖️ [Tyr](https://discord.com/channels/1/333)",
        )

    def test_markdown_link_escapes_brackets_in_label(self) -> None:
        link = markdown_channel_link(
            label="[Phandalin] Toblen Stonehill",
            url="https://discord.com/channels/1/111",
        )
        self.assertEqual(
            link,
            "[(Phandalin) Toblen Stonehill](https://discord.com/channels/1/111)",
        )


if __name__ == "__main__":
    unittest.main()
