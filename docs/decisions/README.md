# Decision records

One file per structural decision: what was decided, what else was considered, and what
it costs. Short on purpose.

These exist because this codebase was built across many sessions, and a decision whose
reasoning is not written down gets quietly undone by the next person who finds it
inconvenient. If you are about to reverse one of these, add a new record superseding it
rather than editing it — the old reasoning is the useful part.

Format: [MADR](https://adr.github.io/madr/), trimmed.

| # | Decision |
|---|---|
| [0001](0001-modular-monolith.md) | One backend process, not microservices |
| [0002](0002-borrow-pipecats-shape-not-pipecat.md) | Borrow Pipecat's structure, don't depend on Pipecat |
| [0003](0003-ports-and-adapters-for-vendors.md) | Every speech and LLM vendor behind a Protocol |
| [0004](0004-one-websocket-per-turn.md) | One WebSocket per turn, no server-side conversation state |
| [0005](0005-audio2face-as-a-separate-stack.md) | Audio2Face deployed separately, and optional |
| [0006](0006-personas-as-data.md) | Presenters are data, not code branches |
| [0007](0007-keep-the-wire-format.md) | Formalise the WebSocket format, don't redesign it |
| [0008](0008-right-sizing-the-tooling.md) | The tools we deliberately did not adopt |
