"use client";

/**
 * Panel for the lab's editable copy of the kiosk studios and camera
 * (lab-rig.ts): every light of the current theme, the presenter's per-theme
 * knobs, the reflection panels and the framing, plus resets and the JSON export.
 */

import { useState } from "react";
import styles from "@/app/lab/lab.module.css";
import type { AvatarId } from "@/components/avatar/models";
import type { AvatarState } from "@/components/avatar/state";
import type { Theme } from "@/lib/theme";
import { Choice, Slider } from "./LabControls";
import {
  buildExport,
  diff,
  kioskRig,
  LIGHT_NAMES,
  STATE_LIGHTS,
  type LabRig,
  type Layout,
  type LightName,
} from "./lab-rig";

const STATES: AvatarState[] = ["idle", "listening", "thinking", "speaking"];

type Update = (change: (draft: LabRig) => void) => void;

function ColorField({ label, value, onChange }: { label: string; value: string; onChange: (value: string) => void }) {
  return (
    <label className={styles.color}>
      <span>{label}</span>
      <input type="color" value={value} onChange={(event) => onChange(event.target.value)} />
      <code>{value}</code>
    </label>
  );
}

function SelectedLight({ rig, theme, name, update }: { rig: LabRig; theme: Theme; name: LightName; update: Update }) {
  const studio = rig.studio[theme];
  const place = studio.placement[name];
  const axes = ["X (camera-right +)", "Y (up +)", "Z (toward camera +)"];
  const isStateLight = (STATE_LIGHTS as readonly string[]).includes(name);
  return (
    <div className={styles.sliders}>
      <ColorField
        label="Colour"
        value={studio.colors[name]}
        onChange={(color) => update((d) => void (d.studio[theme].colors[name] = color))}
      />
      {axes.map((axis, i) => (
        <Slider
          key={axis}
          label={`Position ${axis}`}
          value={place.position[i]}
          min={-5}
          max={5}
          step={0.05}
          onChange={(v) => update((d) => void (d.studio[theme].placement[name].position[i] = v))}
        />
      ))}
      {isStateLight ? (
        STATES.map((state) => (
          <Slider
            key={state}
            label={`Brightness while ${state}`}
            value={studio.states[state][name as (typeof STATE_LIGHTS)[number]]}
            min={0}
            max={10}
            step={0.05}
            onChange={(v) => update((d) => void (d.studio[theme].states[state][name as (typeof STATE_LIGHTS)[number]] = v))}
          />
        ))
      ) : (
        <Slider
          label="Brightness (every state)"
          value={place.intensity}
          min={0}
          max={10}
          step={0.05}
          onChange={(v) => update((d) => void (d.studio[theme].placement[name].intensity = v))}
        />
      )}
      {place.angle !== undefined && (
        <>
          <Slider label="Cone angle (rad)" value={place.angle} min={0.05} max={1.5} step={0.01} onChange={(v) => update((d) => void (d.studio[theme].placement[name].angle = v))} />
          <Slider label="Penumbra (edge softness)" value={place.penumbra ?? 0} min={0} max={1} step={0.01} onChange={(v) => update((d) => void (d.studio[theme].placement[name].penumbra = v))} />
          <Slider label="Reach (m, 0 = unlimited)" value={place.distance ?? 0} min={0} max={10} step={0.05} onChange={(v) => update((d) => void (d.studio[theme].placement[name].distance = v))} />
        </>
      )}
    </div>
  );
}

function ThemeKnobs({ rig, theme, presenter, update }: { rig: LabRig; theme: Theme; presenter: AvatarId; update: Update }) {
  const knobs = rig.rigLighting[presenter][theme];
  const back = rig.rigLighting[presenter].backLight;
  const studio = rig.studio[theme];
  const setKnob = (key: keyof typeof knobs) => (v: number) => update((d) => void (d.rigLighting[presenter][theme][key] = v));
  return (
    <div className={styles.sliders}>
      <Slider label="Exposure" value={knobs.exposure} min={0.3} max={2} step={0.01} onChange={setKnob("exposure")} />
      <Slider label="Ambient" value={knobs.ambient} min={0} max={2} step={0.01} onChange={setKnob("ambient")} />
      <Slider label="Fill multiplier" value={knobs.fill} min={0} max={3} step={0.01} onChange={setKnob("fill")} />
      <Slider label="Reflections (environment)" value={knobs.environment} min={0} max={3} step={0.01} onChange={setKnob("environment")} />
      <ColorField label="Ambient colour" value={studio.ambientColor} onChange={(c) => update((d) => void (d.studio[theme].ambientColor = c))} />
      <Slider label="Shadow strength" value={studio.shadow.intensity} min={0} max={1} step={0.01} onChange={(v) => update((d) => void (d.studio[theme].shadow.intensity = v))} />
      <Slider label="Back light: rim (both themes)" value={back.rim} min={0} max={2} step={0.01} onChange={(v) => update((d) => void (d.rigLighting[presenter].backLight.rim = v))} />
      <Slider label="Back light: kick (both themes)" value={back.kick} min={0} max={2} step={0.01} onChange={(v) => update((d) => void (d.rigLighting[presenter].backLight.kick = v))} />
    </div>
  );
}

