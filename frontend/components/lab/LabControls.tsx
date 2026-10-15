"use client";

/**
 * The avatar lab's controls: segmented choices, sliders, and the Phase A panel
 * (surface realism, life, ambient occlusion) with its presets.
 */

import type { ReactNode } from "react";
import styles from "@/app/lab/lab.module.css";
import { DEFAULT_LIFE, NO_LIFE, type LifeOptions } from "@/components/avatar/liveliness";
import { NO_GRADE, type GradeSettings } from "@/components/avatar/PostEffects";
import {
  ALL_REALISM,
  DEFAULT_REALISM_PARAMS,
  KIOSK_REALISM,
  type RealismOptions,
  type RealismParams,
} from "@/components/avatar/realism";
import type { LabSettings } from "./LabScene";
import { REFERENCE_BACKDROP_BLUR, REFERENCE_GRADE } from "./reference-look";

interface ChoiceProps<T extends string> {
  label: string;
  value: T;
  options: readonly (readonly [T, string])[];
  onChange: (value: T) => void;
  disabled?: readonly T[];
  hint?: ReactNode;
}

export function Choice<T extends string>({ label, value, options, onChange, disabled = [], hint }: ChoiceProps<T>) {
  return (
    <fieldset className={styles.group}>
      <legend>{label}</legend>
      <div className={styles.segments}>
        {options.map(([option, text]) => (
          <button
            key={option}
            type="button"
            className={option === value ? styles.on : undefined}
            disabled={disabled.includes(option)}
            onClick={() => onChange(option)}
          >
            {text}
          </button>
        ))}
      </div>
      {hint && <p className={styles.hint}>{hint}</p>}
    </fieldset>
  );
}

const ON_OFF = [
  ["off", "Off"],
  ["on", "On"],
] as const;

function Toggle({
  label,
  value,
  onChange,
  hint,
}: {
  label: string;
  value: boolean;
  onChange: (value: boolean) => void;
  hint?: ReactNode;
}) {
  return (
    <Choice label={label} value={value ? "on" : "off"} options={ON_OFF} onChange={(v) => onChange(v === "on")} hint={hint} />
  );
}

export function Slider({
  label,
  value,
  min,
  max,
  step,
  onChange,
  disabled = false,
}: {
  label: string;
  value: number;
  min: number;
  max: number;
  step: number;
  onChange: (value: number) => void;
  disabled?: boolean;
}) {
  return (
    <label className={styles.slider} data-disabled={disabled}>
      <span>
        {label} <output>{value.toFixed(2)}</output>
      </span>
      <input
        type="range"
        min={min}
        max={max}
        step={step}
        value={value}
        disabled={disabled}
        onChange={(event) => onChange(Number(event.target.value))}
      />
    </label>
  );
}

type PhaseA = Pick<LabSettings, "realism" | "realismParams" | "life" | "ao" | "grade" | "shadowSoftness">;

/** What the kiosk renders today. */
export const KIOSK_PHASE_A: PhaseA = {
  realism: KIOSK_REALISM,
  realismParams: DEFAULT_REALISM_PARAMS,
  life: NO_LIFE,
  ao: { enabled: false, intensity: 0.8, radius: 0.12 },
  grade: NO_GRADE,
  shadowSoftness: 0,
};

const ALL_PHASE_A: PhaseA = {
  realism: ALL_REALISM,
  realismParams: DEFAULT_REALISM_PARAMS,
  life: DEFAULT_LIFE,
  ao: { enabled: true, intensity: 0.8, radius: 0.12 },
  grade: NO_GRADE,
  shadowSoftness: 4,
};

/**
 * Reference v1: the supplied portrait, as far as the asset allows. Every value
 * and the reading it came from is in reference-look.ts; these are the scene
 * settings that go with it.
 */
export const REFERENCE_V1: Partial<LabSettings> = {
  look: "kiosk",
  lights: "reference",
  environment: "reference",
  theme: "light",
  tone: "neutral",
  view: "lit",
  camera: "kiosk",
  backdropBlur: REFERENCE_BACKDROP_BLUR,
  realism: ALL_REALISM,
  realismParams: {
    // A soft, warm terminator.
    scatterWrap: 0.5,
    scatterStrength: 0.9,
    scatterWarmth: 0.8,
    // Satin lips, not wet.
    lipGloss: 0.35,
    // The reference skin is retouched-smooth; the waistcoat's weave is visible.
    skinDetail: 0.35,
    clothDetail: 2,
    smoothAmount: DEFAULT_REALISM_PARAMS.smoothAmount,
    smoothRadius: DEFAULT_REALISM_PARAMS.smoothRadius,
    skinRoughness: DEFAULT_REALISM_PARAMS.skinRoughness,
    skinSheen: DEFAULT_REALISM_PARAMS.skinSheen,
  },
  // A full smile with cheeks and eyes engaged, looking into the lens.
  life: { smile: 0.45, gaze: true, headDrift: true },
  // Soft contact shading only: the reference has no dark pockets.
  ao: { enabled: true, intensity: 0.6, radius: 0.1 },
  grade: REFERENCE_GRADE,
};

