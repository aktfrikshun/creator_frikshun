# TikTok Review Demo Video Script

Target length: 90–150 seconds. Record at 1080p or higher with the browser URL
visible. Use the TikTok sandbox environment until the app is approved. Do not
show client secrets, access tokens, `.env`, terminal output, or browser password
manager content.

## Recording sequence

### 1. Establish the real web app (0:00–0:15)

- Begin at `https://creator.frikshun.com` with the full domain visible.
- Show the Google authentication gate and complete sign-in.
- Briefly show the Creator OS home page.
- On-screen caption: **Private creator analytics dashboard**.

### 2. Start TikTok authorization (0:15–0:35)

- Locate the TikTok account row showing analytics as disconnected or ready to connect.
- Click **Connect TikTok**.
- Keep the address bar visible as the browser moves to TikTok.
- On-screen caption: **Login Kit — account owner initiates authorization**.

### 3. Demonstrate every requested scope (0:35–0:60)

- Show the TikTok sandbox consent screen.
- Make the requested permissions legible.
- Authorize with the sandbox/test TikTok account.
- On-screen caption listing:
  - `user.info.basic` — account identity
  - `user.info.profile` — username/profile
  - `user.info.stats` — account totals and growth
  - `video.list` — owned videos and performance

### 4. Show the OAuth return (0:60–0:75)

- Show the redirect returning to
  `https://creator.frikshun.com/oauth/tiktok/callback`.
- Show the success message without exposing tokens.
- Return to Creator OS.

### 5. Show account-wide insights (0:75–1:40)

- Open **Metrics**.
- Show TikTok in the platform/account summary.
- Point out follower/account-stat snapshots and the growth trend.
- Trigger **Poll live metrics** only if the sandbox contains suitable data.
- On-screen caption: **Display API — authorized account-wide statistics**.

### 6. Drill into video performance (1:40–2:05)

- Show the TikTok rows in the sortable post-performance grid.
- Sort by views, then comments or engagement.
- Show that the rows represent videos discovered from the authorized TikTok account, not only posts created in Creator OS.
- On-screen caption: **Display API — owned-video discovery and rankings**.

### 7. Close with control and privacy (2:05–2:20)

- Open the public Privacy Policy in a new tab.
- Briefly show the connected-platform data and deletion sections.
- End on Creator OS with the TikTok account connected.
- On-screen caption: **Private use · revocable access · no TikTok publishing requested**.

## Narration

“FrikShun Creator OS is a private analytics dashboard for one creator. After
Google authentication, the account owner connects TikTok through Login Kit.
The app requests basic identity, profile, account statistics, and video-list
access. The callback stores tokens server-side. Display API data powers
account-wide growth trends and individual-video rankings inside the Metrics
page. This version does not publish to TikTok. Access can be revoked through
TikTok, and deletion requests are described in the public Privacy Policy.”
