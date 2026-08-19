# Video → SOP Generator

Turns a Fathom meeting recording into a Standard Operating Procedure, saved as a local
.docx with screenshots pulled from the video at fixed intervals. Optionally also creates
a Google Doc.

Pipeline: Fathom transcript + video → periodic screenshots (ffmpeg) → Claude
writes the SOP → saved to `output/<title>.docx` (and optionally to Google Docs).

## 1. Prerequisites

- Python 3.10+
- [ffmpeg](https://ffmpeg.org/) on your PATH — `winget install ffmpeg`, verify with `ffmpeg -version`
- A Fathom plan with API access (Settings → API in the Fathom web app; API access requires a Team/Enterprise plan)

Install dependencies:

```bash
pip install -r requirements.txt
```

## 2. Credentials

Copy `.env.example` to `.env` and fill in the two API keys below (needed either way — Fathom
for the transcript/video, Anthropic for writing the SOP). The Google credential is only needed
if you want a Google Doc too, and is a downloaded JSON file, not an env var.

### Anthropic API key

1. Go to https://console.anthropic.com/settings/keys
2. Create a key, paste it into `.env` as `ANTHROPIC_API_KEY`.
3. Note: this needs API credits (Plans & Billing), separate from a claude.ai subscription.

### Fathom API key

1. In the Fathom web app: Settings → API.
2. If you don't see an API option, your plan doesn't include API access — you'd need to upgrade.
3. Create a key, paste it into `.env` as `FATHOM_API_KEY`.

### Google OAuth client (optional — only for `--google`)

1. Go to https://console.cloud.google.com/ and create a new project (or pick an existing one).
2. APIs & Services → Library → enable **Google Docs API** and **Google Drive API**.
3. APIs & Services → OAuth consent screen → External → fill in the required fields → add your
   own Google account under "Test users" (keeps the app in testing mode, which is fine for
   personal use — no Google review needed).
4. APIs & Services → Credentials → Create Credentials → OAuth client ID → Application type:
   **Desktop app**.
5. Download the JSON and save it as `credentials/client_secret.json` in this project.

The first time you run with `--google` it opens a browser for you to sign in and approve access;
after that it reuses a cached token at `credentials/token.json`.

## 3. Usage

```bash
python -m src.cli <fathom_url_or_recording_id>
```

Examples:

```bash
python -m src.cli https://fathom.video/calls/123456789
python -m src.cli 123456789 --frame-interval 10
python -m src.cli 123456789 --google   # also create a Google Doc
```

Flags:
- `--frame-interval SECONDS` — how often to grab a screenshot from the video (default 15)
- `--output-dir DIR` — where to save the .docx (default: `./output`)
- `--google` — also create a Google Doc (requires the OAuth client above)
- `--keep-temp` — keep the downloaded video and extracted frames in `temp/<recording_id>/`
  instead of deleting them after the doc is created

On success it prints the path to the saved `.docx` (and a Google Doc link if `--google` was passed).

## Notes / limitations

- Screenshots are picked at fixed intervals, not by scene detection — a short `--frame-interval`
  gives Claude more candidates to match against steps, at the cost of a slower run.
- Video download depends on Fathom's `/recordings/{id}/download` API being available on your plan.
- In the Google Doc (`--google`), images are inserted at a fixed 400×250pt box, so extracted
  frames get scaled without preserving aspect ratio. The local `.docx` scales images to a fixed
  width and preserves aspect ratio.
