# Lucid Spokesperson Videos v2 — Continuation from Session

## Session State
- **Video 1 (Latina Hook)** — DONE ✅ Generated with Veo 3.1 Quality. Looks excellent, Lucid wordmark properly integrated into fabric.
- **Videos 2–5** — NOT YET STARTED
- **Output dir**: `~/Desktop/Documents/Claude Code/Lucid/spokesperson-videos/v2/`
- **Flow project**: `https://labs.google/fx/tools/flow/project/c24dbd7a-fdcf-4563-a110-b19ca4108818`

## Immediate Next Step: Extend Video 1

**Video 1 edit URL**: `https://labs.google/fx/tools/flow/project/c24dbd7a-fdcf-4563-a110-b19ca4108818/edit/56ab72c2-9424-4e8c-9abe-3e901ba23491`

1. Navigate to edit URL
2. Click **Extend** button
3. Change model to **Veo 3.1 - Quality** (the Extend "What happens next?" box defaults to Fast)
4. Enter extension prompt: `Continue spokesperson speaking naturally to finish their sentence, same camera position, same lighting, seamless continuation.`
5. Generate, wait for completion
6. Download → **1080p Upscaled** → wait for upscale → grab GCS URL → curl download
7. Save as `v2/01-latina-hook-v2.mp4`

---

## Videos 2–5: Full Prompts

### Template (shared across all videos)
```
Cinematic professional spokesperson video, shot on RED Dragon or ARRI Alexa.
[PERSON DESCRIPTION]. Speaking directly to camera with natural warmth and confidence,
naturally pacing the words with brief pauses. Professional studio setup:
[BACKGROUND]. Two-point soft box lighting, slight Rembrandt fill.
Medium close-up, shoulders-up framing, shallow depth of field (f/2.8),
subtle natural bokeh. Subtle natural head movements, natural blinking, hair
slight natural movement. The spokesperson says out loud, clearly:
"[SPOKEN COPY]"
Locked-off shot with a very slow, subtle push-in (5%).
Indistinguishable from a $50,000 professional brand video shoot.
No AI artifacts, no uncanny valley. Hyperrealistic human motion and expression.
```

### Video 2 — South Asian — "The Science"
- **Image**: `04-v1-south-asian-lucid-background.png`
- **Person**: `An extremely handsome South Asian man in his late 20s, wearing a dark forest green fitted crew neck t-shirt, short neat dark hair, light stubble, strong jawline, confident warm smile`
- **Background**: `soft gray seamless background with the word 'Lucid' in large soft steel-blue letters visible in bokeh behind him`
- **Copy**: `"Your voice changes before your mood does. Pitch, rhythm, energy — 20 acoustic signals revealing exactly what's happening mentally. That's what Lucid listens for. Every day."`
- **Save as**: `v2/02-south-asian-science-v2.mp4`

### Video 3 — Latina — "The Privacy"
- **Image**: `02-v2-latina-lucid-shirt.png`
- **Person**: `An extremely attractive Latina woman in her late 20s, wearing a cream ribbed-knit crewneck sweater; on the left chest, the word 'Lucid' is subtly screen-printed in small matte dark lettering directly onto the ribbed knit fabric — the ribbed texture of the sweater is visible through and beneath the letters, the print is fully integrated into the textile surface as part of the garment's design, not floating on top of the fabric. Dark wavy hair worn loosely down, minimal natural makeup, small gold hoop earrings, warm glowing skin`
- **Background**: `pure white/soft gray seamless background`
- **Copy**: `"Lucid doesn't live in a cloud somewhere. It runs entirely on your Mac. Your voice never leaves your device. Mental wellness data that's actually, finally, yours."`
- **Save as**: `v2/03-latina-privacy-v2.mp4`

### Video 4 — South Asian — "The Access"
- **Image**: `04-v1-south-asian-lucid-background.png`
- **Person**: (same as Video 2)
- **Background**: (same as Video 2)
- **Copy**: `"Clinically validated voice AI used to be locked behind hospital doors. Lucid changed that. It's on your Mac for $14.99 a month. The technology was always there."`
- **Save as**: `v2/04-south-asian-access-v2.mp4`

### Video 5 — Latina — "The CTA"
- **Image**: `02-v2-latina-lucid-shirt.png`
- **Person**: (same as Video 3 — Latina with integrated Lucid shirt print)
- **Background**: `pure white/soft gray seamless background`
- **Copy**: `"25 seconds of your voice. That's all Lucid needs to tell you more about your mental state than an annual questionnaire ever could. Try it free."`
- **Save as**: `v2/05-latina-cta-v2.mp4`

---

## Per-Video Workflow (Videos 2–5)
1. Go to project page: `https://labs.google/fx/tools/flow/project/c24dbd7a-fdcf-4563-a110-b19ca4108818`
2. Click **Start** frame → select the correct image
3. Click **Video settings** → change to **Veo 3.1 - Quality** (100 credits)
4. Type full prompt (Template with filled-in Person/Background/Copy)
5. Click **Create** → wait 2–5 min
6. Open video → click **Extend** → use Quality model → enter extension prompt → generate
7. Download → **1080p Upscaled** → grab GCS signed URL via JS:
   ```javascript
   // In DevTools console on the download page:
   // Look for network requests to storage.googleapis.com and copy the URL
   // Then: curl -L "GCS_URL" -o ~/Desktop/Documents/Claude\ Code/Lucid/spokesperson-videos/v2/XX-name-v2.mp4
   ```
8. Verify with: `ffprobe -v error -select_streams v:0 -show_entries stream=width,height -of csv=p=0 <file>`

---

## Important Settings (ALWAYS verify before each generate)
- Model: **Veo 3.1 - Quality** (NOT Fast — Fast is the default, always change it)
- Count: x1
- Orientation: Landscape
- Extension model: also change to Veo 3.1 - Quality

## CRITICAL LESSON
**DO NOT run `pkill -f playwright-profile`** during a session. This kills the Playwright MCP Chrome process and disconnects the MCP server entirely, requiring a full Claude Code restart. If a page closes unexpectedly, just call `mcp__playwright__browser_navigate` again to reopen it.
