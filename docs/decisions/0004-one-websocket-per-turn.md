# 0004 — One WebSocket per turn, no server-side conversation state

**Status:** accepted · 2026-10

## Context

A turn needs bidirectional streaming: audio up while the visitor speaks, captions,
reply sentences, audio and lipsync frames down. The alternatives are one long-lived
socket per visit, or a socket per turn.

## Decision

One socket per turn. The browser opens it, sends audio or text, receives the answer,
and the server closes it. The browser sends whatever conversation history it wants
considered, with every turn. The server keeps nothing between sockets.

## Considered

**A long-lived socket with server-side session state.** Rejected. It needs session
identity, expiry, and a decision about what happens when a visitor walks away
mid-sentence — all of which is state to get wrong, in a lobby where people leave
constantly. A socket per turn makes abandonment free: the socket closes and everything
tied to it is already gone.

**HTTP with polling or server-sent events.** Rejected: no clean path for streaming
audio up.

## Consequences

- Nothing about a visitor outlives their turn. There is no session store, no expiry,
  and nothing to clear between visitors — which is also the privacy answer.
- The browser owns the conversation. It can trim or clear history, and the server
  caps what it will accept.
- A new socket per turn costs a handshake. On a LAN this is immaterial.
- Two turns can overlap while the previous one's lipsync frames drain, so the
  Audio2Face stream pool is process-wide rather than per turn.
