# TikTok Developer Portal Copy

## Basic information

**App name**

Chloekat

**Category**

Entertainment

**Description** (under 120 characters)

Private creator dashboard that tracks TikTok account growth and video performance over time.

**Terms of Service URL**

https://creator.frikshun.com/terms

**Privacy Policy URL**

https://creator.frikshun.com/privacy

**Platform**

Web / Desktop

**Website URL**

https://creator.frikshun.com

**Redirect URI**

https://creator.frikshun.com/oauth/tiktok/callback

## Products and scopes

Add only this product:

- Login Kit

Display API is not shown as a separate product tile in the current Developer
Portal. Its `/v2/user/info/`, `/v2/video/list/`, and `/v2/video/query/` access is
configured through the separate **Scopes** section.

Request only:

- `user.info.basic` — identify the connected TikTok account and display its basic profile identity.
- `user.info.profile` — display the authorized account's username and profile information in the private account registry.
- `user.info.stats` — collect account-wide follower, following, likes, and video-count snapshots for growth trends.
- `video.list` — discover videos owned by the authorized account and collect their view, like, comment, and share counts for individual-post rankings.

Do not add Share Kit, Content Posting API, Webhooks, or Data Portability API, and
do not request publishing scopes for this submission.

## App review explanation (under 1,000 characters)

FrikShun Creator OS is a private, single-creator analytics dashboard. The account owner signs into Creator OS with Google, selects “Connect TikTok,” and is redirected to TikTok Login Kit. After consent, the server exchanges the authorization code and securely stores the access and refresh tokens. Display API data is used only inside the authenticated dashboard. `user.info.basic` and `user.info.profile` identify the connected account; `user.info.stats` records account-wide follower, following, likes, and video-count snapshots; and `video.list` discovers the account’s videos and retrieves view, like, comment, and share counts. The Metrics page compares TikTok account growth over time and ranks individual videos by engagement. Users can revoke access in TikTok or request deletion using the published Privacy Policy. This version does not publish content to TikTok and does not request Content Posting API scopes.

## Reviewer instructions

1. Open https://creator.frikshun.com.
2. Sign in using the review Google account supplied in the submission notes.
3. On Creator OS, locate the TikTok analytics connection and select **Connect TikTok**.
4. Authorize the TikTok sandbox/test account and approve the requested scopes.
5. Return to Creator OS and open **Metrics**.
6. Confirm the TikTok account appears in account summaries and its videos appear in individual-post performance.

If a dedicated Google review account is not supplied, the reviewer cannot pass the private Google gate. Add the reviewer email to `GOOGLE_ALLOWED_EMAILS` before submission or provide a temporary review account.
