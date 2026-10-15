"use client";

/**
 * /lab — the avatar on a bench, for working on how she renders.
 *
 * Each part of the kiosk's rendering can be switched on its own: the raw asset
 * against the kiosk's corrected one, the neutral room against the studio, every
 * tone mapping, debug views of the surfaces, and a free camera. The panel also
 * reports what the rig file actually carries (meshes, maps, resolutions), which
 * is the ceiling every rendering change works under.
 *
 * Not linked from the kiosk. Nothing here changes the kiosk's own page.
 */

import dynamic from "next/dynamic";
import { useCallback, useEffect, useState, type CSSProperties, type ReactNode } from "react";
import styles from "./lab.module.css";
import bgStyles from "../page.module.css";
import { AVATARS, type AvatarId } from "@/components/avatar/models";
import type { AssetInventory } from "@/components/lab/lab-tools";
import {
  Choice,
  KIOSK_PHASE_A,
  KIOSK_TODAY,
  PhaseAPanel,
  REFERENCE_V1,
  REFERENCE_V2,
  Slider,
} from "@/components/lab/LabControls";
import { DEVICES, MOBILE_BACKDROPS, type DeviceId } from "@/components/lab/devices";
import { DeviceFrame } from "@/components/lab/DeviceFrame";
import { kioskRig, type LightName } from "@/components/lab/lab-rig";
import type { LabSettings } from "@/components/lab/LabScene";
import { clearLabSettings, loadLabSettings, saveLabSettings } from "@/components/lab/lab-storage";
import { RigEditor } from "@/components/lab/RigEditor";

// three.js needs WebGL, which exists only in the browser.
const LabScene = dynamic(() => import("@/components/lab/LabScene"), { ssr: false });

type Backdrop = "artwork" | "grey" | "white" | "black";

const BACKDROP_COLOR: Record<Exclude<Backdrop, "artwork">, string> = {
  // Mid-grey is the standard for judging a render: it biases nothing.
  grey: "#7a7a7a",
  white: "#f4f4f4",
  black: "#050505",
};

const PRESENTERS = Object.keys(AVATARS) as AvatarId[];

const INITIAL: LabSettings = {
  presenter: PRESENTERS[0],
  look: "raw",
  lights: "off",
  environment: "room",
  backdropStrength: 1,
  backdropBlur: 0,
  ...KIOSK_PHASE_A,
  theme: "dark",
  tone: "aces",
  view: "lit",
  pose: "breathing",
  camera: "kiosk",
  rig: kioskRig(),
  editLight: "key",
  showHandles: true,
  layout: "desktop",
  device: "phone",
  mobileBackdrop: "theme",
  showGuides: true,
};

