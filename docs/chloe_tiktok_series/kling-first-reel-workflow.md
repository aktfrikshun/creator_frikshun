# Kling Workflow: First Chloe TikTok Reel

Version: 0.1  
Status: preflight; no Kling generation submitted  
Credit posture: conserve the 66-credit trial balance

## Recommendation

Build the first reel as two independent Kling clips and assemble them outside Kling:

0. **Identity setup, no reel generation:** Create a reusable multi-image Chloe Character Element in Kling's Element Library and bind an approved voice recording.
1. **Entrance, 3 seconds, silent:** Chloe enters the apartment-studio and acknowledges the camera.
2. **Dialogue and signature smirk, 5 seconds, native audio:** Chloe delivers one very concise joke, pauses, and resolves into her canonical dry half-smile using a matched tail frame.

Do not attempt entrance, camera reframing, dialogue, smirk, and exit in one generation. A single failure would make the whole spend unusable, and multi-shot generation gives the model more opportunities to change Chloe.

An exit clip is optional after the first two clips pass review. The initial generated exit-frame candidate is explicitly rejected because its body turn reads as glamour posing rather than Chloe's economical movement.

## Live Kling interfaces available

The connected official CLI exposes these relevant MCP-backed commands:

- `kling file_upload <path>` — uploads local reference images. The generation command also uploads local `--image` and `--tailImage` files automatically.
- `kling image_to_video` — submits start-frame, optional tail-frame, or multi-reference video generation.
- `kling query_tasks <generation_id>` — polls an asynchronous task and returns status plus `works[].url` and, when available, `works[].url_without_watermark`.
- `kling account` — reads membership and credit state without generating media.
- `kling who_am_i` — retrieves live model and parameter declarations without generating media.

The CLI currently exposes no character-Element creation, Element listing, or Element-ID command, and its live generation declaration does not currently advertise `element_id`, `element_list`, `voice_id`, or `voice_list` inputs. Kling's official Element Library supports reusable multi-image character Elements with bound voices, but creation is presently a web/app workflow. After creating Chloe there, inspect the UI and rerun `kling who_am_i` and `kling tool_list`; do not assume a user-visible provider ID or CLI binding exists until it is actually returned.

If the Element Library exposes Chloe only through an `@Chloe` selector in the web creator, the first Element-bound validation may need to be run manually in Kling's web interface. The CLI automation can continue using explicit approved image references until its server declaration exposes Element inputs.

## Identity setup before reel generation

Create one Character Element named `Chloe Katastrophe — Model v1` using two to four approved references:

1. `001_front_headshot_v1.png` — primary facial identity.
2. `002_three_quarter_left_v1.png` — multi-angle facial structure.
3. `005_full_body_front_v3.png` — body proportions and posture.
4. `010_v001_010_dry_half_smile.png` — signature performance, if Kling accepts the expression without overweighting it.

Bind a clean 5–30 second single-speaker voice recording in English. Use moderate pace, neutral emotion, consistent room tone, no music, no reverb, no processing, and no other speaker. The source should include neutral narration plus one restrained dry line; it should not be an exaggerated performance.

Kling's official guidance says the bound voice follows the Character Element and should not be redundantly redescribed in every prompt. Record the Element name and every identifier or exportable reference the UI reveals, but do not invent `element_id` or `voice_id` fields.

## Models selected

### Entrance: `kling-video-v3_0_omni`

Use Omni because it accepts up to seven input images. Supply:

1. the 9:16 entrance scene/start frame;
2. approved Identity Core front portrait;
3. approved full-body front turnaround;
4. optional three-quarter portrait if identity needs more reinforcement.

Reference the images in the prompt as `图片1`, `图片2`, and so on, as required by the live Kling declaration. Set `duration=3`, `aspect_ratio=9:16`, `prefer_multi_shots=false`, and `enable_audio=false`.

### Dialogue: `kling-video-v3_0`

Use standard 3.0 image-to-video because it accepts a first frame plus an optional tail frame and supports native audio. Supply the matched dialogue neutral/listening frame as `--image` and the matched dry-half-smile frame as `--tailImage`. Set `duration=5`, `prefer_multi_shots=false`, and `enable_audio=true`.

The live account declaration currently advertises 720p for these paths. Treat 720p as the trial-validation resolution; do not spend trial credits chasing final delivery resolution before identity, performance, and voice are proven.

Kling's official Omni guide lists 720p image-reference pricing at 6 credits per second with native audio off and 9 credits per second with native audio on. A 3-second silent entrance plus a 5-second dialogue clip would therefore cost approximately 63 credits if those published rates apply to this account. That leaves almost no retry budget. Confirm the price shown by Kling immediately before each submission; if Element creation itself consumes trial credits or the displayed rate differs, stop and revise the shot plan.

## Approved trial references

- `reference_images/entrance-start-v1.png` — scene, wardrobe, full-body identity, and entrance composition.
- `reference_images/dialogue-start-v1.png` — matched dialogue start with listening performance.
- `reference_images/dialogue-smirk-tail-v1.png` — matched dialogue tail with canonical dry-half-smile performance.

Identity reinforcements come directly from Chloe Model v1:

- `001_front_headshot_v1.png`
- `002_three_quarter_left_v1.png`
- `005_full_body_front_v3.png`
- `009_v001_009_neutral_observation.png`
- `010_v001_010_dry_half_smile.png`
- `016_v001_016_listening.png`

