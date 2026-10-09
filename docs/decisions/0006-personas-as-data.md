# 0006 — Presenters are data, not code branches

**Status:** accepted · 2026-10

## Context

The kiosk offers two presenters. They differ in name, voice, Urdu grammatical gender,
which text-to-speech engines they may use, and how their rig's mouth is tuned.

That had been implemented as branches: about ten `if avatar == "male"` checks across
text to speech, Audio2Face, prompt selection, the canned replies and the routes, plus
about twenty hard-coded `"female"` defaults, and the presenter list written out in three
places. The two prompt files were 98% identical copies. Adding a third presenter meant
finding every branch.

## Decision

`server/personas.toml` describes the presenters. `server/personas.py` is the only module
that reads a presenter id. Everything else takes a `Persona` and asks it for what it
needs.

On the frontend the same rule, with the per-presenter look values in the avatar config.

Enforced: `tests/test_personas_are_data.py` fails if a presenter id appears in code
again, if the two stop defining the same fields, or if the frontend and backend stop
offering the same set. An ESLint rule does the same for the UI.

## Considered

**A class per presenter, chosen polymorphically.** Rejected as heavier than the problem:
the differences are all values, not behaviour. The one real behavioural difference —
which Urdu agreement pass a reply gets — is selected by a `grammatical_gender` field.

**Leave it and document it.** Rejected: it was already wrong in one place (the Urdu UI
status text was feminine for both presenters) precisely because the rule lived in
people's heads.

## Consequences

- Adding a presenter is a TOML table, prompt files, a frontend profile and a rig.
- Voice ids are the one seam: *which* setting holds a presenter's voice is a fact about
  the presenter, but the id itself is account-specific, so the TOML names the setting
  and the environment supplies the value.
- `personas.toml` carries measurements (the male rig's Audio2Face tuning) alongside
  configuration. That is intentional — they are facts about that presenter — and the
  measurement's provenance is in the comment beside it.
