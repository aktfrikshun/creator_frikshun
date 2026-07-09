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

## Boundary

This tool may read and write the shared content database, but schema changes should be coordinated with the Rails public archive app. Rails should own the first durable migrations for public artifacts, releases, searchable archive content, and fan-visible data.
