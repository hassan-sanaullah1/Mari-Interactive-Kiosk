/** Icons traced from the reference design. Sizes are set by the parent via CSS. */

/** 5-bar voice waveform. Bar widths/heights measured off the reference mic button. */
export function WaveformIcon({ className }: { className?: string }) {
  const bars = [14, 44, 72, 44, 14]; // heights, centred on the 72-unit axis
  return (
    <svg className={className} viewBox="0 0 65 72" fill="currentColor" aria-hidden="true">
      {bars.map((h, i) => (
        <rect key={i} x={i * 14.5} y={(72 - h) / 2} width={7} height={h} rx={3.5} />
      ))}
    </svg>
  );
}

export function CloseIcon({ className }: { className?: string }) {
  return (
    <svg className={className} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2.2} strokeLinecap="round" aria-hidden="true">
      <path d="M6 6l12 12M18 6L6 18" />
    </svg>
  );
}

export function PauseIcon({ className }: { className?: string }) {
  return (
    <svg className={className} viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">
      <rect x="7" y="5" width="4" height="14" rx="1.6" />
      <rect x="13" y="5" width="4" height="14" rx="1.6" />
    </svg>
  );
}

export function PlayIcon({ className }: { className?: string }) {
  return (
    <svg className={className} viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">
      <path d="M8 5.6c0-.9 1-1.5 1.8-1L18 11a1.2 1.2 0 0 1 0 2l-8.2 6.4c-.8.5-1.8-.1-1.8-1V5.6Z" />
    </svg>
  );
}

/** Sun / brightness — centre disc plus eight rays. */
export function BrightnessIcon({ className }: { className?: string }) {
  return (
    <svg className={className} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.9} strokeLinecap="round" aria-hidden="true">
      <circle cx="12" cy="12" r="4.1" fill="currentColor" stroke="none" />
      <path d="M12 2.6v2.6M12 18.8v2.6M21.4 12h-2.6M5.2 12H2.6M18.65 5.35l-1.84 1.84M7.19 16.81l-1.84 1.84M18.65 18.65l-1.84-1.84M7.19 7.19 5.35 5.35" />
    </svg>
  );
}

/** Crescent moon — shown in light mode to switch back to dark. */
export function MoonIcon({ className }: { className?: string }) {
  return (
    <svg className={className} viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">
      <path d="M20.7 14.6a8.6 8.6 0 0 1-11.3-11 .9.9 0 0 0-1.2-1.1 10.3 10.3 0 1 0 13.6 13.3.9.9 0 0 0-1.1-1.2Z" />
    </svg>
  );
}

/** Message square with two text lines — the chat launcher. */
export function ChatIcon({ className }: { className?: string }) {
  return (
    <svg className={className} viewBox="0 0 24 24" fill="none" aria-hidden="true">
      <path
        d="M4 5.5A1.5 1.5 0 0 1 5.5 4h13A1.5 1.5 0 0 1 20 5.5v9a1.5 1.5 0 0 1-1.5 1.5H9.2l-3.6 3.1A1 1 0 0 1 4 18.3V5.5Z"
        fill="currentColor"
      />
      <path d="M7.6 8.3h8.8M7.6 11.7h5.8" stroke="#0077DC" strokeWidth={1.7} strokeLinecap="round" />
    </svg>
  );
}

export function SendIcon({ className }: { className?: string }) {
  return (
    <svg className={className} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2.1} strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d="M5 12h13M12.5 6l6 6-6 6" />
    </svg>
  );
}

/**
 * Presenter silhouettes for the avatar toggle — a head over shoulders, the
 * female one with longer hair and the male with a close-cropped cut.
 *
 * Drawn rather than labelled because the pill sits in a bottom-left cluster
 * that is already at its width budget on a 402-unit phone (see
 * LanguageBar.module.css), and because a glyph needs no translating between
 * English and Urdu.
 */
export function FemaleAvatarIcon({ className }: { className?: string }) {
  return (
    <svg className={className} viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">
      {/* hair falling past the jaw, behind the head */}
      <path d="M12 1.9c-3.2 0-5.2 2.1-5.2 5.1 0 1.5.1 2.7-.5 4.1-.2.5.1.9.6.9h1.4a4.6 4.6 0 0 1-.6-2.3V7.2a9.6 9.6 0 0 0 6.4-2 6 6 0 0 0 2.1 2v2.5c0 .9-.2 1.6-.6 2.3h1.4c.5 0 .8-.4.6-.9-.6-1.4-.5-2.6-.5-4.1 0-3-2-5.1-5.1-5.1Z" />
      {/* face */}
      <circle cx="12" cy="9" r="3.4" />
      {/* shoulders */}
      <path d="M12 13.6c-3.9 0-7 2.5-7.6 5.9-.2.9.5 1.7 1.4 1.7h12.4c.9 0 1.6-.8 1.4-1.7-.6-3.4-3.7-5.9-7.6-5.9Z" />
    </svg>
  );
}

export function MaleAvatarIcon({ className }: { className?: string }) {
  return (
    <svg className={className} viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">
      {/* short crop: a crescent hugging the skull and tapering past the ears.
          Drawn flush with the head on purpose — a flat-topped shape floating
          above it reads as a cap rather than as hair. */}
      <path d="M7.6 9.5a4.4 4.4 0 0 1 8.8 0h-.9a3.5 3.5 0 0 0-7 0Z" />
      {/* face */}
      <circle cx="12" cy="9.5" r="3.5" />
      {/* shoulders, squarer than the female silhouette */}
      <path d="M12 13.8c-4 0-7.1 2.4-7.7 5.8-.2.9.5 1.6 1.4 1.6h12.6c.9 0 1.6-.7 1.4-1.6-.6-3.4-3.7-5.8-7.7-5.8Z" />
    </svg>
  );
}
