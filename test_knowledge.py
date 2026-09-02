"""Knowledge-pack builder: grounding validation and prompt assembly."""

import pytest

from scripts.build_knowledge import validate_pack, build, BANNED
from agent.prompts import system_prompt, load_knowledge

SOURCES = {
    "cv.md": (
        "Validated $10.4M+ in HR business value across 77 research initiatives. "
        "Built three MCP servers, the largest exposing 111 tools. Cut analyst query "
        "time 70% for 1,000+ users. Data science and machine learning since 2017."
    ),
    "config/profile.yml": "compensation: target_range: $200K-250K minimum: $175K",
}

GOOD_PACK = """\
## Facts You May State
- He has worked in data science and machine learning since 2017, on two decades of analytics.
- He validated over ten point four million dollars in business value across 77 research initiatives.
- He built three Model Context Protocol servers, the largest exposing 111 tools.

## How To Talk About Compensation
- Senior leadership compensation, generally in the two hundred to two hundred fifty thousand dollar range.

## Location and Logistics
- Based in the Dallas-Fort Worth area; remote preferred, hybrid locally.

## Hard Filters
- Roles requiring a security clearance are a pass.

## Never Say
- Never name companies he is interviewing with.
"""


def test_good_pack_validates_clean():
    assert validate_pack(GOOD_PACK, SOURCES) == []


def test_banned_tenure_claim_is_rejected():
    bad = GOOD_PACK.replace("since 2017", "with nineteen years of AI experience since 2017")
    problems = validate_pack(bad, SOURCES)
    assert any("nineteen years" in p for p in problems)


def test_missing_2017_framing_is_rejected():
    bad = GOOD_PACK.replace("since 2017", "for many years")
    problems = validate_pack(bad, SOURCES)
    assert any("2017" in p for p in problems)


def test_invented_number_is_rejected():
    bad = GOOD_PACK.replace("111 tools", "111 tools serving 2 million rows")
    problems = validate_pack(bad, SOURCES)
    assert any("2" in p and "number" in p for p in problems)


def test_exclamation_and_em_dash_are_rejected():
    assert any("!" in p for p in validate_pack(GOOD_PACK.replace("a pass.", "a pass!"), SOURCES))
    assert any("—" in p for p in validate_pack(GOOD_PACK.replace("a pass.", "a pass — always."), SOURCES))
    assert "!" in BANNED


def test_missing_section_is_rejected():
    bad = GOOD_PACK.replace("## Never Say", "## Something Else")
    assert any("Never Say" in p for p in validate_pack(bad, SOURCES))


def test_build_refuses_ungrounded_llm_output(tmp_path):
    root = tmp_path
    (root / "cv.md").write_text(SOURCES["cv.md"], encoding="utf-8")
    with pytest.raises(SystemExit):
        build(llm=lambda prompt: GOOD_PACK.replace("111", "999"), root=str(root))


def test_build_accepts_grounded_output(tmp_path):
    root = tmp_path
    (root / "cv.md").write_text(SOURCES["cv.md"], encoding="utf-8")
    pack = build(llm=lambda prompt: GOOD_PACK, root=str(root))
    assert pack == GOOD_PACK


def test_system_prompt_injects_knowledge_and_has_no_gateway():
    prompt = system_prompt("Sophie", "Scott", knowledge=GOOD_PACK)
    assert "111 tools" in prompt
    assert "gateway" not in prompt.lower()
    assert "no phrase, passphrase" in prompt.lower() or "no phrase" in prompt.lower()


def test_system_prompt_without_pack_uses_safe_fallback():
    prompt = system_prompt("Sophie", "Scott", knowledge=None)
    assert "take a message" in prompt.lower()
    assert "nineteen" not in prompt.lower()


def test_load_knowledge_missing_file_is_none(tmp_path):
    assert load_knowledge(str(tmp_path / "nope.md")) is None


def test_build_trims_preamble_before_first_section(tmp_path):
    root = tmp_path
    (root / "cv.md").write_text(SOURCES["cv.md"], encoding="utf-8")
    chatty = "Sure, here is the sheet you asked for:" + "\n\n" + GOOD_PACK
    pack = build(llm=lambda prompt: chatty, root=str(root))
    assert pack.startswith("## Facts You May State")
