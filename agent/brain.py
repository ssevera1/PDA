from __future__ import annotations

import anthropic

from config import get_settings
from store.conversations import CallSession
from agent.prompts import system_prompt, SUMMARY_PROMPT


def _client() -> anthropic.Anthropic:
    return anthropic.Anthropic(api_key=get_settings().anthropic_api_key)


async def respond(session: CallSession, caller_input: str) -> str:
    """Generate a conversational response to the caller's latest input."""
    settings = get_settings()
    session.add_caller_message(caller_input)

    client = _client()
    response = client.messages.create(
        model="claude-sonnet-4-5-20250929",
        max_tokens=300,
        system=system_prompt(settings.agent_name, settings.owner_name),
        messages=session.messages,
    )

    reply = response.content[0].text
    session.add_agent_message(reply)

    # Check if agent wants to escalate
    if "CALL_COMPLETE" in reply:
        session.needs_escalation = True

    return reply


async def generate_greeting(session: CallSession) -> str:
    """Generate the initial greeting for a new call."""
    settings = get_settings()

    client = _client()
    greeting_messages = [
        {
            "role": "user",
            "content": (
                f"A caller is on the line from number {session.caller}. "
                f"Location: {session.caller_city or 'unknown'}, "
                f"{session.caller_state or 'unknown'}. "
                "Please greet them warmly and ask how you can help."
            ),
        }
    ]

    response = client.messages.create(
        model="claude-sonnet-4-5-20250929",
        max_tokens=150,
        system=system_prompt(settings.agent_name, settings.owner_name),
        messages=greeting_messages,
    )

    greeting = response.content[0].text
    # Store the greeting exchange in session history
    session.messages.extend(greeting_messages)
    session.add_agent_message(greeting)
    return greeting


async def summarize_call(session: CallSession) -> str:
    """Generate a structured summary of the completed call."""
    conversation_text = ""
    for msg in session.messages:
        role = "Caller" if msg["role"] == "user" else "Agent"
        conversation_text += f"{role}: {msg['content']}\n\n"

    client = _client()
    response = client.messages.create(
        model="claude-sonnet-4-5-20250929",
        max_tokens=500,
        system=SUMMARY_PROMPT,
        messages=[
            {
                "role": "user",
                "content": f"Here is the call transcript:\n\n{conversation_text}",
            }
        ],
    )

    summary = response.content[0].text
    session.summary = summary
    return summary
