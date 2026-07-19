# FrikShun Creator OS

Local-first content transformation and publishing engine for FrikShun.

This app is the private cockpit: upload or select artifacts, transform them into platform-specific drafts, manage campaign workflows, and eventually publish or assist publishing across platforms.

The public fan-facing archive lives separately in `../chlokat_frikshun`.

## Local Database

Both apps connect to the shared Postgres container defined in:

`../frikshun_dev_stack/docker-compose.yml`

Start it with:

```sh
cd ../frikshun_dev_stack
docker compose up -d
```

Default connection:

```sh
postgresql+psycopg://frikshun:frikshun_dev@localhost:54329/frikshun_content_development
```

## Run Locally

```sh
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
flask run --port 5050
```

## Current Workflow

The local interface can now:

- Upload artifact media to local disk and create artifact metadata.
- Analyze uploaded images when OpenAI vision is configured.
- Generate drafts for Facebook, Instagram, Threads, YouTube, TikTok, X, FanVue, and the ChloKat archive.
- Post-process generated captions for grammar, paragraph breaks, first-person Chloe perspective, voice canon, and platform character limits.
- Approve drafts.
- Archive individual drafts or archive all unpublished drafts.
- Publish a Facebook draft through `FacebookAdapter`.
- Record publication attempts.
- Poll live post metrics for connected platforms.
- Review views, reach, likes, comments, shares, clicks, and incoming comments/messages.

Facebook publishing defaults to dry-run mode so the full workflow can be tested without sending anything to Meta.

## Canon Import

The creator tool can preload Chloe canon from the local marketing archive:

```sh
flask --app app import-canon
```

The UI also has an **Import Canon** button on the home page.

The importer reads markdown files from:

```text
/Users/allentaylor/src/frikshun_marketing/archives/chloe-katastrophe
```

It imports canon, character, music, story, brand, and release files into `creator_canon_entries`. It upserts by `source_path`, so it can be re-run whenever the marketing archive changes. Unresolved mystery files are imported with `canonical_status=unresolved_mystery` and are not used for generation by default.

## Social History and Sample Artifacts

Import prior social post copy as published tone/history:

```sh
flask --app app import-social-posts
```

Import a small set of released sample artifacts from the social folder:

```sh
flask --app app import-sample-artifacts
```

The home page also has buttons for both. These can be re-run safely; existing records are updated instead of duplicated.

## Image Analysis Setup

Image vision is optional. Without a key, the app falls back to filename, MIME type, dimensions, and local metadata. With a key, uploaded images are described before metadata and draft text are generated.

```sh
MEDIA_ANALYZER_PROVIDER=auto
OPENAI_API_KEY=your_openai_api_key
OPENAI_VISION_MODEL=gpt-4.1-mini
```

Use `OPENAI_API_KEY` only; the app intentionally does not look for alternate spellings.

## Facebook Publishing Setup

Automated publishing is supported for a Facebook Page, not a personal profile.

Set these environment variables when you are ready to test real Graph API publishing:

```sh
FACEBOOK_TARGET_TYPE=page
FACEBOOK_GRAPH_VERSION=v20.0
FACEBOOK_DRY_RUN=false
FACEBOOK_PAGE_ID=your_page_id
FACEBOOK_PAGE_ACCESS_TOKEN=your_page_access_token
```

The Page access token should come from a Meta app connected to a Facebook Page you administer. The app/token needs Page publishing permissions such as `pages_manage_posts`; Meta may require additional permissions or app review depending on the account/app state.

For personal profile posting, use the generated Facebook draft as manual copy/paste text. The adapter intentionally refuses automated `profile` targets.

Generate one daily recovered fragment package and publish it across Facebook, Instagram, Threads, X, and FanVue in a single command:

```sh
flask --app app run-daily-fragment-autopilot
```

This command generates the canonical public caption, X-native caption, FanVue caption, and one shared square image automatically. The same image is used across every account, and all five platforms publish through their APIs.

The Creator OS home page is a searchable post library. Search titles and caption text, filter by editorial family, platform, or status, and open any platform badge to review its draft. Use the family selector beside **Create today’s post** to request a recovered-fragment, philosophy, lifestyle, music, travel, or creator-craft post; leave it on automatic to continue the rotation. Each daily post provides an image download and a **Download posting kit** ZIP containing the shared image plus platform-ready Facebook, Instagram, Threads, X, and FanVue captions.

The same override is available from the CLI, for example:

```sh
flask --app app run-daily-fragment-autopilot --family travel
```

Daily-post cards also provide a **Publish** action. It reuses the saved logical run and publishes only to streams that do not already have a successful external publication record. Already-published streams are skipped independently.

