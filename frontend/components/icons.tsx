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
