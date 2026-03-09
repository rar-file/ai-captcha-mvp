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
    "public-demo": {"difficulty": 2, "max_attempts": 6},
    "default": {"difficulty": 3, "max_attempts": 5},
    "hard": {"difficulty": 5, "max_attempts": 4},
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


def _compose_program(difficulty: int) -> Tuple[str, Any]:
    """Create a small logic program with random parameters.

    Difficulty controls step count and parameter ranges.
    """
    difficulty = max(1, min(int(difficulty), 5))
    seed = uuid.uuid4().int

    def rnd(n: int) -> int:
        nonlocal seed
        seed = (seed * 1103515245 + 12345) & 0x7FFFFFFF
        return seed % n

    steps = []

    # 1..(2+difficulty) capped at 5
    step_count = 1 + rnd(min(5, 1 + difficulty))
    for _ in range(step_count):
        op_name, factory = OPERATIONS[rnd(len(OPERATIONS))]

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


def generate_puzzle(sitekey: str) -> Puzzle:
    _cleanup_expired()

    sk = SITEKEYS.get(sitekey) or SITEKEYS["default"]
    difficulty = int(sk.get("difficulty", 3))
    max_attempts = int(sk.get("max_attempts", 5))

    puzzle_id = uuid.uuid4().hex

    prog_id, fn = _compose_program(difficulty)

    ex_words = _pick_words(3)
    examples = [{"input": w, "output": fn(w)} for w in ex_words]

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


@app.get("/widget.js")
def widget_js():
    # Serve as plain JS (disable caching during rapid iteration)
    from fastapi.responses import FileResponse

    return FileResponse(
        "widget.js",
        media_type="application/javascript",
        headers={"Cache-Control": "no-store"},
    )


@app.get("/widget.css")
def widget_css():
    from fastapi.responses import FileResponse

    return FileResponse(
        "widget.css",
        media_type="text/css",
        headers={"Cache-Control": "no-store"},
    )


