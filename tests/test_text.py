import unittest

from frikshun_creator.services.text import split_tags


class SplitTagsTest(unittest.TestCase):
    def test_accepts_comma_separated_words_or_phrases(self):
        self.assertEqual(
            ["ChloKat", "RecoveredMemory", "FineArtPhotography"],
            split_tags("ChloKat, RecoveredMemory, Fine Art Photography"),
        )

    def test_accepts_space_separated_hashtags(self):
        self.assertEqual(
            ["ChloKat", "RecoveredMemory", "FineArtPhotography"],
            split_tags("#ChloKat #RecoveredMemory #FineArtPhotography"),
        )

    def test_accepts_pasted_together_hashtags(self):
        self.assertEqual(
            ["ChloKat", "RecoveredMemory", "FineArtPhotography"],
            split_tags("#ChloKat#RecoveredMemory#FineArtPhotography"),
        )

    def test_removes_duplicate_hashtags_case_insensitively(self):
        self.assertEqual(["ChloKat"], split_tags("#ChloKat #chlokat"))


if __name__ == "__main__":
    unittest.main()
