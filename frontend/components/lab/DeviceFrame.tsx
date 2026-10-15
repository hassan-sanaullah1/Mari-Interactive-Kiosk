"use client";

/**
 * A portrait device in the lab: the screen at the device's exact aspect ratio,
 * scaled to fit, laid out the way the kiosk lays out portrait screens — the
 * portrait artwork behind, the avatar's canvas across the full width and the
 * bottom 79% of the height — with optional outlines of where the controls sit.
 *
 * The camera frames by the canvas's own size, so what fits here fits on the
 * device: the composition is the same at any scale.
 */

import { useEffect, useRef, useState, type ReactNode } from "react";
import styles from "@/app/lab/lab.module.css";
import { DEVICES, MOBILE_BACKDROP_DEFAULT, MOBILE_GUIDES, PORTRAIT_STAGE_HEIGHT } from "./devices";
import type { LabSettings } from "./LabScene";

/** The lab panel's width (lab.module.css .panel), which the frame must not sit under. */
const PANEL_WIDTH_PX = 380;

interface DeviceFrameProps {
  settings: LabSettings;
  /** A flat backdrop colour instead of the artwork, when one is chosen. */
  backdrop?: string;
  isPanelOpen: boolean;
  children: ReactNode;
}

/** The controls' outlines as percentages of the screen, scaled the way --s scales them. */
function guideBoxes(width: number, height: number) {
  const g = MOBILE_GUIDES;
  const s = Math.min(width / g.design.width, height / g.design.height);
  const micY = height - (g.design.height - g.mic.centerY) * s;
  const r = g.mic.radius * s;
  const pct = (value: number, of: number) => `${(value / of) * 100}%`;
  return {
    mic: { left: pct(width / 2 - r, width), top: pct(micY - r, height), width: pct(2 * r, width), height: pct(2 * r, height), borderRadius: "50%" },
    bottomRow: {
      left: pct(g.bottomRow.left * s, width),
      right: pct(g.bottomRow.left * s, width),
      top: pct(height - (g.design.height - g.bottomRow.top) * s, height),
      height: pct((g.bottomRow.bottom - g.bottomRow.top) * s, height),
      borderRadius: "999px",
    },
  };
}

export function DeviceFrame({ settings, backdrop, isPanelOpen, children }: DeviceFrameProps) {
  const device = DEVICES[settings.device];
  const areaRef = useRef<HTMLDivElement>(null);
  const [shown, setShown] = useState({ width: 0, height: 0 });

  // Fit the device into the free area, keeping its exact aspect ratio.
  useEffect(() => {
    const area = areaRef.current;
    if (!area) return;
    const fit = () => {
      const availableW = area.clientWidth - 48;
      const availableH = area.clientHeight - 48 - 28;
      const scale = Math.min(availableW / device.width, availableH / device.height);
      setShown({ width: Math.floor(device.width * scale), height: Math.floor(device.height * scale) });
    };
    fit();
    const observer = new ResizeObserver(fit);
    observer.observe(area);
    return () => observer.disconnect();
  }, [device.width, device.height]);

  const image = settings.mobileBackdrop === "theme" ? MOBILE_BACKDROP_DEFAULT[settings.theme] : settings.mobileBackdrop;
  const guides = guideBoxes(device.width, device.height);
  const scalePercent = shown.height ? Math.round((shown.height / device.height) * 100) : 0;

  return (
    <div ref={areaRef} className={styles.deviceArea} style={{ right: isPanelOpen ? PANEL_WIDTH_PX : 0 }}>
      <div className={styles.device} style={{ width: shown.width, height: shown.height }}>
        <div
          className={styles.deviceBg}
          style={
            backdrop
              ? { background: backdrop }
              : {
                  backgroundImage: `url("${image}")`,
                  filter: settings.backdropBlur ? `blur(${settings.backdropBlur}px)` : undefined,
                  transform: settings.backdropBlur ? "scale(1.03)" : undefined,
                }
          }
          aria-hidden
        />
        <div className={styles.deviceStage} style={{ height: `${PORTRAIT_STAGE_HEIGHT * 100}%` }}>
          {children}
        </div>
        {settings.showGuides && (
          <div className={styles.guides} aria-hidden>
            <div style={guides.mic} />
            <div style={guides.bottomRow} />
          </div>
        )}
      </div>
      <p className={styles.deviceLabel}>
        {device.label} · shown at {scalePercent}% · {backdrop ? "flat backdrop" : image.slice(1)}
      </p>
    </div>
  );
}
