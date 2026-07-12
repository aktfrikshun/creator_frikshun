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

## Boundary

This tool may read and write the shared content database, but schema changes should be coordinated with the Rails public archive app. Rails should own the first durable migrations for public artifacts, releases, searchable archive content, and fan-visible data.
