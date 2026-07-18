# Chloe Katastrophe TikTok Character Series

Status: foundational production pack 0.1  
Primary renderer: Kling 3.x  
Format: recurring vertical character comedy, assembled from short clips  
Canon authority: Chloe Model v1

This directory turns the recurring-character concept into a repeatable production system. It separates what must remain stable about Chloe from what changes per episode, and it keeps generated clips review-first until identity, voice, continuity, and comedic timing are dependable.

## Foundational files

- `series-bible.md` — locked character, voice, setting, performance, and continuity rules.
- `asset-manifest.json` — the reference assets and provider IDs the pipeline must acquire and version.
- `kling-prompt-template.md` — a concise clip prompt contract for Kling.
- `episode-template.json` — machine-readable episode and clip specification.
- `pilot-001-memory-issues.json` — a first production-ready script plan derived from the original concept.
- `review-checklist.md` — approval gates before assembly and publication.
- `kling-first-reel-workflow.md` — exact models, inputs, prompts, commands, and credit gates for the first paid trial.
- `reference_images/` — scene-matched 9:16 entrance, dialogue, and smirk anchors derived from Chloe Model v1.

## Production principle

The application remembers Chloe; Kling performs the current shot.

Do not paste the entire series bible into every generation request. Each Kling request should receive only the approved character Element or references, the selected environment and frame anchors, the performance direction, and the exact dialogue for that clip.

## Initial workflow

1. Produce and approve the missing assets in `asset-manifest.json`.
2. Create a reusable Chloe Element in Kling and record its provider ID in the manifest.
3. Bind or approve the canonical voice, then record its provider ID.
4. Generate each pilot clip independently at 3–8 seconds.
5. Reject identity drift before spending time on assembly.
6. Assemble approved clean clips outside Kling with captions, episode branding, loudness normalization, and music.
7. Require Allen's approval before publication.

The existing creator app already exports TikTok animatics and stores review drafts. This pack defines the stable layer needed before replacing those animatics with Kling motion generation.
