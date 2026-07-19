from datetime import datetime, timezone

import requests

from .base import AccountMetricsData, ContentDiscoveryPage, PostMetrics, PublisherAdapter, RemoteContentData


VIDEO_FIELDS = "id,title,video_description,duration,cover_image_url,embed_link,create_time,view_count,like_count,comment_count,share_count"


class TikTokAnalyticsAdapter(PublisherAdapter):
    platform = "tiktok"

    def __init__(self, oauth, base_url="https://open.tiktokapis.com"):
        self.oauth = oauth
        self.base_url = base_url.rstrip("/")

    def headers(self):
        return {"Authorization": f"Bearer {self.oauth.access_token()}"}

    def fetch_account_metrics(self):
        payload = self.get("/v2/user/info/", params={"fields": "open_id,union_id,display_name,username,follower_count,following_count,likes_count,video_count"})
        user = payload.get("data", {}).get("user", {})
        return AccountMetricsData(
            followers=int(user.get("follower_count") or 0),
            following=int(user.get("following_count") or 0),
            content_count=int(user.get("video_count") or 0),
            engagements=int(user.get("likes_count") or 0),
            metrics=user,
        )

    def discover_account_content(self, cursor="", limit=100):
        body = {"max_count": min(int(limit), 20)}
        if cursor:
            body["cursor"] = int(cursor)
        payload = self.post("/v2/video/list/", params={"fields": VIDEO_FIELDS}, json=body)
        data = payload.get("data", {})
        items = [self.remote_content(video) for video in data.get("videos", [])]
        next_cursor = str(data.get("cursor") or "") if data.get("has_more") else ""
        return ContentDiscoveryPage(items=items, next_cursor=next_cursor)

    def fetch_remote_content_metrics(self, remote_content):
        payload = self.post(
            "/v2/video/query/",
            params={"fields": VIDEO_FIELDS},
            json={"filters": {"video_ids": [remote_content.external_content_id]}},
        )
        videos = payload.get("data", {}).get("videos", [])
        if not videos:
            raise ValueError(f"TikTok video {remote_content.external_content_id} not found")
        video = videos[0]
        return PostMetrics(
            platform="tiktok",
            external_post_id=remote_content.external_content_id,
            external_url=video.get("embed_link", remote_content.permalink),
            views=int(video.get("view_count") or 0),
            likes=int(video.get("like_count") or 0),
            comments=int(video.get("comment_count") or 0),
            shares=int(video.get("share_count") or 0),
            raw_metrics=video,
        )

    def remote_content(self, video):
        created = video.get("create_time")
        return RemoteContentData(
            external_content_id=str(video["id"]),
            content_type="video",
            title=video.get("title") or video.get("video_description") or "TikTok video",
            body=video.get("video_description") or "",
            permalink=video.get("embed_link") or "",
            thumbnail_url=video.get("cover_image_url") or "",
            published_at=datetime.fromtimestamp(int(created), timezone.utc) if created else None,
            metadata={"duration": video.get("duration")},
        )

    def get(self, path, **kwargs):
        return self.response_payload(requests.get(f"{self.base_url}{path}", headers=self.headers(), timeout=30, **kwargs))

    def post(self, path, **kwargs):
        return self.response_payload(requests.post(f"{self.base_url}{path}", headers=self.headers(), timeout=30, **kwargs))

    @staticmethod
    def response_payload(response):
        payload = response.json()
        error = payload.get("error", {})
        if not response.ok or (error and error.get("code") not in (None, "ok")):
            raise ValueError(str(error.get("message") or response.reason))
        return payload
