from datetime import datetime

import requests

from .base import AccountMetricsData, ContentDiscoveryPage, PostMetrics, PublisherAdapter, RemoteContentData


class YouTubeAnalyticsAdapter(PublisherAdapter):
    platform = "youtube"

    def __init__(self, oauth):
        self.oauth = oauth

    def get(self, url, params):
        response = requests.get(url, params=params, headers={"Authorization": f"Bearer {self.oauth.access_token()}"}, timeout=30)
        payload = response.json()
        if not response.ok or payload.get("error"):
            raise ValueError(str(payload.get("error", {}).get("message") or response.reason))
        return payload

    def channel(self):
        payload = self.get("https://www.googleapis.com/youtube/v3/channels", {"part": "snippet,statistics,contentDetails", "mine": "true"})
        if not payload.get("items"):
            raise ValueError("No YouTube channel was returned for the authorized account.")
        return payload["items"][0]

    def fetch_account_metrics(self):
        channel = self.channel()
        stats = channel.get("statistics", {})
        return AccountMetricsData(
            followers=int(stats.get("subscriberCount") or 0),
            content_count=int(stats.get("videoCount") or 0),
            views=int(stats.get("viewCount") or 0),
            metrics={**stats, "channel_id": channel.get("id"), "title": channel.get("snippet", {}).get("title")},
        )

    def discover_account_content(self, cursor="", limit=100):
        uploads = self.channel().get("contentDetails", {}).get("relatedPlaylists", {}).get("uploads")
        params = {"part": "snippet,contentDetails", "playlistId": uploads, "maxResults": min(int(limit), 50)}
        if cursor:
            params["pageToken"] = cursor
        payload = self.get("https://www.googleapis.com/youtube/v3/playlistItems", params)
        return ContentDiscoveryPage(
            items=[self.remote_content(item) for item in payload.get("items", [])],
            next_cursor=payload.get("nextPageToken", ""),
        )

    def fetch_remote_content_metrics(self, remote_content):
        payload = self.get("https://www.googleapis.com/youtube/v3/videos", {"part": "statistics", "id": remote_content.external_content_id})
        if not payload.get("items"):
            raise ValueError(f"YouTube video {remote_content.external_content_id} not found")
        stats = payload["items"][0].get("statistics", {})
        return PostMetrics(
            platform="youtube", external_post_id=remote_content.external_content_id,
            external_url=remote_content.permalink, views=int(stats.get("viewCount") or 0),
            likes=int(stats.get("likeCount") or 0), comments=int(stats.get("commentCount") or 0),
            raw_metrics=stats,
        )

    @staticmethod
    def remote_content(item):
        snippet = item.get("snippet", {})
        video_id = item.get("contentDetails", {}).get("videoId") or snippet.get("resourceId", {}).get("videoId")
        published = snippet.get("publishedAt")
        thumbnails = snippet.get("thumbnails", {})
        thumbnail = (thumbnails.get("high") or thumbnails.get("medium") or thumbnails.get("default") or {}).get("url", "")
        return RemoteContentData(
            external_content_id=video_id, content_type="video", title=snippet.get("title", ""),
            body=snippet.get("description", ""), permalink=f"https://www.youtube.com/watch?v={video_id}",
            thumbnail_url=thumbnail, published_at=datetime.fromisoformat(published.replace("Z", "+00:00")) if published else None,
            metadata={"channel_title": snippet.get("videoOwnerChannelTitle") or snippet.get("channelTitle")},
        )
