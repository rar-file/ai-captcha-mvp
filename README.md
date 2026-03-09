# AI Captcha MVP

An **open-source** “AI captcha” demo service.

Goal: **easy for LLMs**, annoying for most humans / dumb scripts.

It generates a tiny pattern puzzle (`/generate`), checks the answer (`/verify`), then issues a short-lived JWT token. Tokens can be **redeemed once** (`/redeem`).

## What this blocks (and what it doesn’t)

- ✅ Blocks casual humans who won’t bother
- ✅ Blocks simple scripts
- ❌ Does **not** block someone who calls an LLM API to solve puzzles (that’s the point: AI-friendly)

## Run

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

export AI_CAPTCHA_JWT_SECRET='change-me'
uvicorn app:app --host 0.0.0.0 --port 8099
```

## Widget (drop-in)

Serve the widget from the same origin as the API.

Embed:

```html
<link rel="stylesheet" href="https://yourdomain.com/widget.css" />
<script src="https://yourdomain.com/widget.js" defer></script>

<div class="ai-captcha" data-sitekey="public-demo" data-token-target="ai_captcha_token"></div>
<input type="hidden" id="ai_captcha_token" name="ai_captcha_token" />
```

Hooks:
- The widget emits `aicaptcha:verified` event on the `.ai-captcha` element.
- If `window.aiCaptchaVerified` exists, it will be called with `{token, score, sitekey, puzzle_id}`.

Demo page:
- `GET /demo`

## API

### 1) Generate

```bash
curl -s http://127.0.0.1:8099/generate | jq
```

### 2) Verify

Replace `PUZZLE_ID` and `ANSWER`:

```bash
curl -s http://127.0.0.1:8099/verify \
  -H 'Content-Type: application/json' \
  -d '{"puzzle_id":"PUZZLE_ID","answer":"ANSWER"}' | jq
```

### 3) Redeem token (one-time)

```bash
curl -s http://127.0.0.1:8099/redeem \
  -H 'Content-Type: application/json' \
  -d '{"token":"JWT_HERE"}' | jq
```

## Notes

- Puzzles are stored in-memory (TTL default 120s).
- Tokens are HS256 JWTs (TTL default 120s).
- One-time redemption is tracked in-memory (resets on restart).

Next step for a real project: add Redis (or DB) for puzzles + redeemed JTIs, and add per-IP rate limits.
