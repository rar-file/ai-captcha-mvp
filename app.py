import os
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

import jwt
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field


APP_NAME = "ai-captcha-mvp"

# NOTE: For real deployment, set this via env and rotate it.
JWT_SECRET = os.environ.get("AI_CAPTCHA_JWT_SECRET", "dev-secret-change-me")
JWT_ISSUER = os.environ.get("AI_CAPTCHA_JWT_ISSUER", APP_NAME)
PUZZLE_TTL_SECONDS = int(os.environ.get("AI_CAPTCHA_PUZZLE_TTL", "120"))
TOKEN_TTL_SECONDS = int(os.environ.get("AI_CAPTCHA_TOKEN_TTL", "120"))

# Difficulty presets per sitekey (idea #3). 1=easy, 5=harder.
# You can override via env/real config later.
SITEKEYS: Dict[str, Dict[str, Any]] = {
    # Easy + forgiving
    "public-demo": {"difficulty": 2, "max_attempts": 6, "ops": ["swap", "rotate", "reverse"]},
    # Default
    "default": {"difficulty": 3, "max_attempts": 5, "ops": ["swap", "rotate", "reverse", "caesar"]},
    # Harder puzzles (more steps, fewer attempts)
    "hard": {"difficulty": 5, "max_attempts": 4, "ops": ["swap", "rotate", "reverse", "caesar"]},
    # Stress test: string logic only, no caesar, but more steps
    "logic": {"difficulty": 4, "max_attempts": 5, "ops": ["swap", "rotate", "reverse"]},
}


@dataclass
class Puzzle:
    puzzle_id: str
    sitekey: str
    difficulty: int
    type: str
    examples: List[Dict[str, str]]
    challenge: str
    instructions: str
    solution: str
    expires_at: float
    created_at: float
    attempts: int = 0
    max_attempts: int = 5


# In-memory store
PUZZLES: Dict[str, Puzzle] = {}
REDEEMED_JTI: set[str] = set()


def _now() -> float:
    return time.time()


def _cleanup_expired() -> None:
    now = _now()
    expired = [pid for pid, p in PUZZLES.items() if p.expires_at <= now]
    for pid in expired:
        PUZZLES.pop(pid, None)


def _swap_2_3(s: str) -> str:
    if len(s) < 3:
        return s
    a = list(s)
    a[1], a[2] = a[2], a[1]
    return "".join(a)


def _reverse(s: str) -> str:
    return s[::-1]


def _caesar_shift(s: str, k: int = 2) -> str:
    out = []
    for ch in s:
        if "a" <= ch <= "z":
            out.append(chr((ord(ch) - 97 + k) % 26 + 97))
        elif "A" <= ch <= "Z":
            out.append(chr((ord(ch) - 65 + k) % 26 + 65))
        else:
            out.append(ch)
    return "".join(out)


# Operations are composed into a small program per puzzle.
# We keep them simple so even a basic local LLM can infer them from 2–3 examples.

def op_swap(i: int, j: int):
    def fn(s: str) -> str:
        if len(s) <= max(i, j):
            return s
        a = list(s)
        a[i], a[j] = a[j], a[i]
        return "".join(a)

    return fn


def op_rotate(k: int):
    def fn(s: str) -> str:
        if not s:
            return s
        kk = k % len(s)
        return s[kk:] + s[:kk]

    return fn


def op_caesar(k: int):
    return lambda s: _caesar_shift(s, k)


OPERATIONS: List[Tuple[str, Any]] = [
    ("swap", op_swap),
    ("reverse", lambda: _reverse),
    ("rotate", op_rotate),
    ("caesar", op_caesar),
]

WORDS = [
    "lamp",
    "note",
    "card",
    "tree",
    "stone",
    "paper",
    "cloud",
    "mouse",
    "cable",
    "grimoire",
    "server",
    "agent",
    "token",
]


def _pick_words(n: int) -> List[str]:
    # simple deterministic-ish shuffle using uuid
    # good enough for MVP
    seed = uuid.uuid4().int
    words = WORDS[:]
    for i in range(len(words) - 1, 0, -1):
        seed = (seed * 1103515245 + 12345) & 0x7FFFFFFF
        j = seed % (i + 1)
        words[i], words[j] = words[j], words[i]
    return words[:n]