You can run it multiple times on the same day. Each invocation gets a unique run id by default, so it does not block later scheduled runs or later manual runs on the same local date.

If you want to retry the same logical run and skip already-published platforms, pass an explicit run id:

```sh
flask --app app run-daily-fragment-autopilot --run-id friday-evening-retry
```

Use this command for the normal scheduled autopilot path. Keep `publish-daily-fragment` for cases where you already have specific text or images that need custom attention.

Publish one recovered fragment across all connected platforms:

```sh
flask --app app publish-daily-fragment \
  --title "Recovered Fragment 014" \
  --image /absolute/path/to/artwork.png \
  --body "Post text"
```

The command records all platform drafts, prepares the shared image for Meta through S3, and publishes to Facebook, Instagram, Threads, X, and FanVue. It refuses dry-run mode by default.

Use `--local-date` only when you want the generated copy and filenames to reflect a different local date. Use `--run-id` only when you want to retry the same logical run and preserve skip/retry behavior across platforms:

```sh
flask --app app publish-daily-fragment \
  --local-date 2026-07-17 \
  --run-id friday-evening-retry \
  --title "Recovered Fragment 014" \
  --image /absolute/path/to/artwork.png \
  --body "Canonical post text" \
  --x-body "Compact X post?" \
  --fanvue-body "Closer FanVue post?"
```

Use `flask --app app check-daily-fragment-readiness` first to verify that OpenAI, local storage, S3, Facebook, Instagram, Threads, X, and FanVue are ready for a live on-demand run.

Generate and export a TikTok-style vertical review reel without publishing it:

```sh
flask --app app generate-tiktok-reel \
  --concept "dating a virtual girl" \
  --shot-count 5
```

This command imports canon, generates a short-form concept pack, creates Chloe-consistent still frames, assembles a vertical MP4 locally, writes a JSON metadata sidecar plus a review draft text file, and stores a private `tiktok` draft in the creator database for manual review.

The exporter is intentionally review-first and does not publish to TikTok. The default provider is `animatic`, which exports reviewable videos from generated stills. The connected official Kling CLI can instead generate each shot as a motion clip before local FFmpeg assembly:

```sh
TIKTOK_REEL_VIDEO_PROVIDER=kling
KLING_CLI_BIN=kling
KLING_VIDEO_MODEL=kling-video-v3_0
KLING_POLL_SECONDS=600
KLING_ENABLE_AUDIO=true
FFMPEG_BIN=ffmpeg
```

Run `kling login` once before using the Kling provider. Generation is credit-consuming and begins only when `generate-tiktok-reel` is explicitly run with the provider set to `kling`. The default `kling-video-v3_0` path supports native audio and start-frame animation; `kling-video-v3_0_turbo` is a faster single-frame alternative but should be evaluated for dialogue needs before becoming the series default.

Manual intervention points for the current reel flow:

- Review the exported reel before posting.
- Review every Kling clip for Chloe identity, voice, continuity, and lip-sync drift.
- Add or replace music manually in TikTok or your editor of choice.

## Instagram Publishing Setup

The Instagram adapter publishes single-image feed posts through Meta's two-step media-container workflow. The Instagram account must be a professional account connected to the Meta app, and each artifact must resolve to a public HTTPS JPEG URL that Meta can fetch.

```sh
INSTAGRAM_GRAPH_VERSION=v20.0
INSTAGRAM_DRY_RUN=false
INSTAGRAM_USER_ID=your_instagram_professional_account_id
INSTAGRAM_ACCESS_TOKEN=your_instagram_access_token
INSTAGRAM_MEDIA_BASE_URL=https://cdn.example.com/chloe-posts
```

For daily publishing, the S3 media service supplies `generated_metadata.public_media_url` automatically. `INSTAGRAM_MEDIA_BASE_URL` remains available for externally hosted artifact libraries. Local filesystem paths and PNG files are rejected by the Instagram adapter before Meta receives a publishing request.

Private S3 media configuration:

```sh
S3_MEDIA_BUCKET=frikshun-social-media
S3_MEDIA_REGION=us-east-1
S3_MEDIA_PREFIX=social
S3_PRESIGN_SECONDS=3600
```

AWS credentials come from the normal AWS SDK credential chain. Keep the bucket private; Instagram only needs the signed URL while Meta processes the media container.

Instagram publishing creates a media container, waits for Meta to finish processing it, publishes the container, records the resulting media ID and permalink, and makes likes, comments, and incoming comment text available to the metrics poller.

