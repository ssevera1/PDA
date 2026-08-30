# PDAgent v4 — Voice Overhaul Design

Approved by Scott 2026-08-30 ("go build that"). Decisions locked: Grok speech-to-speech
for the live loop with Claude for everything offline; Google Calendar free/busy
scheduling; the Gateway passphrase removed outright; runs on Scott's PC behind a
tunnel.

## Goal

Sophie answers calls from recruiters when Scott is busy, screens the opportunity
against his real profile, offers and holds real interview slots from his Google
Calendar, keeps him informed on Telegram while the call is still going, and writes a
structured record afterward that the career-ops pipeline can consume. Turn latency
stays at speech-to-speech levels; no scripted, laggy IVR feel.

## Architecture

```
Carrier forward -> Twilio number -> POST /voice/incoming  (signature-checked)
    -> TwiML <Connect><Stream url=wss://HOST/voice/media-stream?t=TOKEN>
    -> XAIVoiceBridge  <->  wss://api.x.ai/v1/realtime  model=grok-voice-latest
           |  in-call tools (executed in the bridge):
           |    end_call, get_availability, book_tentative,
           |    notify_owner, lookup_opportunity
           v
    on call end: Claude (Opus 5) structured extract -> Telegram report
                 -> data/call-log.jsonl -> career-ops agent-inbox note
```

- **Voice engine:** `grok-voice-latest` (voice-think-fast-2.0 as of Aug 2026,
  $0.08/min). The bridge keeps server VAD, barge-in (`clear` on
  `speech_started`), u-law passthrough, and adds the current
  `conversation.item.input_audio_transcription.updated` cumulative-transcript
  events alongside the legacy names.
- **Claude (Opus 5, SDK >= 1.x):** builds the knowledge pack offline, produces the
  post-call structured extract and summary. Never in the live audio path.
- **Anthropic has no realtime speech API** (verified Aug 2026); a Claude live loop
  would be a ConversationRelay pipeline at 600-900 ms/turn. Rejected for now;
  revisit only if screening judgment on calls proves inadequate.

## Knowledge pack (grounding)

`scripts/build_knowledge.py` compiles `data/knowledge.md` with Claude from
career-ops sources (`cv.md`, `config/profile.yml`, `modes/_profile.md`; root
configurable as `career_ops_root`). Contents: speakable work-history facts with
numbers verbatim from cv.md, the ML-tenure framing ("data science and machine
learning since 2017, on two decades of analytics"), what Sophie may say about
compensation expectations, hard filters (clearance, non-DFW onsite, non-US), and a
never-disclose list. The system prompt becomes persona + rules and injects the pack
at session start. Hand-written resume claims in `prompts.py` are deleted; the
"nineteen years of AI/ML" claim dies with them. `data/` stays gitignored (the repo
is public).

## In-call tools

| Tool | Effect |
|---|---|
| `end_call` | unchanged |
| `get_availability(days_ahead)` | Google Calendar free/busy -> up to 3 open slots, CT, rules from config (work window, evening window, 30-min buffer, 30-min slots, no weekends) |
| `book_tentative(start_iso, name, company, phone, email, topic)` | tentative "HOLD:" event with details in the description + Telegram notice. Scott confirms or deletes the event natively in Google Calendar; v1 has NO Telegram buttons because the bot token is shared with the Indeed approval loop's getUpdates poller, and a webhook or second poller on the same bot would 409 it. A dedicated bot with buttons is future work. |
| `notify_owner(urgency, text)` | live Telegram message while the call is in progress |
| `lookup_opportunity(company_or_recruiter)` | read-only fuzzy match against career-ops `data/applications.md` and `data/indeed-threads.json`: "Scott replied to that thread yesterday" |

Tool failures return an error result to the model (never crash the bridge); the
model is instructed to carry on gracefully without the tool.

## Scheduling rules (`agent/scheduling.py`, pure)

Configurable: timezone America/Chicago; bookable Mon-Fri 09:00-17:30 plus optional
17:30-20:00 evening window; 30-minute slots on the half hour; 30-minute buffer
around existing events; earliest offer 24h out; horizon 5 business days; at most 3
offers per call. Free/busy comes in; slot list comes out. Fully unit-tested.

## Post-call

`agent/brain.py` keeps only `summarize_call`, rewritten: Claude Opus 5 structured
extract {caller_type, name, company, role, comp, location_policy, urgency,
callback, email, requested_slot, red_flags, summary} + the Telegram report.
Appends one JSON line to `data/call-log.jsonl`. For recruiter calls it also appends
a checklist item to career-ops `data/agent-inbox.md` so the next career-ops session
triages it. The dead v2 webhook conversation path (`respond`, `generate_greeting`)
is removed with its tests; README updated to v3/v4 reality.

## Security

- Gateway Mode deleted. No spoken phrase changes Sophie's rules.
- Twilio signature validation and rate limiting stay.
- `/voice/media-stream` requires a single-use token minted by `/voice/incoming`
  (stream URL query param, expires in 60s, consumed on connect).
- Google OAuth refresh token + client secret live in `.env`/`data/` (gitignored);
  scopes: calendar.freebusy + calendar.events on the primary calendar.

## Runtime on this PC

`scripts/launch.ps1`: start ngrok (already installed) -> read the public URL from
the local ngrok API -> update the Twilio number's Voice URL via the Twilio REST API
-> export BASE_URL -> start uvicorn. Random free-tier ngrok URLs stop mattering
because every launch re-points Twilio. Registered as a logon scheduled task;
health endpoint pinged by the script with a Telegram alert on failure. cloudflared
named tunnel documented as the upgrade path (needs a domain on Cloudflare).

## Testing

- `agent/scheduling.py`: slot rules against synthetic busy lists (unit).
- Bridge: fake xAI + fake Twilio websockets; tool round-trip, transcript events
  (updated + legacy), barge-in clear, end_call flow, tool-crash containment.
- Calendar: fake Google client; freebusy parsing, event creation payload.
- Knowledge builder: injectable LLM; grounding checks (no numbers absent from
  cv.md; banned phrases; ML-tenure rule).
- Config: validators (xAI key now required; Google creds only when scheduling on).
- Live: one scripted test call from Scott's phone before real forwarding.

## Out of scope (v1)

Outbound dialing, voicemail, Telegram confirm buttons (shared-bot conflict),
mid-call Claude consultations, multi-calendar support.

## Scott-side setup (collected at the end)

xAI API key; one-time Google OAuth consent (script provided); ngrok authtoken if
not already configured; one test call.
