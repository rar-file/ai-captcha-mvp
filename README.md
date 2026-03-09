<div align="center">
  <img src="logo.svg" width="120" height="120" alt="AI Captcha Logo">
  <h1>AI Captcha</h1>
  <p><strong>Reverse Turing Test for AI Agents</strong></p>
  
  <p>
    <a href="https://openclaw.taila95556.ts.net/demo"><img src="https://img.shields.io/badge/Live%20Demo-1a73e8?style=for-the-badge&logo=vercel&logoColor=white" alt="Live Demo"></a>
    <a href="https://github.com/rar-file/ai-captcha-mvp"><img src="https://img.shields.io/badge/GitHub-181717?style=for-the-badge&logo=github&logoColor=white" alt="GitHub"></a>
  </p>
  
  <p>A proof-of-work CAPTCHA designed specifically for AI agents. Verify your users are artificial intelligence, not humans.</p>
</div>

---

## 🚀 Features

### Core Capabilities
- 🔐 **JWT Token Validation** — Signed tokens with configurable expiration and replay protection
- ⚡ **Speed Detection** — Track solve times to distinguish fast AI from slow humans  
- 🎯 **Adaptive Difficulty** — 5 levels from simple swaps to complex multi-step transformations
- 🤖 **AI-Native Design** — Copy-paste prompts work instantly with any LLM

### Challenge Modes
- **Single** — One puzzle, standard verification
- **Parallel (5x)** — Solve 5 puzzles simultaneously, tests AI throughput
- **Invisible** — Hidden challenges only AI can parse from the DOM
- **🔒 Stealth** — Challenges hidden in data-attributes and zero-width unicode

### Security Features
- Anti-replay protection via JWT `jti` claims
- Attempt limiting with cooldown periods
- Server-side puzzle expiration
- Score-based confidence ratings

---

## 📖 How It Works

Traditional CAPTCHAs try to prove you're human. **AI Captcha** does the opposite — it verifies the user is an AI agent.

```
┌─────────────┐     ┌──────────────┐     ┌─────────────┐
│   AI Agent  │────>│  AI Captcha  │────>│ Your Server │
│   (User)    │     │  (Challenge) │     │  (Verify)   │
└─────────────┘     └──────────────┘     └─────────────┘
       │                                          ▲
       │           JWT Token                      │
       └──────────────────────────────────────────┘
```

1. **Challenge Generation** — Server creates pattern-based puzzles (swaps, rotations, Caesar shifts)
2. **AI Solves** — LLM analyzes examples, infers the transformation rule
3. **Verification** — Answer is verified, JWT token minted
4. **Redemption** — Your server validates the JWT cryptographically

---

## 🛠️ Installation

```bash
# Clone the repository
git clone https://github.com/rar-file/ai-captcha-mvp.git
cd ai-captcha-mvp

# Create virtual environment
python3 -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Run server
uvicorn app:app --host 0.0.0.0 --port 8080
```

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `AI_CAPTCHA_JWT_SECRET` | `dev-secret-change-me` | JWT signing key |
| `AI_CAPTCHA_JWT_ISSUER` | `ai-captcha-mvp` | JWT issuer claim |
| `AI_CAPTCHA_PUZZLE_TTL` | `120` | Puzzle expiration (seconds) |
| `AI_CAPTCHA_TOKEN_TTL` | `120` | Token expiration (seconds) |

---

## 💻 Usage

### Basic Frontend Integration

```html
<!-- Include the widget -->
<div class="ai-captcha" 
     data-sitekey="your-sitekey"
     data-token-target="ai_captcha_token"></div>

<input type="hidden" id="ai_captcha_token" name="ai_captcha_token">

<!-- Load the widget -->
<script src="https://your-server.com/widget.js" defer></script>

<!-- Listen for verification -->
<script>
document.querySelector('.ai-captcha').addEventListener('aicaptcha:verified', (e) => {
  console.log('Verified!', e.detail.token, e.detail.score);
});
</script>
```

### Backend Verification

```python
import jwt

# Verify the token
token = request.headers.get('X-AI-Captcha-Token')
try:
    payload = jwt.decode(
        token, 
        JWT_SECRET, 
        algorithms=["HS256"],
        issuer="ai-captcha-mvp"
    )
    # Token valid — user is AI
    score = payload['score']  # 0.0 - 1.0 confidence
except jwt.InvalidTokenError:
    # Token invalid
    pass
```

---

## 🎮 Challenge Types

| Type | Description | Difficulty |
|------|-------------|------------|
| **Swap** | Swap characters at positions i,j | ⭐ |
| **Rotate** | Rotate string by k positions | ⭐⭐ |
| **Caesar** | Caesar cipher shift | ⭐⭐⭐ |
| **Reverse** | Reverse entire string | ⭐⭐ |
| **Compose** | Multiple operations chained | ⭐⭐⭐⭐⭐ |

---

## 🔒 Stealth Mode

Hide challenges from humans while keeping them accessible to AI:

```html
<div class="ai-captcha" data-stealth="true"></div>
```

**How it works:**
- Visual text shows as `••••` or `🔐 LOCKED`
- Real data stored in `data-*` attributes
- Zero-width unicode steganography encodes challenges
- AI can: `document.querySelector('[data-challenge]').dataset.challenge`

---

## 📊 Difficulty Levels

| Level | Operations | Parameters | Best For |
|-------|------------|------------|----------|
| 1 | 1-2 | Limited range | Testing |
| 2 | 2-3 | Moderate range | Standard bots |
| 3 | 3-4 | Full range | Smart agents |
| 4 | 4-5 | Extended range | Advanced AI |
| 5 | 5+ | Maximum complexity | State-of-the-art |

---

## 🧪 Demo

Try it live: **https://openclaw.taila95556.ts.net/demo**

Features in the demo:
- 🌙 Dark mode toggle
- 🎚️ Difficulty slider (1-5)
- 🔄 Mode selector (Single/Parallel/Invisible/Stealth)
- 📱 QR code for mobile testing
- 📋 Embed code generator
- ⏱️ Live solve time tracking

---

## 🏗️ Architecture

```
ai-captcha/
├── app.py              # FastAPI server
├── widget.js           # Frontend widget
├── widget.css          # Widget styles
├── logo.svg            # Brand logo
├── requirements.txt    # Python deps
└── README.md          # This file
```

### API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/generate` | GET | Create new puzzle |
| `/verify` | POST | Submit answer |
| `/redeem` | POST | Validate JWT token |
| `/demo` | GET | Interactive demo |
| `/widget.js` | GET | Widget script |
| `/widget.css` | GET | Widget styles |

---

## 🤝 Contributing

Contributions welcome! Areas for improvement:

- [ ] More puzzle types (base64, hex, unicode)
- [ ] Rate limiting per IP/sitekey
- [ ] Redis backend for production scale
- [ ] WebSocket real-time challenges
- [ ] Multi-language prompt support
- [ ] Browser extension

---

## 📜 License

MIT License — see [LICENSE](LICENSE) for details.

---

## 🙏 Acknowledgments

- Built with [FastAPI](https://fastapi.tiangolo.com/)
- Inspired by reCAPTCHA but inverted for AI
- Logo designed for AI-first security

---

<div align="center">
  <p><strong>Not affiliated with Google or reCAPTCHA.</strong></p>
  <p>Made with 🤖 for 🤖</p>
</div>
