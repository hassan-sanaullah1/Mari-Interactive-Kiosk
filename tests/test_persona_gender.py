"""MARI is a female persona, and Urdu marks gender on verbs.

Any Urdu string describing what MARI is doing — in the prompts or in the two UIs —
has to use feminine forms. Masculine is Urdu's default, so these regress easily:
a new status label written as "سن رہا ہے" reads as a male assistant.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from server import knowledge as K  # noqa: E402

# Masculine verb endings that describe the speaker/subject. Each has a feminine
# counterpart (رہا->رہی, سکتا->سکتی, تھا->تھی, رہے گا->رہے گی).
MASCULINE = ("رہا ہے", "رہا ہوں", "سکتا ہوں", "سکتا ہے", "رہا تھا", "سنتا", "رہے گا")

UI_FILES = ("frontend/lib/i18n.ts", "web/app.js")


def _urdu_strings(path: Path) -> list[str]:
    """Quoted literals in the file that contain Urdu text."""
    return [
        lit
        for lit in re.findall(r'"([^"\n]*)"', path.read_text(encoding="utf-8"))
        if re.search(r"[ؠ-ۿ]", lit)
    ]


@pytest.mark.parametrize("relpath", UI_FILES)
def test_ui_strings_use_feminine_forms(relpath: str) -> None:
    offenders = [
        s for s in _urdu_strings(ROOT / relpath) if any(m in s for m in MASCULINE)
    ]
    assert not offenders, f"masculine forms in {relpath}: {offenders}"


def test_urdu_prompt_instructs_feminine_self_reference() -> None:
    """The rule has to be stated, or the model drifts to Urdu's masculine default."""
    assert "مؤنث صیغہ" in K._RULES_UR


def test_urdu_demo_reply_is_feminine() -> None:
    from server.app import DEMO_REPLY

    assert "سکتی" in DEMO_REPLY["ur"]
    assert "سکتا" not in DEMO_REPLY["ur"]
