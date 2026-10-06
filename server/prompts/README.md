# server/prompts

Everything the LLM is told, and the fixed lines spoken without it. Loaded once by
`server/prompts/__init__.py`; a missing or empty file stops the server at startup.

| File | Used for |
|---|---|
| `system/<persona>_<language>.md` | persona and rules, in every system prompt |
| `greeting/<persona>_<language>.md` | added only when `server/agent/greeting.py` says the message is a greeting |
| `core_brief.md` | short company brief, in every system prompt |
| `no_context_<language>.md` | added when retrieval found nothing |
| `query_rewriter.md` | system prompt for rewriting follow-up questions before retrieval |
| `replies.toml` | demo line (LLM unreachable), no-speech apology, and the `MARI_PITCH_ONLY` pitch |

Prompt assembly order (`server/services/generation.py`): system rules → greeting (if a
greeting turn) → core brief → glossary definitions → retrieved sections, or the
no-context instruction.

## The two personas

The browser sends which presenter is on screen with every turn (`avatar`, mirroring
`AvatarId` in `frontend/components/avatar/models.ts`). An unknown id falls back to female.

| Rig | Speaks as | Files |
|---|---|---|
| `female` | Maryam (مریم) | `*/female_*.md` |
| `male` | Hamza (حمزہ) | `*/male_*.md` |

Both present as members of the Mari Energies team (never as an AI), answer only about
Mari Energies, state only what the knowledge base contains, and speak in short sentences.
A change to that framing belongs in all four `system/*.md` files.

Urdu marks gender on the verb and the possessive, so the Urdu prompts are not a name
swap: «کر سکتی ہوں» / «کی representative» for her, «کر سکتا ہوں» / «کا representative» for him. The
model still slips, so `server/agent/reply_fixes.py` corrects agreement per turn, and
forces the salam that must open a greeting reply.

The Urdu prompts ask for the Urdu an educated Pakistani speaks today: Urdu grammar, with the
English words people actually say ("representative", "projects", "Board of Directors") kept in
Latin script, copied as the knowledge base writes them. The model copies the style it is shown,
so the Urdu prompt text itself is written that way — keep new wording plain and keep English
words in Latin.

The fixed lines in `replies.toml` never pass through the LLM or those fixes, so each
Urdu line is written per presenter.

Editing a prompt: change the file and restart the backend.