function InventoryPanel({ data }: { data: AssetInventory | null }) {
  if (!data) return <p className={styles.hint}>Loading the rig…</p>;
  return (
    <details className={styles.inventory} open>
      <summary>
        What this rig carries ({data.materials.length} materials)
      </summary>
      <p className={styles.hint}>
        {data.meshes} meshes · {data.vertices.toLocaleString()} vertices · {data.bones} bones ·{" "}
        {data.morphTargets} face shapes
      </p>
      <p className={styles.coverage}>
        {Object.entries(data.mapCoverage).map(([map, count]) => (
          <span key={map} className={count ? styles.have : styles.missing}>
            {map} {count}
          </span>
        ))}
      </p>
      <table>
        <thead>
          <tr>
            <th>material</th>
            <th>maps</th>
            <th>rough</th>
            <th>alpha</th>
          </tr>
        </thead>
        <tbody>
          {data.materials.map((row) => (
            <tr key={row.name + row.maps.join()}>
              <td>{row.name}</td>
              <td>{row.maps.length ? row.maps.join(", ") : "—"}</td>
              <td>{row.roughness?.toFixed(2) ?? "—"}</td>
              <td>{row.alpha}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </details>
  );
}

const ENVIRONMENT_HINT: Record<LabSettings["environment"], string> = {
  room: "three.js RoomEnvironment: soft, colourless, from every side.",
  panels: "The studio's reflection panels for the theme (STUDIO in tuning.ts).",
  backdrop: "The theme's background picture wrapped round her: she reflects the room she stands in.",
  reference: "The reference portrait's lobby as soft panels: window wall camera-left, ceiling, floor, teal glass.",
};

/** The backdrop picture's style: blurred (the reference's depth of field) when asked. */
function backdropStyle(blur: number): CSSProperties | undefined {
  if (!blur) return undefined;
  // Slightly enlarged with the blur, or the soft edge pulls in from the sides.
  return { filter: "blur(" + blur + "px)", transform: "scale(1.03)" };
}

type Setter = <K extends keyof LabSettings>(key: K) => (value: LabSettings[K]) => void;

/** Device, portrait artwork and control guides, for the mobile frame. */
function MobileControls({ settings, set }: { settings: LabSettings; set: Setter }) {
  return (
    <>
      <Choice
        label="Device"
        value={settings.device}
        options={(Object.keys(DEVICES) as DeviceId[]).map((id) => [id, DEVICES[id].label] as const)}
        onChange={set("device")}
      />
      <Choice
        label="Portrait artwork"
        value={settings.mobileBackdrop}
        options={[["theme", "Kiosk's for theme"], ...MOBILE_BACKDROPS.map((f) => [f, f.slice(1)] as const)]}
        onChange={set("mobileBackdrop")}
      />
      <Choice
        label="Control guides"
        value={settings.showGuides ? "on" : "off"}
        options={[
          ["on", "Show"],
          ["off", "Hide"],
        ]}
        onChange={(v) => set("showGuides")(v === "on")}
        hint="Outlines the mic and the bottom row, so her face and hands stay clear of them."
      />
    </>
  );
}

/** The canvas, full window over the landscape artwork, or inside a portrait device frame. */
function LabStage({
  settings,
  backdrop,
  isPanelOpen,
  children,
}: {
  settings: LabSettings;
  backdrop: Backdrop;
  isPanelOpen: boolean;
  children: ReactNode;
}) {
  const flat = backdrop === "artwork" ? undefined : BACKDROP_COLOR[backdrop];
  if (settings.layout === "mobile") {
    return (
      <DeviceFrame settings={settings} backdrop={flat} isPanelOpen={isPanelOpen}>
        {children}
      </DeviceFrame>
    );
  }
  return (
    <>
      {!flat && <div className={bgStyles.bg} style={backdropStyle(settings.backdropBlur)} aria-hidden />}
      <div className={styles.stage}>{children}</div>
    </>
  );
}

export default function LabPage() {
  const [settings, setSettings] = useState<LabSettings>(INITIAL);
  // Restored after mount (localStorage does not exist during the server render),
  // and saved only once restored, so the defaults never overwrite a saved session.
  const [isRestored, setIsRestored] = useState(false);
  useEffect(() => {
    setSettings(loadLabSettings(INITIAL));
    setIsRestored(true);
  }, []);
  useEffect(() => {
    if (isRestored) saveLabSettings(settings);
  }, [settings, isRestored]);
  const [backdrop, setBackdrop] = useState<Backdrop>("artwork");
  const [inventoryData, setInventoryData] = useState<AssetInventory | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [isPanelOpen, setIsPanelOpen] = useState(true);

  const set = useCallback(
    <K extends keyof LabSettings>(key: K) =>
      (value: LabSettings[K]) =>
        setSettings((s) => ({ ...s, [key]: value })),
    [],
  );

  // A new rig or look means a new load.
  useEffect(() => {
    setIsLoading(true);
    setInventoryData(null);
  }, [settings.presenter, settings.look]);

  // The background artwork is chosen by the root's data-theme (page.module.css).
  // Set directly rather than through applyTheme, which would also change the
  // kiosk's remembered theme; restored on leaving.
  useEffect(() => {
    const root = document.documentElement;
    const previous = root.dataset.theme;
    root.dataset.theme = settings.theme;
    return () => {
      if (previous === undefined) delete root.dataset.theme;
      else root.dataset.theme = previous;
    };
  }, [settings.theme]);

  const onReady = useCallback(() => setIsLoading(false), []);
  const onMoveLight = useCallback((name: LightName, position: [number, number, number]) => {
    setSettings((s) => {
      const rig = structuredClone(s.rig);
      rig.studio[s.theme].placement[name].position = position;
      return { ...s, rig };
    });
  }, []);

  // Recorded in the export, so the values come with the scene they were judged in.
  const { rig: _rig, editLight: _editLight, showHandles: _showHandles, ...sceneSettings } = settings;
  const exportScene = { ...sceneSettings, backdrop };

  const scene = (
    <LabScene
      settings={settings}
      onInventory={setInventoryData}
      onReady={onReady}
      onSelectLight={set("editLight")}
      onMoveLight={onMoveLight}
    />
  );
  const isKiosk = settings.look === "kiosk";

  return (
    <main
      className={styles.root}
      style={backdrop === "artwork" ? undefined : { background: BACKDROP_COLOR[backdrop] }}
    >
      <LabStage settings={settings} backdrop={backdrop} isPanelOpen={isPanelOpen}>
        {scene}
      </LabStage>
      {isLoading && <div className={styles.loading}>Loading {settings.look} rig…</div>}

      <button type="button" className={styles.toggle} onClick={() => setIsPanelOpen((open) => !open)}>
        {isPanelOpen ? "Hide panel" : "Show panel"}
      </button>

      {isPanelOpen && (
        <aside className={styles.panel}>
          <h1>Avatar lab</h1>
          <div className={styles.row}>
            <button
              type="button"
              onClick={() => {
                setBackdrop("artwork");
                setSettings((s) => ({ ...s, ...REFERENCE_V1 }));
              }}
            >
              Reference v1
            </button>
            <button
              type="button"
              onClick={() => {
                setBackdrop("artwork");
                setSettings((s) => ({ ...s, ...REFERENCE_V2 }));
              }}
            >
              Reference v2 (face)
            </button>
            <button type="button" onClick={() => setSettings((s) => ({ ...s, ...KIOSK_PHASE_A, ...KIOSK_TODAY }))}>
              Kiosk today
            </button>
            <button
              type="button"
              title="Forget the saved session and start from the defaults"
              onClick={() => {
                clearLabSettings();
                setSettings(INITIAL);
              }}
            >
              Reset lab
            </button>
          </div>

          <Choice
            label="Layout"
            value={settings.layout}
            options={[
              ["desktop", "Desktop (full window)"],
              ["mobile", "Mobile frame"],
            ]}
            onChange={set("layout")}
            hint="Mobile uses the kiosk's portrait layout: portrait artwork, avatar in the bottom 79%."
          />
          {settings.layout === "mobile" && <MobileControls settings={settings} set={set} />}
          <Choice
            label="Presenter"
            value={settings.presenter}
            options={PRESENTERS.map((id) => [id, AVATARS[id].label.en] as const)}
            onChange={set("presenter")}
          />
          <Choice
            label="Look"
            value={settings.look}
            options={[
              ["raw", "Raw asset"],
              ["kiosk", "Kiosk (corrected)"],
            ]}
            onChange={set("look")}
            hint={
              isKiosk
                ? "AvatarModel: material fixes, skin lift, makeup, hair cut-offs, shadows, blink."
                : "The file exactly as exported. No corrections, no blink, plain loop."
            }
          />
          <Choice
            label="Lights"
            value={settings.lights}
            options={[
              ["off", "None"],
              ["studio", "Kiosk studio"],
              ["editable", "Kiosk studio (editable)"],
              ["reference", "Reference v1"],
            ]}
            onChange={set("lights")}
          />
          <Choice
            label="Environment (what she reflects)"
            value={settings.environment}
            options={[
              ["room", "Neutral room"],
              ["panels", "Studio panels"],
              ["backdrop", "Backdrop image"],
              ["reference", "Reference lobby"],
            ]}
            onChange={set("environment")}
            hint={ENVIRONMENT_HINT[settings.environment]}
          />
          {settings.environment === "backdrop" && (
            <Choice
              label="Backdrop environment strength"
              value={String(settings.backdropStrength)}
              options={[
                ["0.5", "0.5"],
                ["1", "1"],
                ["1.5", "1.5"],
                ["2", "2"],
                ["3", "3"],
              ]}
              onChange={(value) => set("backdropStrength")(Number(value))}
            />
          )}
          <Choice
            label="Theme (studio + artwork)"
            value={settings.theme}
            options={[
              ["dark", "Dark"],
              ["light", "Light"],
            ]}
            onChange={set("theme")}
          />
          <Choice
            label="Backdrop"
            value={backdrop}
            options={[
              ["artwork", "Artwork"],
              ["grey", "Grey"],
              ["white", "White"],
              ["black", "Black"],
            ]}
            onChange={setBackdrop}
          />
          <Slider
            label="Backdrop blur (depth of field, px)"
            value={settings.backdropBlur}
            min={0}
            max={12}
            step={0.5}
            onChange={set("backdropBlur")}
            disabled={backdrop !== "artwork"}
          />
          <Choice
            label="Tone mapping"
            value={settings.tone}
            options={[
              ["aces", "ACES (kiosk)"],
              ["agx", "AgX"],
              ["neutral", "Neutral"],
              ["linear", "Linear"],
              ["none", "None"],
            ]}
            onChange={set("tone")}
          />
          <Choice
            label="Surface view"
            value={settings.view}
            options={[
              ["lit", "Lit"],
              ["albedo", "Albedo"],
              ["normals", "Normals"],
              ["wireframe", "Wireframe"],
            ]}
            onChange={set("view")}
          />
          <Choice
            label="Pose"
            value={settings.pose}
            options={[
              ["tpose", "T-pose"],
              ["breathing", "Breathing"],
              ["listening", "Listening"],
              ["talking", "Talking"],
            ]}
            disabled={isKiosk ? ["tpose"] : []}
            onChange={set("pose")}
            hint={isKiosk && settings.pose === "tpose" ? "The kiosk look always animates." : undefined}
          />
          <Choice
            label="Camera"
            value={settings.camera}
            options={[
              ["kiosk", "Kiosk framing"],
              ["editable", "Kiosk framing (editable)"],
              ["orbit-face", "Orbit: face"],
              ["orbit-body", "Orbit: body"],
              ["orbit-wide", "Orbit: wide (lights)"],
            ]}
            onChange={set("camera")}
            hint={settings.camera === "kiosk" ? undefined : "Drag to orbit, scroll to zoom, right-drag to pan."}
          />

          <RigEditor
            rig={settings.rig}
            onChange={set("rig")}
            theme={settings.theme}
            presenter={settings.presenter}
            layout={settings.layout}
            editLight={settings.editLight}
            onEditLight={set("editLight")}
            showHandles={settings.showHandles}
            onShowHandles={set("showHandles")}
            scene={exportScene}
            visible={{
              lights: settings.lights === "editable",
              camera: settings.camera === "editable",
              panels: settings.environment === "panels",
            }}
            onShowEdits={() =>
              setSettings((s) => ({ ...s, look: "kiosk", lights: "editable", environment: "panels", camera: "editable" }))
            }
          />

          <PhaseAPanel value={settings} onChange={(phaseA) => setSettings((s) => ({ ...s, ...phaseA }))} />

          <InventoryPanel data={inventoryData} />
        </aside>
      )}
    </main>
  );
}