def _compose_program(difficulty: int, allowed_ops: Optional[List[str]] = None) -> Tuple[str, Any]:
    """Create a small logic program with random parameters.

    Difficulty controls step count and parameter ranges.
    allowed_ops constrains which operations are used.
    """
    difficulty = max(1, min(int(difficulty), 5))
    seed = uuid.uuid4().int

    allowed_ops = allowed_ops or [name for name, _ in OPERATIONS]
    allowed_ops = [x for x in allowed_ops if x in {name for name, _ in OPERATIONS}]
    if not allowed_ops:
        allowed_ops = [name for name, _ in OPERATIONS]

    def rnd(n: int) -> int:
        nonlocal seed
        seed = (seed * 1103515245 + 12345) & 0x7FFFFFFF
        return seed % n

    steps = []

    # 1..(2+difficulty) capped at 5
    step_count = 1 + rnd(min(5, 1 + difficulty))
    ops_map = {name: factory for name, factory in OPERATIONS}

    for _ in range(step_count):
        op_name = allowed_ops[rnd(len(allowed_ops))]
        factory = ops_map[op_name]

        if op_name == "swap":
            # positions 0..(2+difficulty) (works for typical words)
            max_pos = min(6, 2 + difficulty)
            i = rnd(max_pos)
            j = rnd(max_pos)
            if i == j:
                j = (j + 1) % max_pos
            steps.append(("swap", (i, j), factory(i, j)))

        elif op_name == "rotate":
            k = 1 + rnd(min(6, 1 + difficulty))
            steps.append(("rotate", (k,), factory(k)))

        elif op_name == "caesar":
            k = 1 + rnd(min(13, 2 + difficulty * 2))
            steps.append(("caesar", (k,), factory(k)))

        elif op_name == "reverse":
            steps.append(("reverse", tuple(), factory()))

    # Build function
    def program(s: str) -> str:
        out = s
        for _, _, fn in steps:
            out = fn(out)
        return out

    # A compact id (not revealing exact params)
    prog_id = "+".join([name for name, _, _ in steps])
    return prog_id, program


def _apply_program(seq: List[Tuple[str, Tuple[int, ...]]], s: str) -> str:
    out = s
    for name, params in seq:
        if name == "reverse":
            out = _reverse(out)
        elif name == "swap":
            i, j = params
            out = op_swap(i, j)(out)
        elif name == "rotate":
            (k,) = params
            out = op_rotate(k)(out)
        elif name == "caesar":
            (k,) = params
            out = op_caesar(k)(out)
    return out


def _count_solutions(
    examples: List[Dict[str, str]],
    allowed_ops: List[str],
    difficulty: int,
    max_steps: int,
    limit: int = 2,
) -> int:
    """Count how many programs (up to max_steps) fit the examples.

    We stop counting once we reach `limit`.

    This is a safety check to avoid ambiguous puzzles (LLMs/humans guess wrong if
    multiple rules fit the examples).
    """
    # Build candidate op list with bounded params.
    max_pos = min(6, 2 + difficulty)
    rot_max = 1 + min(6, 1 + difficulty)
    caesar_max = 1 + min(13, 2 + difficulty * 2)

    ops: List[Tuple[str, Tuple[int, ...]]] = []
    if "reverse" in allowed_ops:
        ops.append(("reverse", tuple()))
    if "swap" in allowed_ops:
        for i in range(max_pos):
            for j in range(max_pos):
                if i != j:
                    ops.append(("swap", (i, j)))
    if "rotate" in allowed_ops:
        for k in range(1, rot_max + 1):
            ops.append(("rotate", (k,)))
    if "caesar" in allowed_ops:
        for k in range(1, caesar_max + 1):
            ops.append(("caesar", (k,)))

    def fits(seq: List[Tuple[str, Tuple[int, ...]]]) -> bool:
        for ex in examples:
            if _apply_program(seq, ex["input"]) != ex["output"]:
                return False
        return True

    count = 0

    # DFS over sequences up to max_steps
    seq: List[Tuple[str, Tuple[int, ...]]] = []

    def dfs(depth: int):
        nonlocal count
        if depth > 0:
            if fits(seq):
                count += 1
                if count >= limit:
                    return True
        if depth == max_steps:
            return False
        for op in ops:
            seq.append(op)
            if dfs(depth + 1):
                return True
            seq.pop()
        return False

    dfs(0)
    return count


