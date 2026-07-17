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
- Generate drafts for Facebook, Instagram, YouTube, TikTok, X, FanVue, and the ChloKat archive.
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

Generate one daily recovered fragment package and publish it across Facebook, Instagram, X, and FanVue in a single command:

```sh
flask --app app run-daily-fragment-autopilot
```

This command generates the canonical public caption, X-native caption, FanVue caption, public image, and FanVue companion image automatically, then publishes them through the same run-based workflow used by the manual publisher.

You can run it multiple times on the same day. Each invocation gets a unique run id by default, so it does not block later scheduled runs or later manual runs on the same local date.

If you want to retry the same logical run and skip already-published platforms, pass an explicit run id:

```sh
flask --app app run-daily-fragment-autopilot --run-id friday-evening-retry
```

Use this command for the normal scheduled autopilot path. Keep `publish-daily-fragment` for cases where you already have specific text or images that need custom attention.

Publish one recovered fragment and image to both Facebook and Instagram for the current local day:

```sh
flask --app app publish-daily-fragment \
  --title "Recovered Fragment 014" \
  --image /absolute/path/to/artwork.png \
  --body "Post text"
```

The command converts the artwork to JPEG, uploads it privately to S3, gives Instagram a short-lived signed URL, and records independent Facebook and Instagram publications. It refuses dry-run mode by default.

Use `--local-date` only when you want the generated copy and filenames to reflect a different local date. Use `--run-id` only when you want to retry the same logical run and preserve skip/retry behavior across platforms:

```sh
flask --app app publish-daily-fragment \
  --local-date 2026-07-17 \
  --run-id friday-evening-retry \
  --title "Recovered Fragment 014" \
  --image /absolute/path/to/artwork.png \
  --fanvue-image /absolute/path/to/fanvue-artwork.png \
  --body "Canonical post text" \
  --x-body "Compact X post?" \
  --fanvue-body "Closer FanVue post?"
```

Use `flask --app app check-daily-fragment-readiness` first to verify that OpenAI, S3, Facebook, Instagram, X, and FanVue are all ready for a live on-demand run.

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

## Post Metrics Polling

Poll published post metrics from the UI:

```text
/metrics
```

Or from the command line:

```sh
flask --app app poll-post-metrics
```

The metrics layer is platform-neutral and currently includes Facebook, Instagram, and X adapters. Each poll stores a new snapshot in `creator_post_metric_snapshots` and imports supported comments into `creator_post_interactions` with `reply_status=pending_review`.

## X Publishing Setup

The X adapter uses X API v2 to upload the artifact image, create the post, and collect impressions, likes, replies, reposts/quotes, bookmarks, and link clicks. Configure the app for Read and write access, then provide its OAuth 1.0a `X_CONSUMER_KEY`, `X_SECRET_KEY`, `X_ACCESS_TOKEN`, and `X_ACCESS_TOKEN_SECRET`. Set `X_USERNAME` and change `X_DRY_RUN=false` only after the identity check succeeds. Never commit these credentials.

X posts are validated against the standard 280-character limit before any media is uploaded. Use the generated X-specific draft rather than sending the longer Facebook or Instagram caption unchanged.

X captions are always link-free. The adapter removes raw URLs and the standing archive, music, and FanVue footer, then adds: `Links are in my bio. Search Chloe Katastrophe on major streaming platforms.` This keeps the post native to X and avoids the substantially higher API rate for posts containing URLs.

## FanVue API Setup

FanVue uses OAuth 2.0 publishing, media, and insights APIs. The private app requests only `read:self`, `read:post`, `write:post`, `read:media`, `write:media`, `read:insights`, and the required `openid offline_access offline` scopes. Authorization uses HTTPS and PKCE; refreshable tokens are stored privately under `instance/`.

The FanVue adapter uploads a separate local image through FanVue's multipart media API, waits for processing, and creates a free `followers-and-subscribers` post. Daily runs require `--fanvue-image` and may use `--fanvue-body`. The FanVue artwork should be a distinct, more beautiful, artsy, and intimate interpretation of the same daily subject while remaining within the approved Chloe visual canon and image-generation safety rules. Likes, comments, and comment text feed the shared metrics and interaction-review UI.

The interaction queue is intentionally review-first. It is the staging area for the planned scheduled process that will fetch new comments/messages and prepare Chloe-voice replies before anything is sent.

## Boundary

This tool may read and write the shared content database, but schema changes should be coordinated with the Rails public archive app. Rails should own the first durable migrations for public artifacts, releases, searchable archive content, and fan-visible data.
