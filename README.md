# AI Captcha (MVP)

An open-source **AI-friendly captcha** you can embed like Turnstile.

This project is intentionally **easy for LLMs/agents** and **annoying for most humans / dumb scripts**.

It works by:
- generating a short logic puzzle (`GET /generate`)
- verifying the answer (`POST /verify`) and issuing a short-lived JWT
- redeeming the JWT once (`POST /redeem`) on your backend

## Demo

- Widget demo page: `GET /demo`

If you’re running it on a host with a reachable IP:
- `http://HOST:8099/demo`

## What it blocks (and what it doesn’t)

- ✅ blocks casual humans (they won’t bother)
- ✅ blocks simple scripts (rate limits + attempts + cooldown)
- ❌ **does not** block someone who uses an LLM API to solve it (that’s the point)

## Quickstart

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

export AI_CAPTCHA_JWT_SECRET='change-me'
uvicorn app:app --host 0.0.0.0 --port 8099
```

## Drop-in widget (Turnstile-ish)

Serve the widget from the same origin as the API.

```html
<link rel="stylesheet" href="https://yourdomain.com/widget.css" />
<script src="https://yourdomain.com/widget.js" defer></script>

<form method="POST" action="/submit">
  <div class="ai-captcha" data-sitekey="public-demo" data-token-target="ai_captcha_token"></div>
  <input type="hidden" id="ai_captcha_token" name="ai_captcha_token" />
  <button type="submit">Continue</button>
</form>
```

### Widget hooks

- Emits an event: `aicaptcha:verified`
  - `detail = { token, score, sitekey, puzzle_id }`
- Optional global callback:
  - `window.aiCaptchaVerified = ({ token, score, sitekey, puzzle_id }) => { ... }`

### Sitekeys (difficulty)

`GET /generate?sitekey=...`

Built-in presets:
- `public-demo` (easy-ish)
- `default`
- `hard` (more steps, fewer attempts)

## API

### `GET /generate`

```bash
curl -s "http://127.0.0.1:8099/generate?sitekey=public-demo" | jq
```

Response includes:
- `puzzle_id`, `examples[]`, `challenge`
- `difficulty`, `max_attempts`, `expires_at`

### `POST /verify`

```bash
curl -s http://127.0.0.1:8099/verify \
  -H 'Content-Type: application/json' \
  -d '{"puzzle_id":"PUZZLE_ID","answer":"ANSWER","action":"signup"}' | jq
```

- On success: `{ pass: true, token, score }`
- On fail: `{ pass: false, reason, attempts_left }`

### `POST /redeem` (server-side)

Redeem from **your backend**, not the browser.

```bash
curl -s http://127.0.0.1:8099/redeem \
  -H 'Content-Type: application/json' \
  -d '{"token":"JWT_HERE"}' | jq
```

- One-time redeem per token (`already_redeemed` after).

## How the puzzles work

Each request builds a small random **program** (1–5 steps depending on difficulty), e.g.
- `swap(i,j)`
- `rotate(k)`
- `reverse`
- `caesar(k)`

The program changes every request so it’s hard to “patternise” with hard-coded rules.

## Security / production notes

This is an MVP.

For real usage:
- use Redis/DB for puzzle storage + redeemed JTIs
- add IP + user-agent rate limits (and maybe a server-side cooldown)
- bind token to `origin`/`action`/`audience`
- rotate `AI_CAPTCHA_JWT_SECRET`

## License

Pick a license (MIT is typical for open source). Add `LICENSE` when ready.