def generate_puzzle(sitekey: str) -> Puzzle:
    _cleanup_expired()

    sk = SITEKEYS.get(sitekey) or SITEKEYS["default"]
    difficulty = int(sk.get("difficulty", 3))
    max_attempts = int(sk.get("max_attempts", 5))
    allowed_ops = sk.get("ops") or ["swap", "rotate", "reverse", "caesar"]

    # For demo UX: keep puzzles solvable quickly.
    # More examples => less ambiguity.
    example_count = 3 if difficulty <= 3 else 4
    # Also cap effective steps to reduce ambiguous/multi-solution cases.
    effective_steps = 2 if sitekey == "public-demo" else min(3, difficulty)

    # Regenerate until we get a non-ambiguous rule (or give up).
    for _ in range(12):
        puzzle_id = uuid.uuid4().hex
        prog_id, fn = _compose_program(effective_steps, allowed_ops=allowed_ops)

        ex_words = _pick_words(example_count)
        examples = [{"input": w, "output": fn(w)} for w in ex_words]

        # Check ambiguity (only for smaller search spaces)
        if effective_steps <= 3:
            sol_count = _count_solutions(examples, allowed_ops, effective_steps, max_steps=effective_steps, limit=2)
            if sol_count != 1:
                continue

        challenge = _pick_words(1)[0]
        solution = fn(challenge)

        instructions = "Infer the transformation rule from the examples and apply it to the challenge."

        p = Puzzle(
            puzzle_id=puzzle_id,
            sitekey=sitekey,
            difficulty=difficulty,
            type=prog_id,
            examples=examples,
            challenge=challenge,
            instructions=instructions,
            solution=solution,
            expires_at=_now() + PUZZLE_TTL_SECONDS,
            created_at=_now(),
            attempts=0,
            max_attempts=max_attempts,
        )

        PUZZLES[puzzle_id] = p
        return p

    # Fallback: generate without ambiguity check
    puzzle_id = uuid.uuid4().hex
    prog_id, fn = _compose_program(min(3, difficulty), allowed_ops=allowed_ops)
    ex_words = _pick_words(3)
    examples = [{"input": w, "output": fn(w)} for w in ex_words]
    challenge = _pick_words(1)[0]
    solution = fn(challenge)

    p = Puzzle(
        puzzle_id=puzzle_id,
        sitekey=sitekey,
        difficulty=difficulty,
        type=prog_id,
        examples=examples,
        challenge=challenge,
        instructions="Infer the transformation rule from the examples and apply it to the challenge.",
        solution=solution,
        expires_at=_now() + PUZZLE_TTL_SECONDS,
        created_at=_now(),
        attempts=0,
        max_attempts=max_attempts,
    )
    PUZZLES[puzzle_id] = p
    return p


def mint_token(p: Puzzle, score: float) -> str:
    now = int(time.time())
    jti = uuid.uuid4().hex
    payload = {
        "iss": JWT_ISSUER,
        "sub": "ai-captcha",
        "iat": now,
        "exp": now + TOKEN_TTL_SECONDS,
        "jti": jti,
        "puzzle_id": p.puzzle_id,
        "sitekey": p.sitekey,
        "difficulty": p.difficulty,
        "score": score,
    }
    return jwt.encode(payload, JWT_SECRET, algorithm="HS256")


def decode_token(token: str) -> Dict[str, Any]:
    return jwt.decode(token, JWT_SECRET, algorithms=["HS256"], issuer=JWT_ISSUER)


class VerifyRequest(BaseModel):
    puzzle_id: str = Field(..., min_length=8)
    answer: str = Field(..., min_length=1, max_length=200)
    action: str = Field(default="default", max_length=80)


class RedeemRequest(BaseModel):
    token: str = Field(..., min_length=20)


