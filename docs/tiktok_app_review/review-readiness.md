# TikTok Review Readiness

## Developer Portal

- [ ] Upload `chloekat-app-icon-1024.png`.
- [ ] Add the basic information from `submission-copy.md`.
- [ ] Add the public website, Terms, and Privacy URLs.
- [ ] Configure Web / Desktop with the exact HTTPS redirect URI.
- [ ] Add Login Kit only; Display API access is represented by scopes, not a product tile.
- [ ] Add exactly `user.info.basic`, `user.info.profile`, `user.info.stats`, and `video.list`.
- [ ] Do not add Share Kit, Content Posting API, Webhooks, or Data Portability API.
- [ ] Configure a TikTok sandbox and add the intended test account.

## Creator OS

- [ ] Set `TIKTOK_REDIRECT_URI=https://creator.frikshun.com/oauth/tiktok/callback`.
- [ ] Restart `com.frikshun.creator` after changing `.env`.
- [ ] Confirm **Connect TikTok** begins OAuth from the authenticated Creator OS.
- [ ] Confirm callback state validation succeeds.
- [ ] Confirm tokens are stored under `instance/` with mode `0600`.
- [ ] Confirm a refresh-token cycle succeeds.
- [ ] Confirm account statistics populate the metrics dashboard.
- [ ] Confirm owned videos populate the post-performance table.
- [ ] Confirm deleted/unavailable videos are handled without breaking the poll.

## Reviewer access

- [ ] Decide how a TikTok reviewer will pass Google SSO.
- [ ] Prefer a dedicated temporary Google review account rather than adding an unknown personal reviewer address.
- [ ] Add the review account to the Google OAuth test users.
- [ ] Add the same address to `GOOGLE_ALLOWED_EMAILS` for the review window.
- [ ] Remove the temporary reviewer after approval.

## Demo video

- [ ] Use the TikTok sandbox and the same public domain submitted for review.
- [ ] Show the full Login Kit authorization flow.
- [ ] Visibly demonstrate every requested scope.
- [ ] Show both account-wide insights and individual-video performance.
- [ ] Show the Privacy Policy and deletion language.
- [ ] Verify no credentials, tokens, private `.env` values, or unrelated personal data are visible.
- [ ] Export MP4 or MOV under 50 MB.

## Final audit

- [ ] App name, icon, domain, and UI shown in the video match the submission.
- [ ] Review explanation is under 1,000 characters.
- [ ] Public description is under 120 characters.
- [ ] No unneeded products or scopes remain selected.
- [ ] Legal pages load without Google authentication.
- [ ] Creator and Metrics pages require authentication.
