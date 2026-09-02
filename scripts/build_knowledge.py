"""Compile Sophie's knowledge pack from the career-ops sources.

Reads cv.md, config/profile.yml, and modes/_profile.md from the career-ops
checkout, has Claude compile a speakable fact sheet, validates the result
against the sources (every number must appear in them; banned phrasings are
rejected), and only then writes ``data/knowledge.md``. A pack that fails
validation is never written — Sophie falls back to a minimal safe stub and
takes messages instead of improvising facts.

Usage:  venv/Scripts/python scripts/build_knowledge.py [--print]
"""

from __future__ import annotations

import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import get_settings  # noqa: E402

BANNED = [
    "★",  # decoration from a chatty wrapper, never speakable content
    "nineteen years",
    "19 years",
    "twenty years of ai",
    "20 years of ai",
    "!",
    "—",  # em dash — spoken-aloud text should not carry written tells either
]

MODEL = "claude-opus-5"

INSTRUCTIONS = """\
You are compiling a fact sheet for a voice assistant that answers phone calls from \
recruiters on behalf of the person described in the source documents below. Everything \
you write will be spoken aloud by the assistant, so write plain, speakable prose bullets.

Produce EXACTLY these five markdown sections:

## Facts You May State
8-12 bullets covering: current role and scope, machine learning tenure (he has worked in \
data science and machine learning since twenty seventeen, on a foundation of two decades \
of analytics — use that framing, never a larger ML number), the strongest quantified \
achievements, platform and leadership credentials, and education. Spell out numbers as \
words where natural for speech, but keep each figure faithful to the sources.

## How To Talk About Compensation
2-3 bullets: what the assistant may say about expectations, phrased as a range in words, \
grounded in the compensation targets in the sources. The assistant asks for the caller's \
range first and never states a walk-away number.

## Location and Logistics
2-3 bullets: where he is based, remote and hybrid preferences, work authorization.

## Hard Filters
Bullets for opportunity types the assistant should politely decline on his behalf, from \
the sources (for example security-clearance-required roles, mandatory relocation or \
on-site outside his metro area, roles far below his level).

## Never Say
Bullets for what must not be disclosed: specific companies in play, exact walk-away \
numbers, personal details beyond the professional facts above, and anything not present \
in the sources.

HARD RULES: every quantified claim must appear in the sources verbatim or as an exact \
spelled-out equivalent; do not add, round, or combine numbers. No exclamation marks, no \
em dashes, no markdown beyond the section headers and bullets.
"""


def _read(path: str) -> str:
    with open(path, encoding="utf-8") as fh:
        return fh.read()


def gather_sources(root: str) -> dict[str, str]:
    sources = {}
    for rel in ("cv.md", "config/profile.yml", "modes/_profile.md"):
        path = os.path.join(root, rel)
        if os.path.exists(path):
            sources[rel] = _read(path)
    if "cv.md" not in sources:
        raise SystemExit(f"cv.md not found under {root} — cannot ground a knowledge pack")
    return sources


_NUM_RE = re.compile(r"\d[\d,.]*")
_WORD_NUMS = {
    "one": "1", "two": "2", "three": "3", "four": "4", "five": "5", "six": "6",
    "seven": "7", "eight": "8", "nine": "9", "ten": "10", "eleven": "11",
    "twelve": "12", "twenty": "20", "thirty": "30", "forty": "40", "fifty": "50",
    "sixty": "60", "seventy": "70", "eighty": "80", "ninety": "90",
    "hundred": "100", "thousand": "000", "million": "million", "billion": "billion",
}


def validate_pack(pack: str, sources: dict[str, str]) -> list[str]:
    """Problems found in the pack; empty means grounded and clean."""
    problems = []
    lower = pack.lower()
    for phrase in BANNED:
        if phrase.lower() in lower:
            problems.append(f"banned phrasing present: {phrase!r}")
    if "2017" not in pack and "twenty seventeen" not in lower:
        problems.append("the since-2017 ML tenure framing is missing")

    source_digits = set(_NUM_RE.findall(" ".join(sources.values())))
    source_blob = re.sub(r"[,\s]", "", " ".join(sources.values()))
    for num in _NUM_RE.findall(pack):
        canon = num.rstrip(".,")
        if canon in {"2017"}:
            continue
        if canon in source_digits:
            continue
        # Substring fallback covers formatting drift ("1,000" vs "1000") but is
        # too lax for 1-2 digit numbers ("2" matches inside "2017"), so gate it.
        if len(canon) >= 3 and re.sub(r"[,]", "", canon) in source_blob:
            continue
        problems.append(f"number {canon!r} does not appear in the sources")
    for section in ("## Facts You May State", "## How To Talk About Compensation",
                    "## Location and Logistics", "## Hard Filters", "## Never Say"):
        if section not in pack:
            problems.append(f"missing section: {section}")
    return problems


def _claude_cli(prompt: str) -> str:
    """Fallback builder: the logged-in Claude Code CLI, no API key needed."""
    import subprocess

    r = subprocess.run(
        ["claude", "-p", "--output-format", "text", "--model", MODEL],
        input=prompt, capture_output=True, text=True, timeout=300, shell=False, encoding="utf-8",
    )
    if r.returncode != 0:
        raise SystemExit(f"claude -p failed ({r.returncode}): {(r.stderr or '')[:300]}")
    return (r.stdout or "").strip()


def _claude(prompt: str) -> str:
    import anthropic

    key = get_settings().anthropic_api_key
    if key:
        try:
            client = anthropic.Anthropic(api_key=key)
            response = client.messages.create(
                model=MODEL,
                max_tokens=4000,
                messages=[{"role": "user", "content": prompt}],
            )
            return "".join(b.text for b in response.content if getattr(b, "type", "") == "text").strip()
        except anthropic.AuthenticationError:
            print("ANTHROPIC_API_KEY rejected; falling back to the claude CLI")
    return _claude_cli(prompt)


def build(llm=None, root: str | None = None) -> str:
    settings = get_settings()
    root = root or settings.career_ops_root
    sources = gather_sources(root)
    prompt = INSTRUCTIONS + "\n\n" + "\n\n".join(
        f"===== SOURCE: {name} =====\n{text}" for name, text in sources.items()
    )
    pack = (llm or _claude)(prompt)
    # A chatty model (or CLI wrapper) may preface the sheet with prose; the
    # pack begins at its first required section, everything before it is noise.
    idx = pack.find("## Facts You May State")
    if idx > 0:
        pack = pack[idx:]
    problems = validate_pack(pack, sources)
    if problems:
        raise SystemExit("knowledge pack failed validation:\n  - " + "\n  - ".join(problems))
    return pack


def main() -> None:
    settings = get_settings()
    pack = build()
    out = settings.knowledge_path
    os.makedirs(os.path.dirname(out) or ".", exist_ok=True)
    with open(out, "w", encoding="utf-8") as fh:
        fh.write(pack + "\n")
    print(f"knowledge pack written -> {out} ({len(pack)} chars)")
    if "--print" in sys.argv:
        print("\n" + pack)


if __name__ == "__main__":
    main()
