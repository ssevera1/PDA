# PDAgent — Personal Digital Agent

An AI-powered phone assistant that answers your calls, handles conversations intelligently using Claude, Grok, or Gemini, and sends you detailed summaries via Telegram when you're unavailable.

**Forward your calls → Sophie (the AI) picks up → She helps the caller → You get a full report on Telegram.**

---

## Table of Contents

- [How It Works](#how-it-works)
- [Architecture](#architecture)
- [Prerequisites](#prerequisites)
- [Setup Guide](#setup-guide)
  - [1. Clone & Install](#1-clone--install)
  - [2. Anthropic (Claude AI)](#2-anthropic-claude-ai)
  - [3. Twilio (Phone System)](#3-twilio-phone-system)
  - [4. Telegram (Notifications)](#4-telegram-notifications)
  - [5. Configure Environment](#5-configure-environment)
  - [6. Expose Your Server](#6-expose-your-server)
  - [7. Connect Twilio Webhooks](#7-connect-twilio-webhooks)
  - [8. Forward Your Phone](#8-forward-your-phone)
- [Running the Agent](#running-the-agent)
- [Call Flow](#call-flow)
- [Configuration Reference](#configuration-reference)
- [Project Structure](#project-structure)
- [Customization](#customization)
- [Deployment](#deployment)
- [Troubleshooting](#troubleshooting)
- [Cost Estimates](#cost-estimates)

---

## How It Works

1. You forward your phone to your Twilio number (or set it as a fallback)
2. When someone calls, Twilio routes it to your PDAgent server
3. The agent greets the caller with a warm, natural voice
4. The caller speaks → Twilio transcribes → Claude generates a response → Twilio speaks it back
5. This loop continues until the issue is resolved or the call ends
6. When the call ends, Claude summarizes the entire conversation
7. You receive a structured report on Telegram with: caller info, topic, details, action items, and urgency level

---

## Architecture

```
┌──────────────┐     ┌─────────────┐     ┌──────────────────┐
│  Caller's    │────▶│   Twilio    │────▶│   PDAgent        │
│  Phone       │◀────│   (Voice)   │◀────│   (FastAPI)      │
└──────────────┘     └─────────────┘     │                  │
                      Speech-to-Text ──▶ │  ┌────────────┐  │
                      Text-to-Speech ◀── │  │ Claude AI  │  │
                                         │  │ (Brain)    │  │
                                         │  └────────────┘  │
                                         │        │         │
                                         │  ┌────────────┐  │     ┌──────────┐
                                         │  │ Notifier   │──│────▶│ Telegram │
                                         │  └────────────┘  │     │ (You)    │
                                         └──────────────────┘     └──────────┘
```

**Tech Stack:**
| Component | Technology | Purpose |
|-----------|-----------|---------|
| Web Framework | FastAPI (Python) | Webhook server for Twilio |
| AI Engine | Claude / Grok / Gemini (configurable) | Conversation & summarization |
| Telephony | Twilio Programmable Voice | Call handling, STT, TTS |
| Notifications | Telegram Bot API | Sending call reports to you |
| TTS Voice | AWS Polly (via Twilio) | Natural-sounding speech |

---

## Prerequisites

- **Python 3.11+**
- **Twilio account** (free trial works for testing)
- **LLM API key** — one of: Anthropic (Claude), xAI (Grok), or Google (Gemini)
- **Telegram account** (for receiving notifications)
- **ngrok** (for local development) or a server with a public URL

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

### 3. Twilio (Phone System)

1. Sign up at [twilio.com](https://www.twilio.com/)
2. From the Console Dashboard, note your:
   - **Account SID** (starts with `AC`)
   - **Auth Token**
3. Go to **Phone Numbers** → **Buy a Number**
   - Pick a number with **Voice** capability
   - Note the phone number (e.g., `+12025551234`)
4. Save these as `TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN`, and `TWILIO_PHONE_NUMBER` in your `.env`

> **Trial accounts:** Twilio trial accounts can only call/receive calls from verified numbers. Add your personal number under **Verified Caller IDs** for testing.

### 4. Telegram (Notifications)

#### Create a Bot

1. Open Telegram and search for **@BotFather**
2. Send `/newbot`
3. Follow the prompts — give it a name like "My Call Agent"
4. BotFather gives you a **bot token** — save it as `TELEGRAM_BOT_TOKEN`

#### Get Your Chat ID

1. Start a conversation with your new bot (send it any message like `/start`)
2. Open this URL in your browser (replace `YOUR_BOT_TOKEN`):
   ```
   https://api.telegram.org/botYOUR_BOT_TOKEN/getUpdates
   ```
3. Find `"chat":{"id":123456789}` in the JSON response
4. Save that number as `TELEGRAM_CHAT_ID`

> **Tip:** If the response is empty, send another message to the bot and refresh.

### 5. Configure Environment

```bash
cp .env.example .env
```

Edit `.env` with your values:

```env
LLM_PROVIDER=claude
ANTHROPIC_API_KEY=sk-ant-your-key-here
# XAI_API_KEY=xai-your-key-here        # for Grok
# GOOGLE_API_KEY=AIza-your-key-here     # for Gemini
TWILIO_ACCOUNT_SID=ACxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
TWILIO_AUTH_TOKEN=your-auth-token
TWILIO_PHONE_NUMBER=+12025551234
TELEGRAM_BOT_TOKEN=123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11
TELEGRAM_CHAT_ID=123456789
AGENT_NAME=Sophie
OWNER_NAME=Your Name
BASE_URL=https://your-subdomain.ngrok-free.app
```

### 6. Expose Your Server

For local development, use ngrok to create a public URL:

```bash
# Install ngrok: https://ngrok.com/download
ngrok http 8000
```

Note the `https://xxxx.ngrok-free.app` URL — this is your `BASE_URL`.

### 7. Connect Twilio Webhooks

1. Go to [Twilio Console](https://console.twilio.com/) → **Phone Numbers** → click your number
2. Under **Voice Configuration**:
   - **A call comes in:** Webhook → `https://your-url.ngrok-free.app/voice/incoming` → HTTP POST
   - **Call status changes:** `https://your-url.ngrok-free.app/voice/status` → HTTP POST
3. Click **Save configuration**

### 8. Forward Your Phone

Set up call forwarding on your personal phone to your Twilio number:

| Carrier | How to Forward |
|---------|---------------|
| **iPhone** | Settings → Phone → Call Forwarding → Enter Twilio number |
| **Android** | Phone app → Settings → Calls → Call Forwarding |
| **AT&T** | Dial `*21*[Twilio number]#` |
| **T-Mobile** | Dial `**21*[Twilio number]#` |
| **Verizon** | Dial `*72` then Twilio number |

> **Tip:** Most carriers support conditional forwarding — forward only when busy or unanswered, so you can still take calls yourself when available.

---

## Running the Agent

```bash
# Make sure your venv is active and .env is configured
python main.py
```

The server starts on `http://localhost:8000`. With ngrok running, calls to your Twilio number will be handled by the agent.

**Verify it's working:**
```bash
curl http://localhost:8000/health
# {"status": "healthy"}
```

---

## Call Flow

Here's what happens during a single call, step by step:

```
1. RING ──────────────────────────────────────────────────────
   Caller dials your number → forwarded to Twilio number
   Twilio POST → /voice/incoming

2. GREETING ──────────────────────────────────────────────────
   Claude generates a warm greeting
   Twilio speaks it via TTS (Polly.Joanna voice)
   Twilio begins listening for caller speech (Gather)

3. CONVERSATION LOOP ────────────────────────────────────────
   ┌─→ Caller speaks
   │   Twilio STT transcribes speech
   │   POST → /voice/respond with SpeechResult
   │   Claude generates contextual response
   │   Twilio speaks response via TTS
   │   Twilio begins listening again
   └─────────────────────────────────────────────────── loop

4. CALL ENDS ─────────────────────────────────────────────────
   Caller hangs up, or Claude signals CALL_COMPLETE
   Twilio POST → /voice/status (CallStatus: completed)

5. SUMMARY & NOTIFICATION ───────────────────────────────────
   Claude analyzes full transcript
   Generates structured summary:
     - Caller name & number
     - Topic & details
     - Action items & urgency
   Summary sent to you via Telegram
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
| `TWILIO_ACCOUNT_SID` | Yes | — | Twilio Account SID |
| `TWILIO_AUTH_TOKEN` | Yes | — | Twilio Auth Token |
| `TWILIO_PHONE_NUMBER` | Yes | — | Your Twilio phone number |
| `TELEGRAM_BOT_TOKEN` | Yes | — | Telegram bot token from BotFather |
| `TELEGRAM_CHAT_ID` | Yes | — | Your Telegram chat ID |
| `AGENT_NAME` | No | Sophie | What the agent calls herself |
| `OWNER_NAME` | No | Boss | How the agent refers to you |
| `BASE_URL` | No | http://localhost:8000 | Public URL for webhooks |

---

## Project Structure

```
PDAgent/
├── main.py                     # FastAPI application entry point
├── config.py                   # Environment config via pydantic-settings
├── requirements.txt            # Python dependencies
├── .env.example                # Template for environment variables
│
├── agent/                      # AI conversation engine
│   ├── llm.py                  # LLM provider abstraction layer
│   │   ├── ClaudeProvider      # Anthropic native SDK
│   │   ├── GrokProvider        # xAI via OpenAI-compatible API
│   │   ├── GeminiProvider      # Google via OpenAI-compatible API
│   │   └── get_provider()      # Factory (cached singleton)
│   ├── brain.py                # Conversation logic (provider-agnostic)
│   │   ├── respond()           # Generate reply to caller input
│   │   ├── generate_greeting() # Create initial greeting
│   │   └── summarize_call()    # Post-call summary generation
│   └── prompts.py              # System prompts & personality
│       ├── system_prompt()     # Agent personality & rules
│       └── SUMMARY_PROMPT      # Call summary format
│
├── telephony/                  # Twilio call handling
│   └── handlers.py             # Webhook endpoints
│       ├── /voice/incoming     # New call handler
│       ├── /voice/respond      # Conversation turn handler
│       └── /voice/status       # Call completion handler
│
├── notifications/              # User notification system
│   └── telegram.py             # Telegram bot messaging
│       ├── send_call_summary() # Formatted call report
│       └── send_urgent_alert() # High-priority notifications
│
└── store/                      # State management
    └── conversations.py        # In-memory call session store
        ├── CallSession          # Per-call data model
        └── ConversationStore    # Session CRUD operations
```

---

## Customization

### Change the Agent's Personality

Edit `agent/prompts.py` → `system_prompt()`. The agent's personality, rules, and behavior are all defined there. You can:

- Change her name (also update `AGENT_NAME` in `.env`)
- Adjust her tone (more formal, more casual, specific industry jargon)
- Add knowledge about your business, schedule, or services
- Add custom rules (e.g., "always ask for an email address")

### Change the Voice

Edit `telephony/handlers.py` → change the `VOICE` constant. Available Twilio voices:

| Voice | Description |
|-------|-------------|
| `Polly.Joanna` | US English, female (default) |
| `Polly.Matthew` | US English, male |
| `Polly.Amy` | British English, female |
| `Polly.Brian` | British English, male |
| `Polly.Lucia` | Spanish, female |

Full list: [Twilio TTS Voices](https://www.twilio.com/docs/voice/twiml/say/text-speech#polly-standard-and-neural-voices)

### Change the AI Model

Set `LLM_MODEL` in your `.env` to override the default model for your provider:

| Provider | Default Model | Alternatives |
|----------|--------------|--------------|
| `claude` | `claude-sonnet-4-5-20250929` | `claude-opus-4-6` |
| `grok` | `grok-3-mini` | `grok-3` |
| `gemini` | `gemini-2.5-flash` | `gemini-2.5-pro` |

### Add SMS Notifications (Alternative to Telegram)

You already have Twilio — you can send SMS with a few lines. Add to `notifications/`:

```python
from twilio.rest import Client
from config import get_settings

def send_sms(body: str, to: str):
    s = get_settings()
    client = Client(s.twilio_account_sid, s.twilio_auth_token)
    client.messages.create(body=body, from_=s.twilio_phone_number, to=to)
```

---

## Deployment

### Option A: AWS (Recommended for Production)

See the **[full AWS Deployment Guide](docs/AWS_DEPLOYMENT.md)** covering three options:

- **EC2** — Simple single-server setup (~$9/mo)
- **ECS Fargate** — Serverless containers, zero server management (~$26/mo)
- **Elastic Beanstalk** — PaaS-style quick deploy (~$9/mo)

The guide includes step-by-step instructions for networking, SSL, secrets management, monitoring, and CI/CD.

### Option B: Railway / Render / Fly.io

These platforms handle HTTPS and persistent hosting for you:

1. Push your code to GitHub
2. Connect the repo to your platform of choice
3. Set all environment variables in the platform's dashboard
4. Update `BASE_URL` to your deployed URL
5. Update Twilio webhooks to point to the deployed URL

### Option C: Docker (Any Host)

A `Dockerfile` is included in the repo:

```bash
docker build -t pdagent .
docker run -d --env-file .env -p 8000:8000 pdagent
```

---

## Troubleshooting

### "No speech detected" / Caller can't be heard
- Check Twilio's call logs in the Console → Monitor → Calls
- Ensure your Twilio number has Voice capability enabled
- Check that the `speech_timeout` setting is reasonable

### Agent doesn't respond / Timeout
- Check your server logs for errors
- Verify your LLM API key is valid (check `LLM_PROVIDER` matches the key you set)
- Ensure ngrok is running and the URL matches Twilio webhooks
- Test the `/health` endpoint: `curl https://your-url/health`

### No Telegram notifications
- Make sure you messaged your bot first (it can't initiate chats)
- Verify `TELEGRAM_CHAT_ID` is correct — use the `getUpdates` API to double-check
- Check server logs for Telegram API errors

### Twilio returns an error
- Check that all webhook URLs use HTTPS (ngrok provides this)
- Verify webhook paths are correct: `/voice/incoming` and `/voice/status`
- Look at Twilio's Error Logs in the Console for specific error codes

### Call quality is poor
- Use a stable internet connection (ngrok can introduce latency)
- For production, deploy to a region close to your Twilio number
- Consider upgrading to Twilio's Enhanced Speech Recognition

---

## Cost Estimates

| Service | Cost | Notes |
|---------|------|-------|
| **Twilio Voice** | ~$0.014/min inbound | Per-minute billing |
| **Twilio Phone Number** | ~$1.15/month | Monthly number rental |
| **LLM (Claude/Grok/Gemini)** | ~$0.001–0.003 per 1K tokens | Varies by provider & model |
| **Telegram** | Free | No API costs |
| **Typical 3-min call** | ~$0.05–0.08 total | All services combined |

---

## License

MIT — Use it however you want.
