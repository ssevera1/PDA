# PDAgent — Personal Digital Agent

An AI-powered personal assistant that handles your phone calls via Twilio using Claude, Grok, or Gemini, and notifies you via Telegram.

**Your phone rings → Twilio forwards the call → Sophie (the AI) picks up → She helps the caller → You get a Telegram notification with a full summary.**

---

## Table of Contents

- [How It Works](#how-it-works)
- [Architecture](#architecture)
- [Prerequisites](#prerequisites)
- [Setup Guide](#setup-guide)
  - [1. Clone & Install](#1-clone--install)
  - [2. LLM Provider](#2-llm-provider-choose-one)
  - [3. Twilio](#3-twilio)
  - [4. Telegram Notifications](#4-telegram-notifications)
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

1. Someone calls your real phone number
2. Your carrier forwards the call to your Twilio number
3. Twilio hits your server's `/voice/incoming` webhook
4. Sophie greets the caller and begins a conversation via TwiML `<Say>` + `<Gather>`
5. Each time the caller speaks, Twilio transcribes it and sends it to `/voice/gather`
6. The LLM generates a response, which Twilio speaks back to the caller
7. When the call ends (naturally or via hangup), the LLM summarizes the conversation
8. You receive a Telegram notification with the full call report

---

## Architecture

```
┌──────────────┐     ┌──────────────────────────────┐
│  Caller's    │────▶│   Twilio                      │
│  Phone       │◀────│   (Voice Platform)             │
└──────────────┘     └──────────┬───────────────────┘
                                │ TwiML Webhooks
                     ┌──────────▼───────────────────┐
                     │   PDAgent (FastAPI)           │
                     │                               │
                     │  ┌─────────────┐              │
                     │  │ Twilio      │              │
                     │  │ Webhook     │              │
                     │  │ Handler     │              │
                     │  └──────┬──────┘              │
                     │         │                     │
                     │  ┌──────▼──────┐              │
                     │  │  LLM Brain  │              │
                     │  │ Claude/Grok │              │
                     │  │  /Gemini    │              │
                     │  └──────┬──────┘              │
                     │         │                     │
                     │  ┌──────▼──────┐              │
                     │  │ Dispatcher  │              │
                     │  └──┬───────┬──┘              │
                     │     │       │                  │
                     └─────│───────│──────────────────┘
                           │       │
              ┌────────────┘       └────────────┐
              ▼                                 ▼
        ┌──────────┐                     ┌───────────┐
        │  JSONL   │                     │ Telegram  │
        │  History │                     │ Bot API   │
        │  (Disk)  │                     │  (You)    │
        └──────────┘                     └───────────┘
```

**Tech Stack:**
| Component | Technology | Purpose |
|-----------|-----------|---------|
| Web Framework | FastAPI (Python) | TwiML webhook server |
| AI Engine | Claude / Grok / Gemini (configurable) | Conversation & summarization |
| Voice Platform | Twilio | Phone call handling, speech recognition & synthesis |
| Notifications | Telegram Bot API | Call reports to you |
| Persistence | JSONL file | Call history |

---

## Prerequisites

- **Python 3.11+**
- **LLM API key** — one of: Anthropic (Claude), xAI (Grok), or Google (Gemini)
- **Twilio account** — with a phone number and voice webhooks configured
- **Telegram bot** — for receiving call notifications
- **Public URL** — your server must be reachable by Twilio (use ngrok for local dev)

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

### 3. Twilio

1. Sign up at [twilio.com](https://www.twilio.com/) and get a phone number
2. In the Twilio Console, go to your phone number's configuration
3. Under **Voice & Fax**, set:
   - **A call comes in**: Webhook → `https://your-domain/voice/incoming` (HTTP POST)
   - **Status callback URL**: `https://your-domain/voice/status` (HTTP POST)
4. Copy your **Account SID** and **Auth Token** from the Twilio dashboard
5. Save them in your `.env`:
   ```
   TWILIO_ACCOUNT_SID=ACxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
   TWILIO_AUTH_TOKEN=your-auth-token
   TWILIO_PHONE_NUMBER=+15551234567
   ```
6. Set up call forwarding on your real phone number to forward to your Twilio number

### 4. Telegram Notifications

1. Open Telegram and message [@BotFather](https://t.me/BotFather)
2. Send `/newbot` and follow the prompts to create a bot
3. Copy the bot token (looks like `123456789:ABCdefGHI...`)
4. Send any message to your new bot
5. Get your chat ID by visiting `https://api.telegram.org/bot<YOUR_TOKEN>/getUpdates`
6. Save both in your `.env`:
   ```
   TELEGRAM_BOT_TOKEN=123456789:ABCdefGHIjklMNOpqrsTUVwxyz
   TELEGRAM_CHAT_ID=123456789
   ```

### 5. Configure Environment

```bash
cp .env.example .env
```

Edit `.env` with your values:

```env
LLM_PROVIDER=claude
ANTHROPIC_API_KEY=sk-ant-your-key-here

# Twilio (required)
TWILIO_ACCOUNT_SID=ACxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
TWILIO_AUTH_TOKEN=your-auth-token
TWILIO_PHONE_NUMBER=+15551234567

# Telegram notifications
TELEGRAM_BOT_TOKEN=123456789:ABCdefGHIjklMNOpqrsTUVwxyz
TELEGRAM_CHAT_ID=123456789

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

**For local development with Twilio,** expose your server with ngrok:
```bash
ngrok http 8000
```
Then update the Twilio webhook URLs and `BASE_URL` in `.env` with the ngrok URL.

---

## Call Flow

Here's what happens during a single call, step by step:

```
1. INCOMING CALL ──────────────────────────────────────────
   Caller dials your phone number
   Carrier forwards to Twilio number
   Twilio POSTs to /voice/incoming

2. GREETING ───────────────────────────────────────────────
   LLM generates a warm greeting
   Server returns TwiML: <Say>greeting</Say><Gather>
   Twilio speaks the greeting, begins listening

3. CONVERSATION LOOP ─────────────────────────────────────
   ┌─→ Caller speaks
   │   Twilio transcribes → POSTs SpeechResult to /voice/gather
   │   LLM generates contextual response
   │   Server returns TwiML: <Say>reply</Say><Gather>
   │   Twilio speaks reply, begins listening again
   └─────────────────────────────────────────────── loop

4. CALL ENDS ──────────────────────────────────────────────
   LLM signals CALL_COMPLETE → <Say>goodbye</Say><Hangup/>
   Or turn limit reached (20 turns max)
   Or caller hangs up → Twilio POSTs to /voice/status

5. SUMMARY & NOTIFICATION ────────────────────────────────
   LLM analyzes full transcript
   Generates structured summary:
     - Caller name & number
     - Topic & details
     - Action items & urgency
   Record saved to data/call_history.jsonl
   Telegram notification sent with full report
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
| `TWILIO_ACCOUNT_SID` | No | — | Twilio Account SID |
| `TWILIO_AUTH_TOKEN` | Yes | — | Twilio Auth Token (used for signature validation) |
| `TWILIO_PHONE_NUMBER` | No | — | Your Twilio phone number |
| `TELEGRAM_BOT_TOKEN` | No | — | Telegram bot token from @BotFather |
| `TELEGRAM_CHAT_ID` | No | — | Your Telegram chat ID |
| `DATA_DIR` | No | `data` | Directory for call history persistence |
| `AGENT_NAME` | No | `Sophie` | What the agent calls herself |
| `OWNER_NAME` | No | `Boss` | How the agent refers to you |
| `BASE_URL` | No | `http://localhost:8000` | Public URL (used in TwiML action URLs) |

---

## Project Structure

```
PDAgent/
├── main.py                        # FastAPI app, routing, middleware
├── config.py                      # Environment config via pydantic-settings
├── security.py                    # Rate limiting, security headers
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
├── voice/                         # Twilio voice handling
│   └── twilio_webhook.py          # TwiML webhook endpoints
│       ├── POST /voice/incoming   #   Handle new incoming call
│       ├── POST /voice/gather     #   Process caller speech, return reply
│       └── POST /voice/status     #   Handle call completion/hangup
│
├── notifications/                 # Notification system
│   ├── telegram.py                # Telegram Bot API notifications
│   └── dispatcher.py              # JSONL persistence + notification routing
│
├── store/                         # State management
│   └── conversations.py           # In-memory call session store
│
├── data/                          # Persisted call records
│   └── call_history.jsonl         # One JSON record per completed call
│
├── test_twilio_flow.py            # Integration test suite (11 tests)
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

### Change the Voice

The TwiML voice is set in `voice/twilio_webhook.py` — currently `Polly.Joanna` (Amazon Polly via Twilio). You can change it to any [Twilio-supported voice](https://www.twilio.com/docs/voice/twiml/say#voice).

---

## Security

PDAgent includes multiple layers of security hardening:

- **Twilio signature validation** — every webhook request is verified using `X-Twilio-Signature` and your auth token
- **Concurrent call cap** — limits simultaneous calls to prevent resource exhaustion
- **Input sanitization** — caller-supplied fields are truncated and stripped of newlines
- **Security headers** — CSP (`default-src 'none'`), X-Frame-Options (DENY), X-Content-Type-Options, Referrer-Policy
- **Rate limiting** — 30 requests per minute per IP on `/voice/*` endpoints
- **Session cleanup** — background task purges stale sessions after 1 hour
- **Turn limit** — conversations capped at 20 turns to prevent runaway LLM costs

---

## Deployment

### Option A: Direct

```bash
pip install -r requirements.txt
python main.py
```

For production, use a reverse proxy (nginx/Caddy) with HTTPS in front of uvicorn. Twilio requires HTTPS for webhooks.

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
5. Point Twilio webhooks to your deployed URL

### Option D: AWS

See the **[AWS Deployment Guide](docs/AWS_DEPLOYMENT.md)** covering EC2, ECS Fargate, and Elastic Beanstalk.

### ngrok for Local Development

```bash
ngrok http 8000
```

Copy the HTTPS URL (e.g., `https://abc123.ngrok-free.app`) and:
1. Set `BASE_URL` in `.env` to the ngrok URL
2. Update Twilio webhook URLs to the ngrok URL
3. Restart the server

---

## Troubleshooting

### Twilio says "Application error"
- Check your server logs for errors
- Verify your server is reachable at the webhook URL: `curl https://your-url/health`
- Make sure `BASE_URL` in `.env` matches the URL Twilio is using
- Check that `TWILIO_AUTH_TOKEN` is correct (wrong token = 403 on every request)

### Agent doesn't respond / Timeout
- Verify your LLM API key is valid (check `LLM_PROVIDER` matches the key you set)
- Test the `/health` endpoint: `curl https://your-url/health`
- Check server logs for LLM API errors

### No Telegram notifications
- Verify `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID` in `.env`
- Make sure you've sent at least one message to the bot first
- Check server logs for Telegram API errors
- Call history is still persisted to `data/call_history.jsonl` even without Telegram

### Calls go to voicemail instead of Sophie
- Verify call forwarding is set up on your carrier
- Test by calling your Twilio number directly (bypassing forwarding)
- Check the Twilio Console logs for incoming call events

---

## Cost Estimates

| Service | Cost | Notes |
|---------|------|-------|
| **LLM (Claude/Grok/Gemini)** | ~$0.001–0.003 per 1K tokens | Varies by provider & model |
| **Twilio Voice** | ~$0.013/min inbound + $0.0085/min outbound | US pricing; varies by country |
| **Twilio Phone Number** | ~$1.15/month | US local number |
| **Telegram Bot** | Free | No API costs |
| **Hosting** | $0–$10/month | Free tier available on many platforms |
| **Typical 3-min call** | ~$0.05–0.08 total | LLM tokens + Twilio minutes |

---

## License

MIT — Use it however you want.