function PanelsEditor({ rig, theme, update }: { rig: LabRig; theme: Theme; update: Update }) {
  return (
    <div className={styles.sliders}>
      {rig.studio[theme].environment.lightformers.map((panel, i) => (
        <div key={i} className={styles.panelRow}>
          <Slider
            label={`Panel ${i + 1} brightness`}
            value={panel.intensity}
            min={0}
            max={6}
            step={0.05}
            onChange={(v) => update((d) => void (d.studio[theme].environment.lightformers[i].intensity = v))}
          />
          <ColorField label="colour" value={panel.color} onChange={(c) => update((d) => void (d.studio[theme].environment.lightformers[i].color = c))} />
        </div>
      ))}
    </div>
  );
}

function CameraEditor({
  rig,
  presenter,
  layout,
  update,
}: {
  rig: LabRig;
  presenter: AvatarId;
  layout: Layout;
  update: Update;
}) {
  const cam = rig.camera[layout];
  const own = cam.rigs[presenter];
  const isFixed = own.cameraDistanceM !== null;
  return (
    <div className={styles.sliders}>
      <Slider label="Frame height (m of her in frame)" value={cam.frameHeightM} min={0.4} max={2.5} step={0.01} onChange={(v) => update((d) => void (d.camera[layout].frameHeightM = v))} />
      <Slider label="Head room (fraction of height)" value={cam.headRoom} min={0} max={0.3} step={0.005} onChange={(v) => update((d) => void (d.camera[layout].headRoom = v))} />
      <Slider label="Lens (mm, this presenter)" value={own.lensMm} min={18} max={200} step={1} onChange={(v) => update((d) => void (d.camera[layout].rigs[presenter].lensMm = v))} />
      <Choice
        label="Camera distance (this presenter)"
        value={isFixed ? "fixed" : "auto"}
        options={[
          ["auto", "From the lens"],
          ["fixed", "Fixed"],
        ]}
        onChange={(mode) => update((d) => void (d.camera[layout].rigs[presenter].cameraDistanceM = mode === "fixed" ? (own.cameraDistanceM ?? 4) : null))}
      />
      {isFixed && (
        <Slider label="Distance (m)" value={own.cameraDistanceM ?? 4} min={0.5} max={12} step={0.01} onChange={(v) => update((d) => void (d.camera[layout].rigs[presenter].cameraDistanceM = v))} />
      )}
      <Slider label="Width squeeze (this presenter)" value={own.widthSqueeze} min={0.7} max={1.3} step={0.005} onChange={(v) => update((d) => void (d.camera[layout].rigs[presenter].widthSqueeze = v))} />
      <Slider label="Sway amplitude (m)" value={cam.sway.amplitude} min={0} max={0.1} step={0.001} onChange={(v) => update((d) => void (d.camera[layout].sway.amplitude = v))} />
      <Slider label="Sway speed" value={cam.sway.speed} min={0} max={0.5} step={0.005} onChange={(v) => update((d) => void (d.camera[layout].sway.speed = v))} />
    </div>
  );
}

function ExportBar({ rig, scene }: { rig: LabRig; scene: Record<string, unknown> }) {
  const [copied, setCopied] = useState(false);
  const changes = diff(kioskRig(), rig).length;
  const document_ = () => JSON.stringify(buildExport(rig, scene), null, 2);
  const download = () => {
    const blob = new Blob([document_()], { type: "application/json" });
    const link = document.createElement("a");
    link.href = URL.createObjectURL(blob);
    link.download = `avatar-lab-${new Date().toISOString().slice(0, 19).replace(/[:T]/g, "-")}.json`;
    link.click();
    URL.revokeObjectURL(link.href);
  };
  const copy = async () => {
    await navigator.clipboard.writeText(document_());
    setCopied(true);
    setTimeout(() => setCopied(false), 1500);
  };
  return (
    <>
      <p className={styles.hint}>
        {changes === 0 ? "Identical to the kiosk." : `${changes} value(s) differ from the kiosk.`} The export holds the
        whole rig, the list of changes with where each belongs in the code, and the scene it was judged in.
      </p>
      <div className={styles.row}>
        <button type="button" onClick={download}>
          Export JSON
        </button>
        <button type="button" onClick={() => void copy()}>
          {copied ? "Copied" : "Copy JSON"}
        </button>
      </div>
    </>
  );
}

