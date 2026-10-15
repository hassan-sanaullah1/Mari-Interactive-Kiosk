"use client";

/**
 * Step 0 of matching a target picture: put it next to (or over) the render, and
 * read colours off both, so tuning converges on numbers instead of guesses.
 *
 *   ReferenceSide     the target pinned to the left of the window
 *   ReferenceOverlay  the target laid over the render at an adjustable opacity
 *   useEyedropper     while on, a click on the render or on the target samples
 *                     a 9 x 9 px average there instead of doing anything else
 *   SamplesPanel      the samples, with the ratios that tell skin tones apart
 */

import { useEffect } from "react";
import styles from "@/app/lab/lab.module.css";

export interface ColorSample {
  id: number;
  source: "render" | "target";
  rgb: [number, number, number];
}

/** Lab-only pictures (public/lab/, git-ignored); a file can also be loaded from disk. */
export const COMPARE_IMAGES = [
  ["/lab/reference.webp", "Reference portrait"],
  ["/lab/comparison.webp", "Your comparison screenshot"],
] as const;

export function ReferenceSide({ image }: { image: string }) {
  // eslint-disable-next-line @next/next/no-img-element -- a local file or data URL, sampled by pixel
  return <img src={image} alt="Target" className={styles.referenceSide} data-reference />;
}

export function ReferenceOverlay({ image, opacity }: { image: string; opacity: number }) {
  // eslint-disable-next-line @next/next/no-img-element -- a local file or data URL, drawn over the render
  return <img src={image} alt="" className={styles.referenceOverlay} style={{ opacity }} aria-hidden />;
}

const RADIUS = 4;

/** Average colour of a (2*RADIUS+1)^2 patch of a drawable at a pixel position. */
function averageAt(source: CanvasImageSource, width: number, height: number, x: number, y: number) {
  const canvas = document.createElement("canvas");
  canvas.width = width;
  canvas.height = height;
  const context = canvas.getContext("2d", { willReadFrequently: true });
  if (!context) return null;
  context.drawImage(source, 0, 0, width, height);
  const data = context.getImageData(Math.max(0, x - RADIUS), Math.max(0, y - RADIUS), 2 * RADIUS + 1, 2 * RADIUS + 1).data;
  let r = 0;
  let g = 0;
  let b = 0;
  let n = 0;
  for (let i = 0; i < data.length; i += 4) {
    if (data[i + 3] < 200) continue; // the transparent canvas around her: not her
    r += data[i];
    g += data[i + 1];
    b += data[i + 2];
    n += 1;
  }
  return n ? ([r / n, g / n, b / n].map(Math.round) as [number, number, number]) : null;
}

/** Sample whatever is under a click: the avatar canvas or a target picture. */
function sampleAt(clientX: number, clientY: number): Omit<ColorSample, "id"> | null {
  for (const element of document.elementsFromPoint(clientX, clientY)) {
    const rect = element.getBoundingClientRect();
    if (element instanceof HTMLCanvasElement) {
      // preserveDrawingBuffer is on in the lab, so the last frame is still there.
      const x = Math.round(((clientX - rect.left) / rect.width) * element.width);
      const y = Math.round(((clientY - rect.top) / rect.height) * element.height);
      const rgb = averageAt(element, element.width, element.height, x, y);
      if (rgb) return { source: "render", rgb };
    }
    if (element instanceof HTMLImageElement && element.dataset.reference !== undefined) {
      const x = Math.round(((clientX - rect.left) / rect.width) * element.naturalWidth);
      const y = Math.round(((clientY - rect.top) / rect.height) * element.naturalHeight);
      const rgb = averageAt(element, element.naturalWidth, element.naturalHeight, x, y);
      if (rgb) return { source: "target", rgb };
    }
  }
  return null;
}

/** While enabled, clicks on the render or the target are samples, not interactions. */
export function useEyedropper(enabled: boolean, onSample: (sample: Omit<ColorSample, "id">) => void) {
  useEffect(() => {
    if (!enabled) return;
    const onClick = (event: MouseEvent) => {
      if ((event.target as Element).closest("aside")) return; // the panel stays usable
      const sample = sampleAt(event.clientX, event.clientY);
      if (!sample) return;
      event.preventDefault();
      event.stopPropagation();
      onSample(sample);
    };
    document.addEventListener("click", onClick, true);
    document.body.style.cursor = "crosshair";
    return () => {
      document.removeEventListener("click", onClick, true);
      document.body.style.cursor = "";
    };
  }, [enabled, onSample]);
}

export function SamplesPanel({ samples, onClear }: { samples: ColorSample[]; onClear: () => void }) {
  if (!samples.length) {
    return <p className={styles.hint}>No samples yet. Click the same spot on the target and on the render.</p>;
  }
  return (
    <>
      <table className={styles.samples}>
        <thead>
          <tr>
            <th />
            <th>from</th>
            <th>R G B</th>
            <th title="Green over red: lower is redder">G/R</th>
            <th title="Blue over red: lower is more orange">B/R</th>
          </tr>
        </thead>
        <tbody>
          {samples.map(({ id, source, rgb: [r, g, b] }) => (
            <tr key={id}>
              <td>
                <span className={styles.swatch} style={{ background: `rgb(${r} ${g} ${b})` }} />
              </td>
              <td>{source}</td>
              <td>
                {r} {g} {b}
              </td>
              <td>{(g / r).toFixed(2)}</td>
              <td>{(b / r).toFixed(2)}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <div className={styles.row}>
        <button type="button" onClick={onClear}>
          Clear samples
        </button>
      </div>
    </>
  );
}
