# Bottom control row: the width budget

Measured in a browser against the running kiosk, portrait layout, at the
402-unit reference width (`--s` = 1px exactly, viewport 402x874).

The row carries six things. Left cluster: the language pill, the presenter
button and the theme switch. Right cluster: the captions toggle and the chat
launcher.

## Why the tokens alone were wrong

`--pill-seg` is a `min-width`, not a width. The language segments hold real
words, and the words plus their side padding are wider than that floor:

| segment   | min-width | rendered | over |
|-----------|-----------|----------|------|
| `English` | 79u       | 100.0u   | +21u |
| `اردو`    | 79u       | 96.6u    | +18u |

So the pill is **206.6u**, not the 168u its tokens suggest.

## The budget

```
pill 206.6 + presenter 46 + theme 46 + captions 45 + chat 45  = 388.6u
available between the two 16u edge margins                     = 370.0u
                                                                 -------
                                                                  -18.6u
```

The row overflowed **with every gap set to zero**. Adding the captions button
to the reference 12.5u gaps put the two clusters 17.5u into each other. At
1080x1920 this was invisible — the font renders proportionally narrower there —
but at 360x640 the clusters measurably collided (left bar ended at 253.4px,
captions began at 252.8px).

## The fix

Slim the segment padding in portrait only, via `--pill-seg-pad`:
`0.32 * --pill-h` (14.4u) → **6u**. The font size (`--pill-font`) is untouched,
so the words stay exactly as large and legible; only the empty space around them
shrinks. That frees ~26u, which pays for the new button and leaves the four gaps
at 3.5u (`--pill-gap`, `--row-gap-tight`).

Landscape keeps the reference 0.32 padding and its 22u gaps: that layout has
room to spare, and its geometry comes from UI.png.

## Verified

| viewport  | left cluster ends | captions start | clear |
|-----------|-------------------|----------------|-------|
| 1080x1920 | 760.2             | 785.9          | 25.7  |
| 402x874   | 301.3             | 312.9          | 11.6  |
| 360x640   | 253.4             | 262.0          |  8.6  |
| 1920x1080 | 1083.8            | 1098.3         | 14.5  |

Re-measure with `scripts/measure-bottom-row.mjs` after changing any of
`--pill-seg-pad`, `--pill-gap`, `--row-gap-tight`, `--launcher`, `--theme-btn`
or `--edge-x`, or after adding another control to this row.