/**
 * Reference v2: the face only — the reference's light, soft shadows and
 * retouched, evenly sheened skin. No expression: the resting smile stays off.
 *
 *   smoothing   0.65 at a radius of ~5 texels evens the painted blotches out;
 *               skin bump detail drops to 0.1 so it does not put them back
 *   sheen       roughness 0.42 and reflection 0.85: a broad, low shine
 *   scatter     a wider, slightly softer wrap: the reference's light-to-shadow
 *               transition on the cheek is long and warm
 *   shadows     VSM blurred by 6: no hard edge under the nose or chin
 *   AO          lighter and tighter than v1: contact shading, never pockets
 */
export const REFERENCE_V2: Partial<LabSettings> = {
  ...REFERENCE_V1,
  realism: { ...ALL_REALISM, lipGloss: false },
  realismParams: {
    scatterWrap: 0.55,
    scatterStrength: 0.85,
    scatterWarmth: 0.8,
    lipGloss: 0,
    skinDetail: 0.1,
    clothDetail: 2,
    smoothAmount: 0.65,
    smoothRadius: 0.0025,
    skinRoughness: 0.42,
    skinSheen: 0.85,
  },
  life: { smile: 0, gaze: true, headDrift: true },
  ao: { enabled: true, intensity: 0.45, radius: 0.08 },
  shadowSoftness: 6,
};

/** What the kiosk renders today, including its lights, environment and tone mapping. */
export const KIOSK_TODAY: Partial<LabSettings> = {
  look: "kiosk",
  lights: "studio",
  environment: "panels",
  tone: "aces",
  backdropBlur: 0,
};

function SurfaceSwitches({ realism, onChange }: { realism: RealismOptions; onChange: (r: RealismOptions) => void }) {
  const set = (key: keyof RealismOptions) => (value: boolean) => onChange({ ...realism, [key]: value });
  return (
    <>
      <Toggle
        label="Skin glow (kiosk emissive lift)"
        value={realism.skinGlow}
        onChange={set("skinGlow")}
        hint="Only the kiosk look has it. Off lets the lights shape the face."
      />
      <Toggle
        label="Skin scatter (warm light past the shadow edge)"
        value={realism.skinScatter}
        onChange={set("skinScatter")}
        hint="Needs the studio lights: they are the direct light it wraps."
      />
      <Toggle label="Lip and flush gloss (roughness from colour)" value={realism.lipGloss} onChange={set("lipGloss")} />
      <Toggle
        label="Surface detail (colour reused as bump)"
        value={realism.surfaceDetail}
        onChange={set("surfaceDetail")}
        hint="Pores and freckles on skin, the weave on the 4K garments."
      />
      <Toggle
        label="Skin smoothing (retouch)"
        value={realism.skinSmooth}
        onChange={set("skinSmooth")}
        hint="Blurs the skin texture and blends it back: even tone, no blotches. Keep skin detail low with it."
      />
      <Toggle
        label="Skin sheen (soft even shine)"
        value={realism.skinSheen}
        onChange={set("skinSheen")}
        hint="One roughness and reflection strength for all skin, like the reference's forehead and cheekbones."
      />
      <Toggle label="Wet eyes (clear-coat catchlight)" value={realism.wetEyes} onChange={set("wetEyes")} />
      <Toggle
        label="Soft hair edges (alpha to coverage)"
        value={realism.hairCoverage}
        onChange={set("hairCoverage")}
        hint="Judge on the kiosk's GPU: it depends on real MSAA."
      />
    </>
  );
}

function SurfaceSliders({
  realism,
  params,
  onChange,
}: {
  realism: RealismOptions;
  params: RealismParams;
  onChange: (p: RealismParams) => void;
}) {
  const set = (key: keyof RealismParams) => (value: number) => onChange({ ...params, [key]: value });
  return (
    <div className={styles.sliders}>
      <Slider label="Scatter wrap" value={params.scatterWrap} min={0} max={1} step={0.05} onChange={set("scatterWrap")} disabled={!realism.skinScatter} />
      <Slider label="Scatter strength" value={params.scatterStrength} min={0} max={2} step={0.05} onChange={set("scatterStrength")} disabled={!realism.skinScatter} />
      <Slider label="Scatter warmth" value={params.scatterWarmth} min={0} max={1} step={0.05} onChange={set("scatterWarmth")} disabled={!realism.skinScatter} />
      <Slider label="Lip gloss" value={params.lipGloss} min={0} max={1} step={0.05} onChange={set("lipGloss")} disabled={!realism.lipGloss} />
      <Slider label="Skin detail" value={params.skinDetail} min={0} max={4} step={0.1} onChange={set("skinDetail")} disabled={!realism.surfaceDetail} />
      <Slider label="Cloth detail" value={params.clothDetail} min={0} max={6} step={0.1} onChange={set("clothDetail")} disabled={!realism.surfaceDetail} />
      <Slider label="Smoothing amount" value={params.smoothAmount} min={0} max={1} step={0.01} onChange={set("smoothAmount")} disabled={!realism.skinSmooth} />
      <Slider label="Smoothing radius" value={params.smoothRadius} min={0.0005} max={0.008} step={0.0005} onChange={set("smoothRadius")} disabled={!realism.skinSmooth} />
      <Slider label="Skin roughness" value={params.skinRoughness} min={0.2} max={0.9} step={0.01} onChange={set("skinRoughness")} disabled={!realism.skinSheen} />
      <Slider label="Skin sheen (reflection)" value={params.skinSheen} min={0} max={2} step={0.01} onChange={set("skinSheen")} disabled={!realism.skinSheen} />
    </div>
  );
}