app = FastAPI(title=APP_NAME)


@app.api_route("/widget.js", methods=["GET", "HEAD"])
def widget_js():
    # Serve as plain JS (disable caching during rapid iteration)
    from fastapi.responses import FileResponse

    return FileResponse(
        "widget.js",
        media_type="application/javascript",
        headers={"Cache-Control": "no-store"},
    )


@app.api_route("/widget.css", methods=["GET", "HEAD"])
def widget_css():
    from fastapi.responses import FileResponse

    return FileResponse(
        "widget.css",
        media_type="text/css",
        headers={"Cache-Control": "no-store"},
    )


@app.get("/demo")
def demo():
    """Single-widget demo (public-demo)."""
    from fastapi.responses import HTMLResponse

    html = """<!doctype html>
<html>
<head>
  <meta charset='utf-8' />
  <meta name='viewport' content='width=device-width,initial-scale=1' />
  <title>AI Captcha Demo</title>
  <link rel='stylesheet' href='/widget.css' />
  <style>
    body{background:#f7f8fb;color:#0f172a;font-family:system-ui;display:flex;justify-content:center;padding:30px}
    .wrap{max-width:820px;width:100%}
    pre{background:#ffffff;border:1px solid #e6e8ef;padding:10px;border-radius:12px;display:block;overflow:auto}
    .row{display:flex;gap:16px;flex-wrap:wrap;align-items:flex-start}
    .card{flex:1;min-width:320px}
  </style>
</head>
<body>
  <div class='wrap'>
    <h2>AI Captcha Demo</h2>
    <p style='color:#475569'>Single widget (sitekey: <b>public-demo</b>). For more, use <a href='/demo-suite'>/demo-suite</a>.</p>

    <form id='demoForm' class='card'>
      <div class='ai-captcha' data-sitekey='public-demo' data-token-target='ai_captcha_token'></div>
      <input type='hidden' id='ai_captcha_token' name='ai_captcha_token' />
      <button type='submit' style='margin-top:14px'>Submit</button>
    </form>

    <h3>Redeem (server-side simulation)</h3>
    <pre id='out'>(submit after verify)</pre>

    <script src='/widget.js' defer></script>
    <script>
      document.querySelector('.ai-captcha').addEventListener('aicaptcha:verified', (e) => {
        console.log('verified', e.detail);
      });

      document.getElementById('demoForm').addEventListener('submit', async (e) => {
        e.preventDefault();
        const token = document.getElementById('ai_captcha_token').value;
        const out = document.getElementById('out');
        if (!token) { out.textContent = 'no token yet'; return; }
        const r = await fetch('/redeem', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({token})});
        out.textContent = await r.text();
      });
    </script>
  </div>
</body>
</html>"""
    return HTMLResponse(html)


