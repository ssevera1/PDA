# PDAgent — Personal Digital Agent

An AI-powered personal assistant that handles conversations through your browser using Claude, Grok, or Gemini, and notifies you via email and a real-time dashboard.

**Visit `/call` → Sophie (the AI) picks up → She helps the caller → You get a report via email + dashboard.**

No external telephony or messaging services required — everything runs self-hosted except the LLM API.

---

## Table of Contents

- [How It Works](#how-it-works)
- [Architecture](#architecture)
- [Prerequisites](#prerequisites)
- [Setup Guide](#setup-guide)
  - [1. Clone & Install](#1-clone--install)
  - [2. LLM Provider](#2-llm-provider-choose-one)
  - [3. SMTP Email (Optional)](#3-smtp-email-optional)
  - [4. Dashboard API Key](#4-dashboard-api-key)
  - [5. Configure Environment](#5-configure-environment)
- [Running the Agent](#running-the-agent)
- [Call Flow](#call-flow)
- [Configuration Reference](#configuration-reference)
- [Project Structure](#project-structure)
- [Customization](#customization)
- [Security](#security)
- [Deployment](#deployment)
- [Troubleshooting](#troubleshooting)
- [Cost Estimates](#cost-estimates)

---

## How It Works

1. A caller visits `https://your-server/call` in their browser
2. They click "Call Sophie" — a WebSocket connection opens
3. The browser's Speech Recognition API captures their voice (or they type)
4. Sophie responds via the browser's Speech Synthesis API (or text)
5. The conversation continues until the issue is resolved or the call ends
6. When the call ends, the LLM summarizes the entire conversation
7. You receive a notification via email and the real-time dashboard at `/dashboard`

---

## Architecture

```
┌──────────────┐     ┌──────────────────────────────┐
│  Caller's    │────▶│   PDAgent (FastAPI)           │
│  Browser     │◀────│                               │
│              │ WS  │  ┌─────────────┐              │
│ SpeechRecog. │────▶│  │ WebSocket   │              │
│ SpeechSynth. │◀────│  │ Handler     │              │
└──────────────┘     │  └──────┬──────┘              │
                     │         │                     │
                     │  ┌──────▼──────┐              │
                     │  │  LLM Brain  │              │
                     │  │ Claude/Grok │              │
                     │  │  /Gemini    │              │
                     │  └──────┬──────┘              │
                     │         │                     │
                     │  ┌──────▼──────┐              │
                     │  │ Dispatcher  │              │
                     │  └──┬────┬──┬──┘              │
                     │     │    │  │                  │
                     └─────│────│──│──────────────────┘
                           │    │  │
              ┌────────────┘    │  └────────────┐
              ▼                 ▼               ▼
        ┌──────────┐    ┌────────────┐   ┌───────────┐
        │  SMTP    │    │  JSONL     │   │  SSE      │
        │  Email   │    │  History   │   │ Dashboard │
        │  (You)   │    │  (Disk)    │   │  (You)    │
        └──────────┘    └────────────┘   └───────────┘
```

**Tech Stack:**
| Component | Technology | Purpose |
|-----------|-----------|---------|
| Web Framework | FastAPI (Python) | WebSocket server + API |
| AI Engine | Claude / Grok / Gemini (configurable) | Conversation & summarization |
| Voice Input | Browser Web Speech API | Speech-to-text |
| Voice Output | Browser SpeechSynthesis API | Text-to-speech |
| Notifications | SMTP email (stdlib) + SSE dashboard | Call reports to you |
| Persistence | JSONL file | Call history |
| Fallback STT | Whisper (optional) | Server-side transcription |
| Fallback TTS | pyttsx3 (optional) | Server-side synthesis |

---

## Prerequisites

- **Python 3.11+**
- **LLM API key** — one of: Anthropic (Claude), xAI (Grok), or Google (Gemini)
- **SMTP credentials** (optional — for email notifications; Gmail, Outlook, etc.)
- A modern browser with microphone access (Chrome recommended for speech APIs)

---

## Setup Guide

### 1. Clone & Install

```bash
cd PDAgent
python -m venv venv

# Windows
venv\Scripts\activate

# macOS / Linux
source venv/bin/activate

pip install -r requirements.txt
```

### 2. LLM Provider (Choose One)

#### Option A: Claude (Anthropic) — default
1. Go to [console.anthropic.com](https://console.anthropic.com/)
2. Create an account or sign in
3. Navigate to **API Keys** → **Create Key**
4. Copy the key — it starts with `sk-ant-`
5. Save it as `ANTHROPIC_API_KEY` in your `.env`

#### Option B: Grok (xAI)
1. Go to [console.x.ai](https://console.x.ai/)
2. Create an API key
3. Save it as `XAI_API_KEY` in your `.env`
4. Set `LLM_PROVIDER=grok` in your `.env`

#### Option C: Gemini (Google)
1. Go to [aistudio.google.com](https://aistudio.google.com/)
2. Create an API key
3. Save it as `GOOGLE_API_KEY` in your `.env`
4. Set `LLM_PROVIDER=gemini` in your `.env`

### 3. SMTP Email (Optional)

If you want email notifications when calls complete:

1. Use your email provider's SMTP settings (e.g., Gmail, Outlook, Fastmail)
2. For Gmail, create an [App Password](https://myaccount.google.com/apppasswords)
3. Configure `SMTP_*` and `NOTIFICATION_EMAIL` in your `.env`

If SMTP is not configured, notifications are still available via the dashboard and persisted to `data/call_history.jsonl`.

### 4. Dashboard API Key

Generate a strong random key for dashboard access:

```bash
python -c "import secrets; print(secrets.token_urlsafe(32))"
```

Save it as `DASHBOARD_API_KEY` in your `.env`.

### 5. Configure Environment

```bash
cp .env.example .env
```

Edit `.env` with your values:

```env
LLM_PROVIDER=claude
ANTHROPIC_API_KEY=sk-ant-your-key-here

# Email notifications (optional)
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_USER=you@gmail.com
SMTP_PASSWORD=your-app-password
SMTP_FROM=you@gmail.com
NOTIFICATION_EMAIL=you@gmail.com

# Dashboard access
DASHBOARD_API_KEY=your-strong-random-key

# Agent personality
AGENT_NAME=Sophie
OWNER_NAME=Your Name
BASE_URL=https://your-domain.example.com
```

---

## Running the Agent

```bash
# Make sure your venv is active and .env is configured
python main.py
```

The server starts on `http://localhost:8000`.

**Verify it's working:**
```bash
curl http://localhost:8000/health
# {"status": "healthy"}
```

**Use it:**
- **Call Sophie:** Open `http://localhost:8000/call` in Chrome
- **View Dashboard:** Open `http://localhost:8000/dashboard` and enter your API key

---

## Call Flow

Here's what happens during a single call, step by step:

```
1. CONNECT ─────────────────────────────────────────────────
   Caller opens /call in browser → clicks "Call Sophie"
   Browser opens WebSocket → /ws/call

2. GREETING ────────────────────────────────────────────────
   LLM generates a warm greeting
   Browser speaks it via SpeechSynthesis
   Browser begins listening via SpeechRecognition

3. CONVERSATION LOOP ──────────────────────────────────────
   ┌─→ Caller speaks (or types)
   │   Browser transcribes speech → sends via WebSocket
   │   LLM generates contextual response
   │   Response sent back → browser speaks it
   │   Browser begins listening again
   └─────────────────────────────────────────────── loop

4. CALL ENDS ───────────────────────────────────────────────
   Caller clicks end, or LLM signals CALL_COMPLETE,
   or turn limit reached (20 turns max)

5. SUMMARY & NOTIFICATION ─────────────────────────────────
   LLM analyzes full transcript
   Generates structured summary:
     - Caller name & number
     - Topic & details
     - Action items & urgency
   Record saved to data/call_history.jsonl
   Email sent (if SMTP configured)
   Dashboard updated in real-time via SSE
```

---

## Configuration Reference

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `LLM_PROVIDER` | No | `claude` | LLM backend: `claude`, `grok`, or `gemini` |
| `LLM_MODEL` | No | per-provider | Override the default model |
| `ANTHROPIC_API_KEY` | If claude | — | Anthropic API key |
| `XAI_API_KEY` | If grok | — | xAI API key |
| `GOOGLE_API_KEY` | If gemini | — | Google AI API key |
| `SMTP_HOST` | No | — | SMTP server hostname |
| `SMTP_PORT` | No | `587` | SMTP port (587 for STARTTLS, 465 for SSL) |
| `SMTP_USER` | No | — | SMTP username |
| `SMTP_PASSWORD` | No | — | SMTP password / app password |
| `SMTP_FROM` | No | — | Sender email address |
| `NOTIFICATION_EMAIL` | No | — | Where to send call reports |
| `DASHBOARD_API_KEY` | Yes | — | API key for dashboard access |
| `DATA_DIR` | No | `data` | Directory for call history persistence |
| `AGENT_NAME` | No | `Sophie` | What the agent calls herself |
| `OWNER_NAME` | No | `Boss` | How the agent refers to you |
| `BASE_URL` | No | `http://localhost:8000` | Public URL (used for origin validation) |

---

## Project Structure

```
PDAgent/
├── main.py                        # FastAPI app, routing, middleware
├── config.py                      # Environment config via pydantic-settings
├── security.py                    # Rate limiting, API key auth, security headers
├── requirements.txt               # Python dependencies
├── .env.example                   # Template for environment variables
│
├── agent/                         # AI conversation engine
│   ├── llm.py                     # LLM provider abstraction layer
│   │   ├── ClaudeProvider         #   Anthropic native SDK
│   │   ├── GrokProvider           #   xAI via OpenAI-compatible API
│   │   ├── GeminiProvider         #   Google via OpenAI-compatible API
│   │   └── get_provider()         #   Factory (cached singleton)
│   ├── brain.py                   # Conversation logic (provider-agnostic)
│   │   ├── respond()              #   Generate reply to caller input
│   │   ├── generate_greeting()    #   Create initial greeting
│   │   └── summarize_call()       #   Post-call summary generation
│   └── prompts.py                 # System prompts & personality
│
├── voice/                         # Browser-based voice system
│   ├── websocket.py               # WebSocket call handler (/ws/call)
│   ├── stt.py                     # Optional Whisper STT fallback
│   └── tts.py                     # Optional pyttsx3 TTS fallback
│
├── notifications/                 # Notification system
│   ├── email.py                   # SMTP email notifications
│   ├── dashboard.py               # SSE stream + JSONL call history
│   └── dispatcher.py              # Multi-channel notification router
│
├── store/                         # State management
│   └── conversations.py           # In-memory call session store
│
├── static/                        # Web clients
│   ├── call.html                  # Caller-facing voice client
│   └── dashboard.html             # Owner's notification dashboard
│
├── data/                          # Persisted call records
│   └── call_history.jsonl         # One JSON record per completed call
│
├── test_websocket_flow.py         # Integration test suite (11 tests)
├── Dockerfile                     # Docker container config
└── Procfile                       # Cloud platform deployment
```

---

## Customization

### Change the Agent's Personality

Edit `agent/prompts.py` → `system_prompt()`. The agent's personality, rules, and behavior are all defined there. You can:

- Change her name (also update `AGENT_NAME` in `.env`)
- Adjust her tone (more formal, more casual, specific industry jargon)
- Add knowledge about your business, schedule, or services
- Add custom rules (e.g., "always ask for an email address")

### Change the AI Model

Set `LLM_MODEL` in your `.env` to override the default model for your provider:

| Provider | Default Model | Alternatives |
|----------|--------------|--------------|
| `claude` | `claude-sonnet-4-5-20250929` | `claude-opus-4-6` |
| `grok` | `grok-3-mini` | `grok-3` |
| `gemini` | `gemini-2.5-flash` | `gemini-2.5-pro` |

### Optional: Server-Side STT/TTS Fallbacks

If callers use browsers without Web Speech API support:

```bash
# Server-side speech-to-text (Whisper)
pip install openai-whisper

# Server-side text-to-speech (pyttsx3)
pip install pyttsx3
```

These are automatically available at `/api/stt/transcribe` and `/api/tts/speak` when installed.

---

## Security

PDAgent includes multiple layers of security hardening:

- **WebSocket origin validation** — only allows connections from your configured `BASE_URL`
- **Concurrent connection cap** — limits simultaneous calls to prevent resource exhaustion
- **Per-message rate limiting** — throttles speech messages to prevent LLM API abuse
- **Message length limits** — caps input at 2000 characters
- **Input sanitization** — caller-supplied fields are truncated and stripped of newlines
- **Dashboard API key auth** — timing-safe comparison via `hmac.compare_digest`
- **Security headers** — CSP, X-Frame-Options (DENY), X-Content-Type-Options, Referrer-Policy
- **Rate limiting** — 30 requests per minute per IP on `/ws/*` and `/api/*` endpoints
- **SMTP TLS enforcement** — always uses TLS with certificate verification
- **Session cleanup** — background task purges stale sessions after 1 hour
- **JSONL pagination** — history API limits response size to prevent memory exhaustion

---

## Deployment

### Option A: Direct

```bash
pip install -r requirements.txt
python main.py
```

For production, use a reverse proxy (nginx/Caddy) with HTTPS in front of uvicorn.

### Option B: Docker

```bash
docker build -t pdagent .
docker run -d --env-file .env -p 8000:8000 -v pdagent-data:/app/data pdagent
```

The `data/` directory is a Docker volume for persisting call history across restarts.

### Option C: Cloud Platforms (Railway / Render / Fly.io)

1. Push your code to GitHub
2. Connect the repo to your platform of choice
3. Set all environment variables in the platform's dashboard
4. Update `BASE_URL` to your deployed URL

### Option D: AWS

See the **[AWS Deployment Guide](docs/AWS_DEPLOYMENT.md)** covering EC2, ECS Fargate, and Elastic Beanstalk.

---

## Troubleshooting

### Browser says "Speech recognition unavailable"
- Use Chrome (best support for Web Speech API)
- The page will automatically fall back to text input mode
- For server-side fallback, install `openai-whisper`

### Agent doesn't respond / Timeout
- Check your server logs for errors
- Verify your LLM API key is valid (check `LLM_PROVIDER` matches the key you set)
- Test the `/health` endpoint: `curl https://your-url/health`

### No email notifications
- Verify SMTP settings in `.env` (host, port, credentials)
- For Gmail, use an App Password (not your regular password)
- Check server logs for SMTP errors
- Notifications are still visible on the dashboard even without email

### Dashboard shows "Invalid API key"
- Verify `DASHBOARD_API_KEY` in `.env` matches what you enter in the browser
- The key is stored in your browser's localStorage — try logging out and back in

### WebSocket connection fails
- Ensure `BASE_URL` in `.env` matches your actual server URL
- Check that your reverse proxy (if any) supports WebSocket upgrades
- For local development, `localhost` and `127.0.0.1` are always allowed

---

## Cost Estimates

| Service | Cost | Notes |
|---------|------|-------|
| **LLM (Claude/Grok/Gemini)** | ~$0.001–0.003 per 1K tokens | Varies by provider & model |
| **SMTP Email** | Free (most providers) | Gmail, Outlook, etc. |
| **Hosting** | $0–$10/month | Free tier available on many platforms |
| **Typical 3-min call** | ~$0.01–0.03 total | LLM tokens only |

---

## License

MIT — Use it however you want.