## Clip A: entrance

### Inputs

- Image 1: `reference_images/entrance-start-v1.png`
- Image 2: Chloe Model v1 front headshot
- Image 3: Chloe Model v1 full-body front turnaround
- No tail frame for the first test. A rejected entrance-tail candidate failed to show enough spatial travel and would encourage an almost-static interpolation.
- Native audio off.

### Prompt

```text
图片1 is the exact first frame and apartment composition. 图片2 is the locked
facial identity. 图片3 is the locked body proportion and posture reference.

One continuous fixed-camera vertical shot. Preserve the exact woman, face,
gray-green eyes, freckles, natural skin, dark wavy hair, body proportions,
charcoal top, black trousers, boots, silver wolf pendant, doorway, piano,
lighting, lens, and color grade from the references.

Chloe takes two unhurried natural steps into the room, releases the doorframe,
stops on the rug, notices the camera, and holds a quiet observant look for one
beat. Her movement is deliberate and economical, never a runway walk.

Realistic walking mechanics, hands, feet, hair and fabric motion. Fixed camera.
No dialogue. No music. No subtitles, generated text, logos, extra people,
glamour posing, hip emphasis, broad smile, glowing eyes, glitch effects,
camera cut, zoom, pan, or reframing.
```

### Preflight command — do not run until approved

```sh
kling image_to_video \
  --model kling-video-v3_0_omni \
  --image docs/chloe_tiktok_series/reference_images/entrance-start-v1.png \
  --image /Users/allentaylor/src/frikshun_image_studio/studio/reference-packs/chloe_model_v1/packs/character_turnaround_v1/001/001_front_headshot_v1.png \
  --image /Users/allentaylor/src/frikshun_image_studio/studio/reference-packs/chloe_model_v1/packs/character_turnaround_v1/005/005_full_body_front_v3.png \
  --duration 3 \
  --aspect_ratio 9:16 \
  --prefer_multi_shots false \
  --enable_audio false \
  --poll 600 \
  '<prompt above>'
```

## Clip B: dialogue and smirk

### Inputs

- Start: `reference_images/dialogue-start-v1.png`
- Tail: `reference_images/dialogue-smirk-tail-v1.png`
- Native audio on.
- Exact spoken line kept short enough for a deliberate pause.

### First-line candidate

> I forget anniversaries. He forgets I keep receipts.

This is eight words, fits a five-second performance with a final pause, and establishes the relationship without a lore lecture. The tail frame communicates the final punctuation more reliably than asking the prompt to invent Chloe's signature expression.

### Prompt

```text
The input image is the exact first frame. The tail image is the exact final
frame. Preserve Chloe's facial identity, gray-green eyes, freckles, natural
skin texture, dark wavy hair, body proportions, charcoal top, black trousers,
silver wolf pendant, hands, apartment, piano, practical lamps, fixed lens,
exposure, and color grade throughout.

One continuous fixed-camera vertical medium shot. Chloe looks directly into
the lens and says exactly, in a warm lower-mid adult American voice with
precise diction and restrained dry timing:

"I forget anniversaries. He forgets I keep receipts."

She pauses for one full beat after “mean.” Only then, her expression resolves
naturally into the small asymmetrical dry half-smile shown in the tail frame.
The humor appears mainly in one mouth corner and her eyes. No teeth.

Natural lip synchronization, breathing, blinking, tiny mouth tension, and
minimal hand movement. No background speech or music. No subtitles, generated
text, logos, extra people, broad smile, laughter, flirt pose, eyebrow mugging,
beauty-filter skin, glowing eyes, glitch effect, camera cut, zoom, pan, or
reframing.
```

### Preflight command — do not run until Clip A passes

```sh
kling image_to_video \
  --model kling-video-v3_0 \
  --image docs/chloe_tiktok_series/reference_images/dialogue-start-v1.png \
  --tailImage docs/chloe_tiktok_series/reference_images/dialogue-smirk-tail-v1.png \
  --duration 5 \
  --prefer_multi_shots false \
  --enable_audio true \
  --poll 600 \
  '<prompt above>'
```

## Approval gates

### Before any Kling spend

- Allen approves the three reference images.
- The Chloe Character Element and bound voice are created and reviewed in Kling's Element Library.
- Any Element/voice identifiers or UI reference names are recorded exactly as Kling exposes them.
- The dialogue line and voice direction are locked.
- CLI account still reports the expected credit balance.
- No baked captions or overlay text exist in input frames.

### After Clip A

Stop and review before submitting Clip B. Reject if face, body, hair, wardrobe, gait, hands, feet, apartment geometry, or Chloe's restrained presence drift. Do not rationalize an identity miss because the motion is attractive.

### After Clip B

Reject for wrong voice identity, accent drift, poor lip sync, altered face, wardrobe/background mutation, premature smile, broad smile, malformed tail transition, or missing comedic pause.

Only after both clips pass should FFmpeg concatenate them, normalize loudness, and add captions and episode branding. Publication remains manual.

## Credit discipline

- One generation at a time.
- Never request multiple outputs during trial validation.
- Do not use smart multi-shot splitting.
- Do not regenerate to fix captions; captions belong in post.
- Do not generate an exit until the entrance and dialogue performance are approved.
- Record every generation ID, prompt, model, inputs, and rejection reason so failed spend still teaches the pipeline.