interface RigEditorProps {
  rig: LabRig;
  onChange: (rig: LabRig) => void;
  theme: Theme;
  presenter: AvatarId;
  layout: Layout;
  editLight: LightName;
  onEditLight: (name: LightName) => void;
  showHandles: boolean;
  onShowHandles: (show: boolean) => void;
  /** Everything else about the scene, recorded in the export. */
  scene: Record<string, unknown>;
  /** What the scene is currently showing, to warn when these edits are not on screen. */
  visible: { lights: boolean; camera: boolean; panels: boolean };
  /** Switch the scene to show the editable lights, panels and framing. */
  onShowEdits: () => void;
}

/**
 * Edits to the copy are kept whatever the scene shows, so with Lights on
 * "None" a moved light changes the export but nothing on screen. Say so.
 */
function HiddenEditsNotice({ visible, onShowEdits }: Pick<RigEditorProps, "visible" | "onShowEdits">) {
  const hidden = [
    !visible.lights && "lights (Lights is not \"Kiosk studio (editable)\")",
    !visible.panels && "reflection panels (Environment is not \"Studio panels\")",
    !visible.camera && "camera (Camera is not \"Kiosk framing (editable)\")",
  ].filter(Boolean);
  if (!hidden.length) return null;
  return (
    <div className={styles.notice}>
      <p>Not on screen right now: {hidden.join("; ")}. Edits are still kept and exported.</p>
      <button type="button" onClick={onShowEdits}>
        Show my edits
      </button>
    </div>
  );
}

export function RigEditor(props: RigEditorProps) {
  const { rig, onChange, theme, presenter, layout, editLight, onEditLight, showHandles, onShowHandles, scene } = props;
  const { visible, onShowEdits } = props;
  const update: Update = (change) => {
    const next = structuredClone(rig);
    change(next);
    onChange(next);
  };
  const kiosk = kioskRig();
  return (
    <section className={styles.section}>
      <h2>Kiosk lights and camera (editable lab copy)</h2>
      <p className={styles.hint}>
        Starts as an exact copy of tuning.ts and only changes here; the kiosk is never touched. Shown with Lights
        &quot;Kiosk studio (editable)&quot; and Camera &quot;Kiosk framing (editable)&quot;. Editing the {theme} studio:
        switch Theme above to edit the other one.
      </p>

      <HiddenEditsNotice visible={visible} onShowEdits={onShowEdits} />

      <h3>Lights: {theme} studio</h3>
      <Choice label="Light" value={editLight} options={LIGHT_NAMES.map((n) => [n, n] as const)} onChange={onEditLight} />
      <Choice
        label="Handles in the scene"
        value={showHandles ? "on" : "off"}
        options={[
          ["on", "Show"],
          ["off", "Hide"],
        ]}
        onChange={(v) => onShowHandles(v === "on")}
        hint="Click a ball to select its light, drag the arrows to move it."
      />
      <SelectedLight rig={rig} theme={theme} name={editLight} update={update} />

      <h3>{theme} knobs for this presenter</h3>
      <ThemeKnobs rig={rig} theme={theme} presenter={presenter} update={update} />

      <h3>Reflection panels: {theme}</h3>
      <p className={styles.hint}>Seen with Environment &quot;Studio panels&quot;.</p>
      <PanelsEditor rig={rig} theme={theme} update={update} />

      <h3>Camera framing: {layout}</h3>
      <p className={styles.hint}>
        One framing per layout; switch Layout above to edit the other. The kiosk has a single framing today, so a mobile
        value that differs is a new setting (the export says so).
      </p>
      <CameraEditor rig={rig} presenter={presenter} layout={layout} update={update} />

      <div className={styles.row}>
        <button type="button" onClick={() => update((d) => void (d.studio[theme] = structuredClone(kiosk.studio[theme])))}>
          Reset {theme} lights
        </button>
        <button type="button" onClick={() => update((d) => void (d.camera[layout] = structuredClone(kiosk.camera[layout])))}>
          Reset {layout} camera
        </button>
        <button type="button" onClick={() => onChange(kiosk)}>
          Reset all
        </button>
      </div>

      <h3>Export</h3>
      <ExportBar rig={rig} scene={scene} />
    </section>
  );
}