@app.get("/demo")
def demo():
    from fastapi.responses import HTMLResponse
    import qrcode
    import qrcode.image.svg
    import base64
    from io import BytesIO
    
    # Generate QR code
    qr = qrcode.QRCode(version=1, box_size=10, border=2)
    qr.add_data("https://openclaw.taila95556.ts.net/demo")
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")
    buffered = BytesIO()
    img.save(buffered, format="PNG")
    qr_base64 = base64.b64encode(buffered.getvalue()).decode()

    html = f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>AI Captcha — Reverse Turing Test</title>
  <link href="https://fonts.googleapis.com/css2?family=Roboto:wght@400;500;700&amp;family=Roboto+Mono:wght@400;500&amp;display=swap" rel="stylesheet">
  <link rel="stylesheet" href="/widget.css">
  <style>
    :root{{
      --bg:#f8f9fa;
      --surface:#ffffff;
      --surface-2:#f1f3f4;
      --border:#dadce0;
      --text:#202124;
      --text-secondary:#5f6368;
      --primary:#1a73e8;
      --primary-hover:#1557b0;
      --success:#188038;
      --error:#d93025;
      --shadow:0 1px 2px rgba(60,64,67,0.1),0 2px 6px rgba(60,64,67,0.08);
    }}
    
    [data-theme="dark"] {{
      --bg:#1a1a1a;
      --surface:#2d2d2d;
      --surface-2:#3d3d3d;
      --border:#404040;
      --text:#e8eaed;
      --text-secondary:#9aa0a6;
      --primary:#8ab4f8;
      --primary-hover:#aecbfa;
      --shadow:0 1px 2px rgba(0,0,0,0.3),0 2px 6px rgba(0,0,0,0.2);
    }}
    
    *{{margin:0;padding:0;box-sizing:border-box}}
    
    body{{
      background:var(--bg);
      color:var(--text);
      font-family:'Roboto',system-ui,-apple-system,sans-serif;
      line-height:1.6;
      min-height:100vh;
      transition:background 0.3s,color 0.3s;
    }}
    
    .container{{
      max-width:1000px;
      margin:0 auto;
      padding:40px 20px;
    }}
    
    /* Nav */
    .nav{{
      display:flex;
      align-items:center;
      justify-content:space-between;
      margin-bottom:40px;
      padding-bottom:20px;
      border-bottom:1px solid var(--border);
      flex-wrap:wrap;
      gap:16px;
    }}
    
    .nav-logo{{
      display:flex;
      align-items:center;
      gap:12px;
      font-weight:700;
      font-size:22px;
      color:var(--text);
    }}
    
    .nav-logo-icon{{
      width:36px;
      height:36px;
      background:linear-gradient(135deg,var(--primary),#4285f4);
      border-radius:8px;
      display:grid;
      place-items:center;
      color:#fff;
      font-size:13px;
      font-weight:800;
    }}
    
    .nav-controls{{
      display:flex;
      align-items:center;
      gap:16px;
    }}
    
    .theme-toggle{{
      display:flex;
      align-items:center;
      gap:8px;
      padding:8px 16px;
      background:var(--surface);
      border:1px solid var(--border);
      border-radius:20px;
      cursor:pointer;
      font-size:14px;
      color:var(--text-secondary);
      transition:all 0.2s;
    }}
    
    .theme-toggle:hover{{
      border-color:var(--primary);
      color:var(--primary);
    }}
    
    /* Hero */
    .hero{{
      text-align:center;
      margin-bottom:48px;
    }}
    
    .hero h1{{
      font-size:52px;
      font-weight:300;
      color:var(--text);
      margin-bottom:16px;
      letter-spacing:-0.5px;
    }}
    
    .hero p{{
      font-size:18px;
      color:var(--text-secondary);
      max-width:560px;
      margin:0 auto 24px;
    }}
    
    .hero-badge{{
      display:inline-flex;
      align-items:center;
      gap:8px;
      padding:8px 16px;
      background:var(--surface);
      border:1px solid var(--border);
      border-radius:20px;
      font-size:14px;
      color:var(--text-secondary);
    }}
    
    /* Controls Panel */
    .controls-panel{{
      display:grid;
      grid-template-columns:repeat(auto-fit,minmax(200px,1fr));
      gap:24px;
      margin-bottom:32px;
    }}
    
    .control-group{{
      background:var(--surface);
      border:1px solid var(--border);
      border-radius:12px;
      padding:20px;
    }}
    
    .control-group h3{{
      font-size:13px;
      font-weight:600;
      color:var(--text-secondary);
      text-transform:uppercase;
      letter-spacing:0.5px;
      margin-bottom:16px;
    }}
    
    .slider-wrap{{
      display:flex;
      align-items:center;
      gap:12px;
    }}
    
    .slider{{
      flex:1;
      -webkit-appearance:none;
      height:6px;
      border-radius:3px;
      background:var(--surface-2);
      outline:none;
    }}
    
    .slider::-webkit-slider-thumb{{
      -webkit-appearance:none;
      width:20px;
      height:20px;
      border-radius:50%;
      background:var(--primary);
      cursor:pointer;
      border:2px solid var(--surface);
      box-shadow:0 2px 4px rgba(0,0,0,0.2);
    }}
    
    .slider-value{{
      min-width:32px;
      text-align:center;
      font-family:'Roboto Mono',monospace;
      font-weight:600;
      color:var(--primary);
    }}
    
    .toggle-row{{
      display:flex;
      align-items:center;
      justify-content:space-between;
      margin-bottom:12px;
    }}
    
    .toggle-label{{
      font-size:14px;
      color:var(--text);
    }}
    
    .toggle{{
      position:relative;
      width:44px;
      height:24px;
    }}
    
    .toggle input{{
      opacity:0;
      width:0;
      height:0;
    }}
    
    .toggle-slider{{
      position:absolute;
      inset:0;
      background:var(--surface-2);
      border-radius:24px;
      cursor:pointer;
      transition:background 0.2s;
    }}
    
    .toggle-slider::before{{
      content:'';
      position:absolute;
      width:18px;
      height:18px;
      left:3px;
      top:3px;
      background:#fff;
      border-radius:50%;
      transition:transform 0.2s;
      box-shadow:0 1px 3px rgba(0,0,0,0.2);
    }}
    
    .toggle input:checked + .toggle-slider{{
      background:var(--primary);
    }}
    
    .toggle input:checked + .toggle-slider::before{{
      transform:translateX(20px);
    }}
    
    /* QR Code */
    .qr-wrap{{
      text-align:center;
    }}
    
    .qr-code{{
      width:120px;
      height:120px;
      border-radius:8px;
      margin:0 auto 12px;
    }}
    
    .qr-text{{
      font-size:12px;
      color:var(--text-secondary);
    }}
    
    /* Main Demo */
    .demo-section{{
      display:grid;
      grid-template-columns:1fr 1fr;
      gap:32px;
      margin-bottom:48px;
    }}
    
    @media (max-width:768px){{
      .demo-section{{grid-template-columns:1fr}}
      .hero h1{{font-size:36px}}
    }}
    
    .demo-card{{
      background:var(--surface);
      border:1px solid var(--border);
      border-radius:16px;
      padding:32px;
      box-shadow:var(--shadow);
    }}
    
    .demo-card h2{{
      font-size:22px;
      font-weight:500;
      color:var(--text);
      margin-bottom:8px;
    }}
    
    .demo-card p{{
      color:var(--text-secondary);
      font-size:14px;
      margin-bottom:24px;
    }}
    
    .widget-container{{
      display:flex;
      justify-content:center;
      margin-bottom:20px;
      min-height:200px;
      align-items:center;
    }}
    
    .btn-primary{{
      width:100%;
      padding:14px 24px;
      background:var(--primary);
      color:#fff;
      border:none;
      border-radius:8px;
      font-size:15px;
      font-weight:500;
      cursor:pointer;
      transition:all 0.2s;
    }}
    
    .btn-primary:hover:not(:disabled){{
      background:var(--primary-hover);
      transform:translateY(-1px);
    }}
    
    .btn-primary:disabled{{
      background:var(--border);
      cursor:not-allowed;
    }}
    
    .result-box{{
      background:var(--surface-2);
      border:1px solid var(--border);
      border-radius:8px;
      padding:16px;
      font-family:'Roboto Mono',monospace;
      font-size:12px;
      color:var(--text-secondary);
      min-height:150px;
      white-space:pre-wrap;
      word-break:break-all;
    }}
    
    .result-box.success{{
      background:rgba(24,128,56,0.1);
      border-color:var(--success);
      color:var(--success);
    }}
    
    .result-box.error{{
      background:rgba(217,48,37,0.1);
      border-color:var(--error);
      color:var(--error);
    }}
    
    /* Embed Generator */
    .embed-section{{
      background:var(--surface);
      border:1px solid var(--border);
      border-radius:16px;
      padding:32px;
      margin-bottom:48px;
    }}
    
    .embed-section h2{{
      font-size:22px;
      font-weight:500;
      margin-bottom:8px;
    }}
    
    .embed-section p{{
      color:var(--text-secondary);
      font-size:14px;
      margin-bottom:24px;
    }}
    
    .code-block{{
      background:var(--surface-2);
      border:1px solid var(--border);
      border-radius:8px;
      padding:16px;
      font-family:'Roboto Mono',monospace;
      font-size:13px;
      color:var(--text);
      position:relative;
      overflow-x:auto;
    }}
    
    .copy-btn{{
      position:absolute;
      top:12px;
      right:12px;
      padding:6px 12px;
      background:var(--surface);
      border:1px solid var(--border);
      border-radius:4px;
      font-size:12px;
      cursor:pointer;
      color:var(--text-secondary);
    }}
    
    .copy-btn:hover{{
      border-color:var(--primary);
      color:var(--primary);
    }}
    
    /* Stats */
    .stats{{
      display:grid;
      grid-template-columns:repeat(4,1fr);
      gap:24px;
      margin-bottom:48px;
    }}
    
    @media (max-width:768px){{
      .stats{{grid-template-columns:repeat(2,1fr)}}
    }}
    
    .stat{{
      text-align:center;
      padding:24px;
      background:var(--surface);
      border:1px solid var(--border);
      border-radius:12px;
    }}
    
    .stat-value{{
      font-size:32px;
      font-weight:300;
      color:var(--primary);
      margin-bottom:4px;
    }}
    
    .stat-label{{
      font-size:12px;
      color:var(--text-secondary);
      text-transform:uppercase;
      letter-spacing:0.5px;
    }}
    
    /* Features */
    .features{{
      display:grid;
      grid-template-columns:repeat(3,1fr);
      gap:24px;
      margin-bottom:48px;
    }}
    
    @media (max-width:768px){{
      .features{{grid-template-columns:1fr}}
    }}
    
    .feature{{
      text-align:center;
      padding:32px 24px;
      background:var(--surface);
      border:1px solid var(--border);
      border-radius:12px;
      transition:transform 0.2s,box-shadow 0.2s;
    }}
    
    .feature:hover{{
      transform:translateY(-4px);
      box-shadow:var(--shadow);
    }}
    
    .feature-icon{{
      width:56px;
      height:56px;
      background:linear-gradient(135deg,var(--primary),#4285f4);
      border-radius:50%;
      display:grid;
      place-items:center;
      margin:0 auto 16px;
      color:#fff;
      font-size:24px;
    }}
    
    .feature h3{{
      font-size:16px;
      font-weight:500;
      color:var(--text);
      margin-bottom:8px;
    }}
    
    .feature p{{
      font-size:14px;
      color:var(--text-secondary);
    }}
    
    /* Footer */
    .footer{{
      text-align:center;
      padding-top:32px;
      border-top:1px solid var(--border);
      color:var(--text-secondary);
      font-size:14px;
    }}
    
    .footer a{{
      color:var(--primary);
      text-decoration:none;
    }}
    
    .footer a:hover{{
      text-decoration:underline;
    }}
    
    /* Mode selector */
    .mode-selector{{
      display:flex;
      gap:8px;
      margin-bottom:16px;
    }}
    
    .mode-btn{{
      flex:1;
      padding:10px;
      background:var(--surface-2);
      border:1px solid var(--border);
      border-radius:8px;
      cursor:pointer;
      font-size:13px;
      color:var(--text-secondary);
      transition:all 0.2s;
    }}
    
    .mode-btn.active{{
      background:var(--primary);
      border-color:var(--primary);
      color:#fff;
    }}
    
    .mode-btn:hover:not(.active){{
      border-color:var(--primary);
      color:var(--primary);
    }}
  </style>
</head>
<body>
  <div class="container">
    <nav class="nav">
      <div class="nav-logo">
        <div class="nav-logo-icon">AI</div>
        AI Captcha
      </div>
      <div class="nav-controls">
        <button class="theme-toggle" id="themeToggleBtn">
          <span id="theme-icon">🌙</span>
          <span id="theme-text">Dark</span>
        </button>
        <a href="https://github.com/rar-file/ai-captcha-mvp" target="_blank" style="color:var(--text-secondary);text-decoration:none;font-size:14px;font-weight:500;">GitHub</a>
      </div>
    </nav>
    
    <div class="hero">
      <h1>Reverse Turing Test</h1>
      <p>A proof-of-work CAPTCHA designed for AI agents. Verify your users are artificial intelligence, not humans.</p>
      <div class="hero-badge">
        <span style="color:var(--success);">●</span> System Operational
      </div>
    </div>
    
    <!-- Controls Panel -->
    <div class="controls-panel">
      <div class="control-group">
        <h3>Difficulty Level</h3>
        <div class="slider-wrap">
          <input type="range" class="slider" id="difficulty" min="1" max="5" value="2" id="difficultySlider">
          <span class="slider-value" id="diffValue">2</span>
        </div>
      </div>
      
      <div class="control-group">
        <h3>Challenge Mode</h3>
        <div class="mode-selector">
          <button class="mode-btn active" id="mode-single" data-mode="single">Single</button>
          <button class="mode-btn" id="mode-parallel" data-mode="parallel">Parallel (5x)</button>
          <button class="mode-btn" id="mode-invisible" data-mode="invisible">Invisible</button>
          <button class="mode-btn" id="mode-stealth" data-mode="stealth">🔒 Stealth</button>
        </div>
      </div>
      
      <div class="control-group">
        <h3>Test on Mobile</h3>
        <div class="qr-wrap">
          <img src="data:image/png;base64,{qr_base64}" class="qr-code" alt="QR Code">
          <div class="qr-text">Scan to test</div>
        </div>
      </div>
    </div>
    
    <!-- Stats -->
    <div class="stats">
      <div class="stat">
        <div class="stat-value" id="stat-solve-time">-</div>
        <div class="stat-label">Avg Solve Time</div>
      </div>
      <div class="stat">
        <div class="stat-value" id="stat-success">-</div>
        <div class="stat-label">Success Rate</div>
      </div>
      <div class="stat">
        <div class="stat-value">5</div>
        <div class="stat-label">Difficulty Levels</div>
      </div>
      <div class="stat">
        <div class="stat-value">∞</div>
        <div class="stat-label">AI-Native</div>
      </div>
    </div>
    
    <!-- Demo Section -->
    <div class="demo-section">
      <div class="demo-card">
        <h2>Try the Widget</h2>
        <p>Configure settings above, then check the box to start.</p>
        
        <div class="widget-container" id="widgetContainer">
          <div class="ai-captcha" 
               id="demoWidget"
               data-sitekey="public-demo" 
               data-token-target="ai_captcha_token"
               data-difficulty="2"></div>
        </div>
        
        <input type="hidden" id="ai_captcha_token">
        <button class="btn-primary" id="submitBtn" id="validateBtn" disabled>Complete CAPTCHA to Continue</button>
      </div>
      
      <div class="demo-card">
        <h2>Server Response</h2>
        <p>JWT token validation with replay protection.</p>
        
        <div class="result-box" id="resultBox">Complete the CAPTCHA to see the server validation response.</div>
      </div>
    </div>
    
    <!-- Embed Generator -->
    <div class="embed-section">
      <h2>Embed on Your Site</h2>
      <p>Copy this code to add the AI Captcha widget to your website.</p>
      
      <div class="code-block">
        <button class="copy-btn" id="copyEmbedBtn">Copy</button>
        <code id="embedCode">&lt;div class="ai-captcha" data-sitekey="your-sitekey" data-token-target="ai_captcha_token"&gt;&lt;/div&gt;
&lt;script src="https://openclaw.taila95556.ts.net/widget.js" defer&gt;&lt;/script&gt;</code>
      </div>
    </div>
    
    <!-- Features -->
    <div class="features">
      <div class="feature">
        <div class="feature-icon">🔐</div>
        <h3>JWT Tokens</h3>
        <p>Signed tokens with configurable expiration and replay protection.</p>
      </div>
      <div class="feature">
        <div class="feature-icon">⚡</div>
        <h3>Speed Detection</h3>
        <p>Track solve times. Fast AI solves vs slow human attempts.</p>
      </div>
      <div class="feature">
        <div class="feature-icon">🎯</div>
        <h3>Adaptive Difficulty</h3>
        <p>5 levels from simple swaps to complex multi-step transforms.</p>
      </div>
      <div class="feature">
        <div class="feature-icon">👻</div>
        <h3>Invisible Mode</h3>
        <p>Hidden challenges only AI agents can parse from the DOM.</p>
      </div>
      <div class="feature">
        <div class="feature-icon">🔄</div>
        <h3>Parallel Solving</h3>
        <p>Solve 5 puzzles simultaneously. Tests AI throughput.</p>
      </div>
      <div class="feature">
        <div class="feature-icon">🤖</div>
        <h3>AI Native</h3>
        <p>Designed for LLMs. Copy-paste prompts work instantly.</p>
      </div>
      
      <div class="feature">
        <div class="feature-icon">🕵️</div>
        <h3>Stealth Mode</h3>
        <p>Challenges hidden in data-attributes and zero-width unicode.</p>
      </div>
    </div>
    
    <footer class="footer">
      <p>Open source by <a href="https://github.com/rar-file">@rar-file</a>. Not affiliated with Google or reCAPTCHA.</p>
    </footer>
  </div>

  <script src="/widget.js" defer></script>
  <script>
    // Theme handling
    function initTheme() {{
      const saved = localStorage.getItem('theme');
      const prefersDark = window.matchMedia('(prefers-color-scheme: dark)').matches;
      const theme = saved || (prefersDark ? 'dark' : 'light');
      document.documentElement.setAttribute('data-theme', theme);
      updateThemeUI(theme);
    }}
    
    function toggleTheme() {{
      const current = document.documentElement.getAttribute('data-theme');
      const next = current === 'dark' ? 'light' : 'dark';
      document.documentElement.setAttribute('data-theme', next);
      localStorage.setItem('theme', next);
      updateThemeUI(next);
    }}
    
    function updateThemeUI(theme) {{
      const icon = document.getElementById('theme-icon');
      const text = document.getElementById('theme-text');
      icon.textContent = theme === 'dark' ? '☀️' : '🌙';
      text.textContent = theme === 'dark' ? 'Light' : 'Dark';
    }}
    
    // Difficulty
    function updateDifficulty(val) {{
      document.getElementById('diffValue').textContent = val;
      const widget = document.getElementById('demoWidget');
      widget.setAttribute('data-difficulty', val);
      refreshWidget();
    }}
    
    // Mode switching
    let currentMode = 'single';
    
    function setMode(mode) {{
      currentMode = mode;
      document.querySelectorAll('.mode-btn').forEach(b => b.classList.remove('active'));
      document.getElementById('mode-' + mode).classList.add('active');
      
      const widget = document.getElementById('demoWidget');
      widget.removeAttribute('data-parallel');
      widget.removeAttribute('data-invisible');
      
      if (mode === 'parallel') {{
        widget.setAttribute('data-parallel', 'true');
      }} else if (mode === 'invisible') {{
        widget.setAttribute('data-invisible', 'true');
      }}
      
      refreshWidget();
    }}
    
    function refreshWidget() {{
      const container = document.getElementById('widgetContainer');
      const oldWidget = document.getElementById('demoWidget');
      const newWidget = oldWidget.cloneNode(true);
      newWidget.innerHTML = '';
      container.innerHTML = '';
      container.appendChild(newWidget);
      
      // Re-init
      if (window.aicaptchaBoot) window.aicaptchaBoot();
    }}
    
    // Widget event
    let solveStartTime = null;
    
    document.addEventListener('aicaptcha:verified', (e) => {{
      const btn = document.getElementById('submitBtn');
      btn.disabled = false;
      btn.textContent = 'Validate Token';
      
      if (e.detail.solveTime) {{
        document.getElementById('stat-solve-time').textContent = (e.detail.solveTime / 1000).toFixed(2) + 's';
      }}
    }});
    
    document.addEventListener('aicaptcha:started', () => {{
      solveStartTime = Date.now();
    }});
    
    // Validation
    async function validateToken() {{
      const token = document.getElementById('ai_captcha_token').value;
      const btn = document.getElementById('submitBtn');
      const result = document.getElementById('resultBox');
      
      if (!token) {{
        result.className = 'result-box error';
        result.textContent = 'Error: No token. Complete the CAPTCHA first.';
        return;
      }}
      
      btn.disabled = true;
      btn.textContent = 'Validating...';
      result.className = 'result-box';
      result.textContent = 'Validating JWT token...';
      
      try {{
        const r = await fetch('/redeem', {{
          method: 'POST',
          headers: {{'Content-Type': 'application/json'}},
          body: JSON.stringify({{token}})
        }});
        const data = await r.json();
        
        if (data.valid) {{
          result.className = 'result-box success';
          result.textContent = '✓ Token Validated Successfully\n\n' + JSON.stringify(data, null, 2);
          btn.textContent = '✓ Verified';
          document.getElementById('stat-success').textContent = '100%';
        }} else {{
          result.className = 'result-box error';
          result.textContent = '✗ Validation Failed\n\n' + JSON.stringify(data, null, 2);
          btn.disabled = false;
          btn.textContent = 'Try Again';
          document.getElementById('stat-success').textContent = '0%';
        }}
      }} catch (err) {{
        result.className = 'result-box error';
        result.textContent = 'Error: ' + err.message;
        btn.disabled = false;
        btn.textContent = 'Try Again';
      }}
    }}
    
    // Copy embed
    function copyEmbed() {{
      const code = document.getElementById('embedCode').textContent;
      navigator.clipboard.writeText(code).then(() => {{
        const btn = document.querySelector('.copy-btn');
        const orig = btn.textContent;
        btn.textContent = 'Copied!';
        setTimeout(() => btn.textContent = orig, 2000);
      }});
    }}
    
    // Event listeners (after DOM ready)
    function setupEventListeners() {{
      document.getElementById('themeToggleBtn').addEventListener('click', toggleTheme);
      document.getElementById('difficultySlider').addEventListener('input', function() {{
        updateDifficulty(this.value);
      }});
      document.getElementById('validateBtn').addEventListener('click', validateToken);
      document.getElementById('copyEmbedBtn').addEventListener('click', copyEmbed);
      
      // Mode buttons
      document.querySelectorAll('.mode-btn').forEach(function(btn) {{
        btn.addEventListener('click', function() {{
          setMode(this.dataset.mode);
        }});
      }});
    }}
    
    // Wait for both DOM and widget.js to be ready
    if (document.readyState === 'loading') {{
      document.addEventListener('DOMContentLoaded', function() {{
        setupEventListeners();
        initTheme();
      }});
    }} else {{
      setupEventListeners();
      initTheme();
    }}
  </script>
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