The Instagram adapter removes all raw URLs and the Facebook-specific archive, streaming, and FanVue footer before publishing. It inserts `Archive, music, and modeling links are available through my bio.` immediately before the final hashtag block. Facebook retains the complete standing footer and links.

## Threads Publishing Setup

Threads uses Meta's dedicated Threads API rather than the Instagram Graph publish endpoint. The adapter currently supports text posts and single-image posts, with image delivery coming from the same public S3 URL flow already used for daily fragments.

```sh
THREADS_API_VERSION=v1.0
THREADS_API_BASE_URL=https://graph.threads.net
THREADS_AUTH_URL=https://threads.net/oauth/authorize
THREADS_DRY_RUN=false
THREADS_APP_ID=your_threads_app_id
THREADS_APP_SECRET=your_threads_app_secret
THREADS_REDIRECT_URI=https://your-public-host/oauth/threads/callback
THREADS_TOKEN_PATH=instance/threads_oauth.json
THREADS_ACCESS_TOKEN=your_threads_user_access_token
THREADS_LONG_LIVED_ACCESS_TOKEN=your_threads_long_lived_token
THREADS_MEDIA_BASE_URL=https://cdn.example.com/chloe-posts
```

For the daily fragment autopilot, `generated_metadata.public_media_url` is normally enough and `THREADS_MEDIA_BASE_URL` can stay blank. The adapter removes the standing raw-link footer before publishing and replaces it with `Archive, music, and modeling links are available through my bio.` so the post reads natively on Threads.

To authorize the Threads account and store the long-lived token locally:

1. Set `THREADS_APP_ID`, `THREADS_APP_SECRET`, and `THREADS_REDIRECT_URI`.
2. Make sure the exact `THREADS_REDIRECT_URI` is registered in the Meta Threads use case settings.
3. Run the web app behind that public host.
4. Visit `/oauth/threads/start` on that same host, or print a direct authorization URL with:

```sh
flask --app app start-threads-oauth
```

5. Approve the app as the Threads account.
6. Let Meta redirect back to `/oauth/threads/callback`.

The callback stores the long-lived token JSON in `THREADS_TOKEN_PATH`. You can refresh it later with:

```sh
flask --app app refresh-threads-token
```

## Post Metrics Polling

Poll published post metrics from the UI:

```text
/metrics
```

Or from the command line:

```sh
flask --app app poll-post-metrics
```

The installed launchd job runs this poll once daily (and once when loaded). The metrics layer is platform-neutral and currently includes Facebook, Instagram, Threads, and X adapters, plus FanVue. Account and content analytics are coalesced into one snapshot per UTC day, while supported comments are imported into `creator_post_interactions` with `reply_status=pending_review`.

## X Publishing Setup

The X adapter uses X API v2 to upload the artifact image, create the post, and collect impressions, likes, replies, reposts/quotes, bookmarks, and link clicks. Configure the app for Read and write access, then provide its OAuth 1.0a `X_CONSUMER_KEY`, `X_SECRET_KEY`, `X_ACCESS_TOKEN`, and `X_ACCESS_TOKEN_SECRET`. Set `X_USERNAME` and change `X_DRY_RUN=false` only after the identity check succeeds. Never commit these credentials.

X posts are validated against the standard 280-character limit before any media is uploaded. Use the generated X-specific draft rather than sending the longer Facebook or Instagram caption unchanged.

X captions are always link-free. The adapter removes raw URLs and the standing archive, music, and FanVue footer, then adds: `Links are in my bio. Search Chloe Katastrophe on major streaming platforms.` This keeps the post native to X and avoids the substantially higher API rate for posts containing URLs.

## FanVue API Setup

FanVue uses OAuth 2.0 publishing, media, and insights APIs. The private app requests only `read:self`, `read:post`, `write:post`, `read:media`, `write:media`, `read:insights`, and the required `openid offline_access offline` scopes. Authorization uses HTTPS and PKCE; refreshable tokens are stored privately under `instance/`.

The FanVue adapter uploads the shared local post image through FanVue's multipart media API, waits for processing, and creates a free `followers-and-subscribers` post. Daily runs may use `--fanvue-body` for closer platform-native copy. The legacy `--fanvue-image` option remains available for older custom workflows but is no longer required. Likes, comments, and comment text feed the shared metrics and interaction-review UI.

The interaction queue is intentionally review-first. It is the staging area for the planned scheduled process that will fetch new comments/messages and prepare Chloe-voice replies before anything is sent.

## Boundary

This tool may read and write the shared content database, but schema changes should be coordinated with the Rails public archive app. Rails should own the first durable migrations for public artifacts, releases, searchable archive content, and fan-visible data.
