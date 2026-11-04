"use client";

import { useRef, useState } from "react";
import styles from "./OnScreenKeyboard.module.css";

/**
 * A touch keyboard for the kiosk, laid out like a phone's.
 *
 * The kiosk has no physical keyboard, so the chat panel's textarea needs one.
 * It renders as a normal flex child of the panel rather than an overlay, so it
 * can never cover the message log, the composer or anything behind the panel —
 * the log is `flex: 1 1 auto; min-height: 0`, so it simply gives up height.
 *
 * SELF-CONTAINED BY DESIGN. It owns no app state and imports nothing from the
 * kiosk: it takes a string in and hands a string back. To remove the feature,
 * delete the two lines that render it in ChatPanel.tsx (plus this file and its
 * stylesheet); nothing else refers to it.
 *
 * `onKey` receives a finished value, not keystrokes, so the caller never has to
 * reimplement backspace or shift.
 */

export interface OnScreenKeyboardProps {
  /** Current text of the field being typed into. */
  value: string;
  /** Called with the new value after every key. */
  onChange: (next: string) => void;
  /** Hide the keyboard. Omit it and no close key is drawn. */
  onClose?: () => void;
  /**
   * Accepted for API compatibility and deliberately ignored for layout: a
   * QWERTY keyboard is not mirrored in Urdu. Phones keep the key order
   * identical and only the text being typed runs right-to-left, so flipping
   * the rows would put Backspace and Shift on the wrong side of a layout
   * every visitor already knows.
   */
  rtl?: boolean;
}

// A phone layout, deliberately without an emoji key: this is a business kiosk
// and the reply goes to an LLM, so emoji would be noise in the transcript.
// How quickly a second tap on shift counts as a double tap.
const DOUBLE_TAP_MS = 400;

const ROWS_LOWER = ["qwertyuiop", "asdfghjkl", "zxcvbnm"];
const ROWS_UPPER = ["QWERTYUIOP", "ASDFGHJKL", "ZXCVBNM"];
// The stock Android symbol pages, so the keyboard holds no surprises: ?123 is
// digits and common punctuation, and its own shift (=\<) reaches the rest.
const ROWS_NUM = ["1234567890", "@#$_&-+()/", "*\"':;!?"];
const ROWS_SYM = ["~`|•√π÷×¶∆", "£¢€¥^°={}", "\\©®™%[]"];

export default function OnScreenKeyboard({
  value,
  onChange,
  onClose,
  // eslint-disable-next-line @typescript-eslint/no-unused-vars -- see the prop's doc
  rtl: _rtl = false,
}: OnScreenKeyboardProps) {
  // Three-way, like a phone's: off -> one-shot -> locked. A second tap within
  // DOUBLE_TAP_MS locks it, which is the gesture people already know; tapping
  // again from locked turns it off.
  const [shiftMode, setShiftMode] = useState<"off" | "once" | "locked">("off");
  const lastShiftTap = useRef(0);
  const [numeric, setNumeric] = useState(false);
  // The second symbol page, reached with =\\< like Android's.
  const [symbols, setSymbols] = useState(false);

  const shift = shiftMode !== "off";
  const rows = numeric ? (symbols ? ROWS_SYM : ROWS_NUM) : shift ? ROWS_UPPER : ROWS_LOWER;

  const tapShift = () => {
    const now = Date.now();
    const quick = now - lastShiftTap.current < DOUBLE_TAP_MS;
    lastShiftTap.current = now;
    // A quick second tap locks; otherwise cycle off <-> one-shot, and a tap
    // while locked releases it.
    setShiftMode((m) => (quick ? "locked" : m === "off" ? "once" : "off"));
  };

  const type = (ch: string) => {
    onChange(value + ch);
    // One-shot shift falls back after a single letter; caps lock holds.
    if (shiftMode === "once") setShiftMode("off");
  };

  return (
    <div
      className={styles.keyboard}
      // Not a <form> and not focusable: taps must never steal focus from the
      // textarea, or the caret disappears while typing.
      onMouseDown={(e) => e.preventDefault()}
      onTouchStart={(e) => e.preventDefault()}
      role="group"
      aria-label="On-screen keyboard"
      // Always ltr: see the rtl prop. The keys never mirror.
      dir="ltr"
    >
      {rows.map((row, i) => (
        <div key={i} className={styles.row}>
          {/* The outer keys sit on the last row, around the letters. */}
          {i === 2 &&
            (numeric ? (
              <button
                type="button"
                className={`${styles.key} ${styles.wide}`}
                onClick={() => setSymbols((v) => !v)}
                aria-label={symbols ? "Numbers" : "More symbols"}
              >
                {symbols ? "?123" : "=\\<"}
              </button>
            ) : (
              <button
                type="button"
                className={`${styles.key} ${styles.wide} ${shift ? styles.active : ""} ${
                  shiftMode === "locked" ? styles.locked : ""
                }`}
                onClick={tapShift}
                aria-label={shiftMode === "locked" ? "Caps lock on" : "Shift"}
                aria-pressed={shift}
              >
                {shiftMode === "locked" ? "⇪" : "⇧"}
              </button>
            ))}

          {row.split("").map((ch) => (
            <button
              key={ch}
              type="button"
              className={styles.key}
              onClick={() => type(ch)}
              aria-label={ch}
            >
              {ch}
            </button>
          ))}

          {i === 2 && (
            <button
              type="button"
              className={`${styles.key} ${styles.wide}`}
              onClick={() => onChange(value.slice(0, -1))}
              aria-label="Backspace"
            >
              ⌫
            </button>
          )}
        </div>
      ))}

      <div className={styles.row}>
        <button
          type="button"
          className={`${styles.key} ${styles.wide}`}
          onClick={() => {
            setNumeric((n) => !n);
            setSymbols(false);
          }}
          aria-label={numeric ? "Letters" : "Numbers and symbols"}
        >
          {numeric ? "ABC" : "?123"}
        </button>

        <button
          type="button"
          className={`${styles.key} ${styles.space}`}
          onClick={() => type(" ")}
          aria-label="Space"
        />

        {/* Enter inserts a line break, it does not send: the composer already
            has its own send button beside the text box, and a visitor part way
            through a long question should be able to start a new line without
            firing it off early. */}
        <button
          type="button"
          className={`${styles.key} ${styles.wide}`}
          onClick={() => type("\n")}
          aria-label="New line"
        >
          ⏎
        </button>

        {onClose && (
          <button
            type="button"
            className={`${styles.key} ${styles.wide}`}
            onClick={onClose}
            aria-label="Hide keyboard"
          >
            ⌄
          </button>
        )}
      </div>
    </div>
  );
}