function LifeControls({ life, onChange }: { life: LifeOptions; onChange: (l: LifeOptions) => void }) {
  return (
    <>
      <Slider label="Resting smile" value={life.smile} min={0} max={0.5} step={0.02} onChange={(smile) => onChange({ ...life, smile })} />
      <Toggle
        label="Eye movement (fixations and glances)"
        value={life.gaze}
        onChange={(gaze) => onChange({ ...life, gaze })}
      />
      <Toggle
        label="Head drift (slow, on top of the clip)"
        value={life.headDrift}
        onChange={(headDrift) => onChange({ ...life, headDrift })}
      />
    </>
  );
}

function AoControls({ ao, onChange }: { ao: PhaseA["ao"]; onChange: (a: PhaseA["ao"]) => void }) {
  return (
    <>
      <Toggle
        label="Ambient occlusion (contact shading in creases)"
        value={ao.enabled}
        onChange={(enabled) => onChange({ ...ao, enabled })}
        hint="GTAO post-process; keeps the background transparent."
      />
      <div className={styles.sliders}>
        <Slider label="AO intensity" value={ao.intensity} min={0} max={1} step={0.05} onChange={(intensity) => onChange({ ...ao, intensity })} disabled={!ao.enabled} />
        <Slider label="AO radius (m)" value={ao.radius} min={0.02} max={0.5} step={0.01} onChange={(radius) => onChange({ ...ao, radius })} disabled={!ao.enabled} />
      </div>
    </>
  );
}

function GradeControls({ grade, onChange }: { grade: GradeSettings; onChange: (g: GradeSettings) => void }) {
  const set = (key: keyof Omit<GradeSettings, "enabled">) => (value: number) => onChange({ ...grade, [key]: value });
  const off = !grade.enabled;
  return (
    <>
      <Toggle
        label="Colour grade (after tone mapping)"
        value={grade.enabled}
        onChange={(enabled) => onChange({ ...grade, enabled })}
      />
      <div className={styles.sliders}>
        <Slider label="Contrast" value={grade.contrast} min={0.8} max={1.3} step={0.01} onChange={set("contrast")} disabled={off} />
        <Slider label="Saturation" value={grade.saturation} min={0.6} max={1.4} step={0.01} onChange={set("saturation")} disabled={off} />
        <Slider label="Lift blacks" value={grade.lift} min={0} max={0.1} step={0.005} onChange={set("lift")} disabled={off} />
        <Slider label="Warm highlights" value={grade.warmth} min={-0.2} max={0.2} step={0.01} onChange={set("warmth")} disabled={off} />
        <Slider label="Teal shadows" value={grade.tealShadows} min={-0.2} max={0.2} step={0.01} onChange={set("tealShadows")} disabled={off} />
      </div>
    </>
  );
}

/** Every Phase A upgrade, grouped, with presets for "kiosk today" and "all on". */
export function PhaseAPanel({ value, onChange }: { value: PhaseA; onChange: (value: PhaseA) => void }) {
  const patch = (part: Partial<PhaseA>) => onChange({ ...value, ...part });
  return (
    <section className={styles.section}>
      <h2>Phase A</h2>
      <p className={styles.hint}>Applied on top of the look above. Kiosk today: glow on, everything else off.</p>
      <div className={styles.row}>
        <button type="button" onClick={() => onChange(KIOSK_PHASE_A)}>
          Kiosk today
        </button>
        <button type="button" onClick={() => onChange(ALL_PHASE_A)}>
          All Phase A on
        </button>
      </div>

      <h3>Surfaces</h3>
      <SurfaceSwitches realism={value.realism} onChange={(realism) => patch({ realism })} />
      <SurfaceSliders
        realism={value.realism}
        params={value.realismParams}
        onChange={(realismParams) => patch({ realismParams })}
      />

      <h3>Life</h3>
      <LifeControls life={value.life} onChange={(life) => patch({ life })} />

      <h3>Shadows</h3>
      <Slider
        label="Shadow softness (0 = kiosk PCF, above = VSM blur)"
        value={value.shadowSoftness}
        min={0}
        max={12}
        step={0.5}
        onChange={(shadowSoftness) => patch({ shadowSoftness })}
      />

      <h3>Ambient occlusion</h3>
      <AoControls ao={value.ao} onChange={(ao) => patch({ ao })} />

      <h3>Grade</h3>
      <GradeControls grade={value.grade} onChange={(grade) => patch({ grade })} />
    </section>
  );
}
