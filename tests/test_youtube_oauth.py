import unittest

from frikshun_creator.services.youtube_oauth import YouTubeOAuth


class YouTubeOAuthTest(unittest.TestCase):
    def test_begin_requests_only_read_only_youtube_access(self):
        oauth = YouTubeOAuth(
            "client",
            "secret",
            "https://creator.example/oauth/youtube/callback",
        )

        authorization_url, _state = oauth.begin()

        self.assertIn("youtube.readonly", authorization_url)
        self.assertNotIn("yt-analytics.readonly", authorization_url)

    def test_begin_requests_offline_read_only_access(self):
        oauth = YouTubeOAuth("client", "secret", "https://example.test/callback")
        url, state = oauth.begin()
        self.assertIn("youtube.readonly", url)
        self.assertNotIn("yt-analytics.readonly", url)
        self.assertIn("access_type=offline", url)
        self.assertIn("prompt=consent", url)
        self.assertTrue(state)


if __name__ == "__main__":
    unittest.main()
