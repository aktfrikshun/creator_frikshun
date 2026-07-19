# TikTok App Review Packet

This directory contains the public-facing assets and reviewer copy for the
FrikShun Creator OS TikTok integration.

## Submission assets

- `chloekat-app-icon-1024.png` — final 1024 × 1024 PNG app icon (under 5 MB)
- `submission-copy.md` — field-by-field Developer Portal copy
- `demo-video-script.md` — end-to-end sandbox recording script
- `review-readiness.md` — pre-submission and recording checklist

The generated `chloekat-app-icon-source.png` is retained as the source render.

## Public URLs

- Website: https://creator.frikshun.com
- Terms: https://creator.frikshun.com/terms
- Privacy: https://creator.frikshun.com/privacy
- Acceptable Use: https://creator.frikshun.com/acceptable-use
- TikTok OAuth callback: https://creator.frikshun.com/oauth/tiktok/callback

## Review scope

The review should add only the Login Kit product. Display API is exposed through
the separately requested user and video scopes rather than an addable product
tile in the current Developer Portal. Creator OS uses TikTok authorization to identify the connected creator account, read
account-level profile/statistics data, discover that account's videos, and show
video-level performance in the private metrics dashboard. TikTok publishing is
manual and is not part of this submission. Do not add Share Kit, Content Posting
API, Webhooks, or Data Portability API.