@app.get("/demo-suite")
def demo_suite():
    """Multiple demos with different sitekeys (public-demo/default/logic/hard)."""
    from fastapi.responses import HTMLResponse

    html = """<!doctype html>
<html>
<head>
  <meta charset='utf-8' />
  <meta name='viewport' content='width=device-width,initial-scale=1' />
  <title>AI Captcha Demo Suite</title>
  <link rel='stylesheet' href='/widget.css' />
  <style>
    body{background:#f7f8fb;color:#0f172a;font-family:system-ui;display:flex;justify-content:center;padding:30px}
    .wrap{max-width:1080px;width:100%}
    pre{background:#ffffff;border:1px solid #e6e8ef;padding:10px;border-radius:12px;display:block;overflow:auto}
    .grid{display:grid;grid-template-columns:repeat(2,minmax(320px,1fr));gap:18px}
    @media (max-width: 820px){.grid{grid-template-columns:1fr}}
    .capTitle{margin:0 0 8px;color:#334155}
  </style>
</head>
<body>
  <div class='wrap'>
    <h2>AI Captcha Demo Suite</h2>
    <p style='color:#475569'>Try different sitekeys (difficulty/ops/attempts). Each widget writes to its own token box.</p>

    <div class='grid'>
      <div>
        <h4 class='capTitle'>public-demo (easy, no caesar)</h4>
        <div class='ai-captcha' data-sitekey='public-demo' data-token-target='t1'></div>
        <input type='hidden' id='t1'/>
      </div>
      <div>
        <h4 class='capTitle'>default (mixed ops)</h4>
        <div class='ai-captcha' data-sitekey='default' data-token-target='t2'></div>
        <input type='hidden' id='t2'/>
      </div>
      <div>
        <h4 class='capTitle'>logic (more steps, no caesar)</h4>
        <div class='ai-captcha' data-sitekey='logic' data-token-target='t3'></div>
        <input type='hidden' id='t3'/>
      </div>
      <div>
        <h4 class='capTitle'>hard (max)</h4>
        <div class='ai-captcha' data-sitekey='hard' data-token-target='t4'></div>
        <input type='hidden' id='t4'/>
      </div>
    </div>

    <h3 style='margin-top:22px'>Redeem tokens (server-side simulation)</h3>
    <pre id='out'>(verify one of the widgets, then click redeem)</pre>
    <button id='redeemBtn' style='margin-top:10px'>Redeem latest token</button>

    <script src='/widget.js' defer></script>
    <script>
      let lastToken = null;
      document.querySelectorAll('.ai-captcha').forEach(el => {
        el.addEventListener('aicaptcha:verified', (e) => { lastToken = e.detail.token; });
      });

      document.getElementById('redeemBtn').addEventListener('click', async () => {
        const out = document.getElementById('out');
        if (!lastToken) { out.textContent = 'no token yet'; return; }
        const r = await fetch('/redeem', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({token:lastToken})});
        out.textContent = await r.text();
      });
    </script>
  </div>
</body>
</html>"""
    return HTMLResponse(html)


@app.get("/generate")
def generate(sitekey: str = "public-demo"):
    p = generate_puzzle(sitekey=sitekey)
    return {
        "puzzle_id": p.puzzle_id,
        "sitekey": p.sitekey,
        "difficulty": p.difficulty,
        "type": p.type,
        "examples": p.examples,
        "challenge": p.challenge,
        "instructions": p.instructions,
        "expires_at": int(p.expires_at),
        "max_attempts": p.max_attempts,
    }


@app.post("/verify")
def verify(req: VerifyRequest):
    """Verify answer. Implements anti-guess (idea #5) and score (idea #10)."""
    _cleanup_expired()
    p = PUZZLES.get(req.puzzle_id)
    if not p:
        raise HTTPException(status_code=404, detail="Puzzle not found or expired")

    # attempts
    p.attempts += 1
    if p.attempts > p.max_attempts:
        return {"pass": False, "reason": "too_many_attempts"}

    passed = req.answer.strip() == p.solution
    if not passed:
        # return remaining attempts so widget can show it
        return {"pass": False, "reason": "wrong", "attempts_left": max(0, p.max_attempts - p.attempts)}

    # score: start at 1.0, subtract for time + retries + difficulty
    solve_seconds = max(0.0, _now() - p.created_at)
    score = 1.0
    score -= min(0.45, solve_seconds / 60.0 * 0.25)  # slow solve penalty
    score -= min(0.40, (p.attempts - 1) * 0.15)      # retry penalty
    score -= min(0.25, (p.difficulty - 1) * 0.05)    # difficulty penalty
    score = max(0.0, min(1.0, score))

    token = mint_token(p, score)
    return {"pass": True, "token": token, "score": score}


@app.post("/redeem")
def redeem(req: RedeemRequest):
    try:
        payload = decode_token(req.token)
    except jwt.ExpiredSignatureError:
        return {"valid": False, "reason": "expired"}
    except Exception:
        return {"valid": False, "reason": "invalid"}

    jti = payload.get("jti")
    if not jti:
        return {"valid": False, "reason": "invalid"}

    if jti in REDEEMED_JTI:
        return {"valid": False, "reason": "already_redeemed"}

    REDEEMED_JTI.add(jti)
    return {
        "valid": True,
        "puzzle_id": payload.get("puzzle_id"),
        "sitekey": payload.get("sitekey"),
        "difficulty": payload.get("difficulty"),
        "score": payload.get("score"),
    }
