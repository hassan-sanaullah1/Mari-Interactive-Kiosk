#!/usr/bin/env python3
"""Measure how each avatar's mouth actually moves under real Audio2Face frames.

Viewers judge lipsync on a handful of things: lips sealing on m/b/p, the mouth
sitting closed between words, how far it opens on vowels, rounding on oo/w,
how much teeth show, and left/right symmetry. This puts numbers on each, for
the female rig (which reads as natural) and the male rig, so a difference can
be found without anyone having to describe what looks wrong.

Both heads are the same Character Creator base mesh (identical UV layout, so
an exact one-to-one vertex match), which means the landmarks below are the SAME
anatomical points on both rigs: they are chosen once on the female and mapped
to the male by UV.

Weights are applied exactly as the browser applies them: A2F value x rig gain x
per-shape trim, clamped to [0, 1] (frontend/lib/blendshapePlayer.ts and
a2fMorphs.ts; calibration from frontend/components/avatar/tuning.ts).

Usage:
    # 1. record real A2F frames, each avatar with its own voice and its own
    #    request settings (needs the NIM and TTS keys from .env)
    python scripts/lipsync_audit.py record frames.json
    # 2. compare the rigs
    python scripts/lipsync_audit.py audit frames.json
    # 3. fit the male's per-shape multipliers to the female's lip outline
    python scripts/lipsync_audit.py fit frames.json
    # 4. check a fitted setting on live NIM output (variants file: see record())
    python scripts/lipsync_audit.py record frames2.json variants.json
"""

from __future__ import annotations

import json
import os
import struct
import sys

import numpy as np
from scipy.spatial import cKDTree

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MODELS = os.path.join(ROOT, "frontend", "public", "models")
RIGS = {
    "female": dict(glb="girl15.glb", head="lambert12", upper_teeth="upper_teeth", lower_teeth="lower_teeth"),
    "male": dict(glb="male_inital12.glb", head="lambert5", upper_teeth="Std_Upper_Teeth", lower_teeth="Std_Lower_Teeth"),
}
# Browser calibration (tuning.ts): both rigs use gain 0.9 with jawOpen trimmed to 0.375.
GAIN = {"female": (0.9, {"jawopen": 0.375}), "male": (0.9, {"jawopen": 0.375})}
SENTENCES = {
    "ur": ["السلام علیکم، میں ماری انرجیز کا ڈیجیٹل اسسٹنٹ ہوں۔ آج میں آپ کی کیا مدد کر سکتا ہوں؟",
           "ماری انرجیز پاکستان کی سب سے بڑی گیس پیدا کرنے والی کمپنیوں میں سے ایک ہے، اور اس کا صدر دفتر اسلام آباد میں ہے۔",
           "ہماری کمپنی بجلی، کھاد اور صنعت کے لیے قدرتی گیس فراہم کرتی ہے۔",
           "براہ مہربانی بتائیں، کیا آپ ہمارے منصوبوں کے بارے میں مزید معلومات چاہتے ہیں؟"],
    "en": ["Hello and welcome! I am the digital assistant for Mari Energies. How may I help you today?",
           "Mari Energies is one of the biggest gas producers in Pakistan, with its main office in Islamabad.",
           "We supply natural gas for power, fertilizer and industry, and we keep exploring for more.",
           "We value safety, fresh ideas and five new wells, and we would love to move forward with you."],
}

# ── GLB reading ──────────────────────────────────────────────────────────────
_CT = {5120: np.int8, 5121: np.uint8, 5122: np.int16, 5123: np.uint16, 5125: np.uint32, 5126: np.float32}
_NC = {"SCALAR": 1, "VEC2": 2, "VEC3": 3, "VEC4": 4}


class Glb:
    def __init__(self, path: str):
        data = open(path, "rb").read()
        _, _, length = struct.unpack("<4sII", data[:12])
        off = 12
        while off < length:
            clen, ctype = struct.unpack("<I4s", data[off : off + 8])
            chunk = data[off + 8 : off + 8 + clen]
            if ctype == b"JSON":
                self.j = json.loads(chunk)
            else:
                self.bin = chunk
            off += 8 + clen

    def _view(self, bv, off, ct, count, n):
        v = self.j["bufferViews"][bv]
        return np.frombuffer(self.bin, _CT[ct], count * n, v.get("byteOffset", 0) + off).reshape(count, n)

    def read(self, i: int) -> np.ndarray:
        a = self.j["accessors"][i]
        n = _NC[a["type"]]
        x = (self._view(a["bufferView"], a.get("byteOffset", 0), a["componentType"], a["count"], n).astype(float)
             if "bufferView" in a else np.zeros((a["count"], n)))
        if "sparse" in a:
            sp = a["sparse"]
            idx = self._view(sp["indices"]["bufferView"], sp["indices"].get("byteOffset", 0),
                             sp["indices"]["componentType"], sp["count"], 1)[:, 0]
            x = x.copy()
            x[idx] = self._view(sp["values"]["bufferView"], sp["values"].get("byteOffset", 0),
                                a["componentType"], sp["count"], n)
        return x


def load_rig(name: str) -> dict:
    cfg = RIGS[name]
    g = Glb(os.path.join(MODELS, cfg["glb"]))
    mesh = next(m for m in g.j["meshes"] if (m.get("extras") or {}).get("targetNames"))
    names = [n.lower() for n in mesh["extras"]["targetNames"]]
    parts = {}
    for key in ("head", "upper_teeth", "lower_teeth"):
        p = next(p for p in mesh["primitives"] if g.j["materials"][p["material"]]["name"] == cfg[key])
        parts[key] = dict(pos=g.read(p["attributes"]["POSITION"]), uv=g.read(p["attributes"]["TEXCOORD_0"]),
                          d=np.stack([g.read(t["POSITION"]) for t in p["targets"]]))
    return dict(name=name, names=names, parts=parts)


# ── Landmarks (picked on the female, mapped to the male by UV) ───────────────
def landmarks(ref: dict) -> dict:
    """Vertex index sets on the reference (female) rig."""
    H = ref["parts"]["head"]
    P, D = H["pos"], H["d"]
    jaw_dy = -D[ref["names"].index("jawopen")][:, 1]
    upper_teeth = ref["parts"]["upper_teeth"]["pos"]
    teeth_front_z = upper_teeth[:, 2].max()
    lip_region = np.zeros(len(P), bool)
    for n in ("mouthrollupper", "mouthrolllower", "mouthfunnel", "mouthpucker"):
        m = np.linalg.norm(D[ref["names"].index(n)], axis=1)
        lip_region |= m > 0.4 * m.max()
    mouth_y = P[lip_region, 1].mean()
    front = P[:, 2] > teeth_front_z            # lip surface, not the inside of the mouth
    near = np.abs(P[:, 1] - mouth_y) < 0.03
    sets = {}
    band = np.abs(P[:, 0]) < 0.0025
    sets["upper_lip"] = np.where(band & front & near & (jaw_dy < 0.003))[0]
    sets["lower_lip"] = np.where(band & front & near & (jaw_dy > 0.010))[0]
    # The same pair 10mm either side of the midline: viewers see the whole lip
    # line, and a shape can part the centre while the sides stay pressed.
    for side, sx in (("l", 1), ("r", -1)):
        sb = np.abs(P[:, 0] - sx * 0.010) < 0.0025
        sets[f"upper_lip_{side}"] = np.where(sb & front & near & (jaw_dy < 0.003))[0]
        sets[f"lower_lip_{side}"] = np.where(sb & front & near & (jaw_dy > 0.008))[0]
    # The whole visible lip outline (upper and lower lip, corner to corner): what
    # the shape-per-sound comparison and the fit below work on.
    sets["lip_outline"] = np.where(lip_region & (P[:, 2] > teeth_front_z - 0.003))[0]
    lr = np.where(lip_region)[0]
    sets["corner_left"] = np.array([lr[P[lr, 0].argmax()]])
    sets["corner_right"] = np.array([lr[P[lr, 0].argmin()]])
    ut = ref["parts"]["upper_teeth"]["pos"]
    sets["upper_incisor"] = np.where((np.abs(ut[:, 0]) < 0.004) & (ut[:, 2] > ut[:, 2].max() - 0.004))[0]
    lt = ref["parts"]["lower_teeth"]["pos"]
    sets["lower_incisor"] = np.where((np.abs(lt[:, 0]) < 0.004) & (lt[:, 2] > lt[:, 2].max() - 0.004))[0]
    return sets


def map_sets(ref: dict, rig: dict, sets: dict) -> dict:
    """Same anatomical vertices on `rig`, via exact UV match per part."""
    out = {}
    part_of = {"upper_incisor": "upper_teeth", "lower_incisor": "lower_teeth"}
    maps = {}
    for part in ("head", "upper_teeth", "lower_teeth"):
        d, idx = cKDTree(rig["parts"][part]["uv"]).query(ref["parts"][part]["uv"])
        if d.max() > 1e-6:
            raise SystemExit(f"{part}: UV layouts differ — not the same base mesh, landmarks can't be mapped")
        maps[part] = idx
    for k, v in sets.items():
        out[k] = maps[part_of.get(k, "head")][v]
    return out


# ── Applying A2F frames the way the browser does ─────────────────────────────
def browser_weights(rig: dict, a2f_names: list[str], frames: np.ndarray) -> np.ndarray:
    gain, trims = GAIN[rig["name"]]
    W = np.zeros((len(frames), len(rig["names"])))
    for i, n in enumerate(a2f_names):
        n = n.lower()
        if n in rig["names"]:
            W[:, rig["names"].index(n)] += frames[:, i] * gain * trims.get(n, 1.0)
    return np.clip(W, 0, 1)


def measure(rig: dict, sets: dict, W: np.ndarray) -> dict:
    """Per-frame lip metrics in mm, plus the rig's rest mouth width."""
    H, UT, LT = rig["parts"]["head"], rig["parts"]["upper_teeth"], rig["parts"]["lower_teeth"]
    def pos(part, idx):  # (frames, verts, 3)
        return part["pos"][idx][None] + np.einsum("fs,svk->fvk", W, part["d"][:, idx])
    ul, ll = pos(H, sets["upper_lip"]), pos(H, sets["lower_lip"])
    cl, cr = pos(H, sets["corner_left"])[:, 0], pos(H, sets["corner_right"])[:, 0]
    ui = pos(UT, sets["upper_incisor"])[:, :, 1].min(1)
    li = pos(LT, sets["lower_incisor"])[:, :, 1].max(1)
    upper_lip_low, lower_lip_top = ul[:, :, 1].min(1), ll[:, :, 1].max(1)
    side_gaps = []
    for side in ("l", "r"):
        su, sl = pos(H, sets[f"upper_lip_{side}"]), pos(H, sets[f"lower_lip_{side}"])
        side_gaps.append(su[:, :, 1].min(1) - sl[:, :, 1].max(1))
    rest_cl, rest_cr = H["pos"][sets["corner_left"][0]], H["pos"][sets["corner_right"][0]]
    width0 = np.linalg.norm(rest_cl - rest_cr)
    return dict(
        width0=width0 * 1000,
        gap=(upper_lip_low - lower_lip_top) * 1000,
        width=np.linalg.norm(cl - cr, axis=1) * 1000,
        gap_side=np.mean(side_gaps, axis=0) * 1000,
        # forward motion of the lips themselves (mean over both lip sets)
        protrude=(np.concatenate([ul, ll], 1)[:, :, 2].mean(1)
                  - np.concatenate([H["pos"][sets["upper_lip"]], H["pos"][sets["lower_lip"]]])[:, 2].mean()) * 1000,
        upper_teeth=np.maximum(0, upper_lip_low - np.maximum(ui, lower_lip_top)) * 1000,
        lower_teeth=np.maximum(0, np.minimum(upper_lip_low, li) - lower_lip_top) * 1000,
        asym=np.abs(np.linalg.norm(cl - rest_cl, axis=1) - np.linalg.norm(cr - rest_cr, axis=1)) * 1000,
    )


# ── Audit ────────────────────────────────────────────────────────────────────
def audit(frames_path: str) -> None:
    data = json.load(open(frames_path))
    rigs = {n: load_rig(n) for n in RIGS}
    sets_f = landmarks(rigs["female"])
    sets = {"female": sets_f, "male": map_sets(rigs["female"], rigs["male"], sets_f)}
    print(f"landmarks: {len(sets_f['upper_lip'])} upper-lip / {len(sets_f['lower_lip'])} lower-lip vertices at the "
          f"midline, corners, incisor edges\n")

    def run(rig_name: str, voice: str) -> dict:
        clips = [v for k, v in data.items() if k.startswith(voice + "_")]
        names = clips[0]["names"]
        F = np.concatenate([np.array(c["frames"])[:, 1:] for c in clips])
        W = browser_weights(rigs[rig_name], names, F)
        out = measure(rigs[rig_name], sets[rig_name], W)
        out["W"], out["F"], out["names"] = W, F, names
        rest = measure(rigs[rig_name], sets[rig_name], np.zeros((1, len(rigs[rig_name]["names"]))))
        out["rest"] = {k: float(np.ravel(v)[0]) for k, v in rest.items()}
        return out

    # Same frames on both rigs isolates the rig; own-voice frames is what visitors see.
    same_f, same_m = run("female", "male"), run("male", "male")
    own_f, own_m = run("female", "female"), same_m

    def pct(x): return f"{x:5.1f}%"
    def rel(a, b): return f"{a:6.2f} vs {b:6.2f}"

    for title, F, M in (("SAME A2F frames on both rigs (male voice) — the rig's own effect", same_f, same_m),
                        ("WHAT VISITORS SEE — each avatar with its own voice and settings", own_f, own_m)):
        wf, wm = F["width0"], M["width0"]
        nf, nm = lambda x: 100 * x / wf, lambda x: 100 * x / wm      # % of each rig's mouth width
        print(f"== {title}")
        print(f"   mouth width at rest: female {wf:.1f}mm, male {wm:.1f}mm   (all sizes below in % of own mouth width)")
        print(f"   rest pose: lip gap female {nf(F['rest']['gap']):+.2f}%, male {nm(M['rest']['gap']):+.2f}%; "
              f"upper teeth showing female {nf(F['rest']['upper_teeth']):.2f}%, male {nm(M['rest']['upper_teeth']):.2f}%")
        rows = []
        # 1. closures: frames where the female seals
        seal_f = nf(F["gap"]) < 0.5 if title.startswith("SAME") else None
        if seal_f is not None:
            rows.append(("1 m/b/p closures: when HER lips seal, his gap",
                         f"{np.median(nm(M['gap'][seal_f])):+.2f}% (median); sealed in {100*np.mean(nm(M['gap'][seal_f]) < 0.5):.0f}% of {seal_f.sum()} frames"))
        rows.append(("1 share of speech frames with lips sealed", rel(100*np.mean(nf(F['gap']) < 0.5), 100*np.mean(nm(M['gap']) < 0.5)) + "  (%)"))
        # 2. near-silence
        jf = F["W"][:, rigs['female']['names'].index('jawopen')]; jm = M["W"][:, rigs['male']['names'].index('jawopen')]
        qf, qm = jf < 0.03, jm < 0.03
        rows.append(("2 quiet frames: lip gap (median)", rel(np.median(nf(F['gap'][qf])), np.median(nm(M['gap'][qm])))))
        rows.append(("2 quiet frames: upper teeth showing (median)", rel(np.median(nf(F['upper_teeth'][qf])), np.median(nm(M['upper_teeth'][qm])))))
        # 3. opening
        rows.append(("3 lip gap p50 / p90 over speech", f"{np.percentile(nf(F['gap']),50):5.2f}/{np.percentile(nf(F['gap']),90):5.2f} vs {np.percentile(nm(M['gap']),50):5.2f}/{np.percentile(nm(M['gap']),90):5.2f}"))
        rows.append(("3 side lip gap p50 / p90 (10mm off centre)", f"{np.percentile(nf(F['gap_side']),50):5.2f}/{np.percentile(nf(F['gap_side']),90):5.2f} vs {np.percentile(nm(M['gap_side']),50):5.2f}/{np.percentile(nm(M['gap_side']),90):5.2f}"))
        rows.append(("3 lips overlapping (gap < -1%) share of frames", rel(100*np.mean(nf(F['gap']) < -1), 100*np.mean(nm(M['gap']) < -1)) + "  (%)"))
        # 4. rounding
        rows.append(("4 mouth narrowing p90 (rounding)", rel(np.percentile(-nf(F['width']-wf), 90), np.percentile(-nm(M['width']-wm), 90))))
        rows.append(("4 lip protrusion p90", rel(np.percentile(nf(F['protrude']), 90), np.percentile(nm(M['protrude']), 90))))
        rows.append(("4 mouth widening p90 (spread/smile)", rel(np.percentile(nf(F['width']-wf), 90), np.percentile(nm(M['width']-wm), 90))))
        # 5. teeth
        rows.append(("5 upper teeth showing mean / p90", f"{np.mean(nf(F['upper_teeth'])):5.2f}/{np.percentile(nf(F['upper_teeth']),90):5.2f} vs {np.mean(nm(M['upper_teeth'])):5.2f}/{np.percentile(nm(M['upper_teeth']),90):5.2f}"))
        rows.append(("5 lower teeth showing mean / p90", f"{np.mean(nf(F['lower_teeth'])):5.2f}/{np.percentile(nf(F['lower_teeth']),90):5.2f} vs {np.mean(nm(M['lower_teeth'])):5.2f}/{np.percentile(nm(M['lower_teeth']),90):5.2f}"))
        # 6. symmetry
        rows.append(("6 left/right corner mismatch p90", rel(np.percentile(nf(F['asym']), 90), np.percentile(nm(M['asym']), 90))))
        w = max(len(r[0]) for r in rows)
        print(f"   {'check':{w}s}   female vs male")
        for a, b in rows:
            print(f"   {a:{w}s}   {b}")
        print()


# ── Lip outline: does he make the same mouth SHAPE as her, sound by sound ────
# A2F mouth/jaw channels the fit may rescale (PascalCase, as the NIM names them).
FIT_SHAPES = [
    "JawForward", "JawLeft", "JawRight", "JawOpen", "MouthClose", "MouthFunnel", "MouthPucker",
    "MouthLeft", "MouthRight", "MouthSmileLeft", "MouthSmileRight", "MouthFrownLeft", "MouthFrownRight",
    "MouthDimpleLeft", "MouthDimpleRight", "MouthStretchLeft", "MouthStretchRight", "MouthRollLower",
    "MouthRollUpper", "MouthShrugLower", "MouthShrugUpper", "MouthPressLeft", "MouthPressRight",
    "MouthLowerDownLeft", "MouthLowerDownRight", "MouthUpperUpLeft", "MouthUpperUpRight",
]
RAW_OFFSETS = (-0.02, 0.02, 0.04, 0.06, 0.08)    # lipOpenOffset values recorded with all FIT_SHAPES at 1.0
# Lip roll/press add to the pressing that round 1 fixed: left free, the fit pushes
# them to ~1.4x for the f/v tuck and lip overlap climbs back to 7%. 1.1x keeps it
# at today's level for most of the f/v gain.
ROLL_PRESS = {"MouthRollLower", "MouthRollUpper", "MouthPressLeft", "MouthPressRight"}
ROLL_PRESS_CAP = 1.1


def outline(rig: dict, sets: dict, W: np.ndarray) -> np.ndarray:
    """(frames, verts, 3) lip-outline movement from rest, in % of the rig's mouth width."""
    H = rig["parts"]["head"]
    c = sets["corner_left"][0], sets["corner_right"][0]
    width0 = np.linalg.norm(H["pos"][c[0]] - H["pos"][c[1]])
    return np.einsum("fs,svk->fvk", W, H["d"][:, sets["lip_outline"]]) * 100 / width0


def sound_groups(rig: dict, W: np.ndarray, gap_pct: np.ndarray) -> dict:
    """Frames by what her mouth is doing — the reference for each comparison."""
    w = lambda n: W[:, rig["names"].index(n)]
    closed = gap_pct < 0.5
    return {
        "closed (m/b/p)": closed,
        "lower-lip tuck (f/v)": (w("mouthrolllower") > 0.2) & ~closed,
        "rounded (oo/w)": w("mouthpucker") + w("mouthfunnel") > 0.3,
        "spread (ee)": (w("mouthstretchleft") + w("mouthstretchright") + w("mouthsmileleft") + w("mouthsmileright")) / 2 > 0.25,
        "open (ah)": gap_pct > np.percentile(gap_pct, 75),
        "all speech": np.ones(len(W), bool),
    }


def _clips(data: dict, variant: str) -> list:
    return [(k[len(variant) + 1:], v) for k, v in data.items() if k.startswith(variant + "_")]


def _aligned(data: dict, *variants: str) -> list[np.ndarray]:
    """Frames of several variants recorded on the same audio, clip by clip, trimmed to equal length."""
    per = [dict(_clips(data, v)) for v in variants]
    out = [[] for _ in variants]
    for clip in per[0]:
        n = min(len(p[clip]["frames"]) for p in per)
        for i, p in enumerate(per):
            out[i].append(np.array(p[clip]["frames"])[:n, 1:])
    return [np.concatenate(o) for o in out]


def fit(frames_path: str) -> None:
    """Fit the male's per-shape multipliers so his lip outline follows hers frame by frame.

    Same audio (his voice) on both: her rig with the NIM defaults (what she runs
    with) is the target; his rig with each raw recording (all mouth shapes at 1.0)
    is linear in the multipliers, so a bounded least-squares solve gives them.
    """
    from scipy.optimize import lsq_linear
    data = json.load(open(frames_path))
    names = next(iter(data.values()))["names"]
    lower = [n.lower() for n in names]
    rf, rm = load_rig("female"), load_rig("male")
    sets_f = landmarks(rf)
    sets_m = map_sets(rf, rm, sets_f)

    def look(rig, sets, F):
        W = browser_weights(rig, names, F)
        meas = measure(rig, sets, W)
        return W, meas, outline(rig, sets, W)

    raws = [f"maleraw{o:+.2f}" for o in RAW_OFFSETS]
    Fdef, Fb, *Fraws = _aligned(data, "maledef", "male", *raws)
    Wt, Mt, Ot = look(rf, sets_f, Fdef)
    groups = sound_groups(rf, Wt, 100 * Mt["gap"] / Mt["width0"])

    # The NIM's default multiplier per shape: default output / raw output, same audio and offset.
    fit_idx = [names.index(n) for n in FIT_SHAPES if n in names]
    defaults = {}
    for i in fit_idx:
        r = Fraws[0][:, i]
        ok = np.abs(r) > 0.02
        defaults[names[i]] = float(np.median(Fdef[ok, i] / r[ok])) if ok.sum() > 20 else 1.0

    def report(label, F, mult=None):
        W, Mm, Om = look(rm, sets_m, F)
        d = np.sqrt(((Om - Ot) ** 2).sum(-1).mean(-1))          # per-frame outline distance
        gm = 100 * Mm["gap"] / Mm["width0"]
        row = "  ".join(f"{d[g].mean():5.2f}" for g in groups.values())
        seal = 100 * np.mean(gm[groups["closed (m/b/p)"]] < 0.5)
        guard = (f"overlap {100*np.mean(gm < -1):4.1f}%  sealed {seal:4.0f}%  "
                 f"spread p90 {np.percentile(100*(Mm['width']-Mm['width0'])/Mm['width0'], 90):4.2f}")
        print(f"   {label:22s} {row}   | {guard}")
        return d[groups["all speech"]].mean()

    print("lip-outline distance from HER mouth shape, % of mouth width (lower = more like her)")
    print(f"   {'':22s} " + "  ".join(f"{k.split()[0][:5]:>5s}" for k in groups) + "   | round-1 guards")
    print(f"   {'frames per group':22s} " + "  ".join(f"{g.sum():5d}" for g in groups.values()))
    gt = 100 * Mt["gap"] / Mt["width0"]
    print(f"   {'her (the reference)':22s} " + "  ".join(f"{0:5.2f}" for _ in groups) +
          f"   | overlap {100*np.mean(gt < -1):4.1f}%  sealed  100%  spread p90 "
          f"{np.percentile(100*(Mt['width']-Mt['width0'])/Mt['width0'], 90):4.2f}")
    report("male now (b)", Fb)
    report("male, NIM defaults", Fdef)

    # Weighting: sealing and the f/v tuck are where viewers look hardest.
    wts = np.ones(len(Fdef))
    wts[groups["closed (m/b/p)"]] = 3
    wts[groups["lower-lip tuck (f/v)"]] = 2
    wts[groups["rounded (oo/w)"]] = 3
    gain, trims = GAIN["male"]
    head_m = rm["parts"]["head"]
    cm = sets_m["corner_left"][0], sets_m["corner_right"][0]
    width0_m = np.linalg.norm(head_m["pos"][cm[0]] - head_m["pos"][cm[1]])
    cf = sets_f["corner_left"][0], sets_f["corner_right"][0]
    width0_f = np.linalg.norm(rf["parts"]["head"]["pos"][cf[0]] - rf["parts"]["head"]["pos"][cf[1]])
    gap_pairs = [("upper_lip", "lower_lip"), ("upper_lip_l", "lower_lip_l"), ("upper_lip_r", "lower_lip_r")]

    def gaps(rig, sets, W, width0):
        """Lip gap at the centre and 10mm either side, ABSOLUTE (rest pose included):
        his lips sit closer together at rest than hers, which outline movement can't see."""
        H = rig["parts"]["head"]
        out = []
        for u, l in inner_edges(rig, sets):
            dy = H["d"][:, u, 1].mean(1) - H["d"][:, l, 1].mean(1)
            g0 = H["pos"][u, 1].mean() - H["pos"][l, 1].mean()
            out.append((g0 + W @ dy) * 100 / width0)
        return np.stack(out, 1)                                   # (frames, 3)

    def inner_edges(rig, sets):
        """Where the lips meet: each rig's own lowest upper-lip and highest lower-lip vertices."""
        P = rig["parts"]["head"]["pos"]
        return [(sets[u][np.argsort(P[sets[u], 1])[:3]], sets[l][np.argsort(-P[sets[l], 1])[:3]])
                for u, l in gap_pairs]

    Gt = gaps(rf, sets_f, Wt, width0_f)
    results = []
    for off, Fr in zip(RAW_OFFSETS, Fraws):
        cols, gcols, keep = [], [], []
        fixed = Fr.copy()
        for i in fit_idx:
            n = lower[i]
            if n not in rm["names"]:
                continue
            r = rm["names"].index(n)
            a = Fr[:, i] * gain * trims.get(n, 1.0)
            D = head_m["d"][r, sets_m["lip_outline"]] * 100 / width0_m
            cols.append(a[:, None, None] * D[None])
            dy = [(head_m["d"][r, u, 1].mean() - head_m["d"][r, l, 1].mean()) * 100 / width0_m
                  for u, l in inner_edges(rm, sets_m)]
            gcols.append(a[:, None] * np.array(dy)[None])
            keep.append(i)
            fixed[:, i] = 0
        # Left/right pairs share one value: separate ones fit his small sculpt
        # asymmetries and come out lopsided (UpperUp 1.33 vs 0.99), a crooked mouth.
        groups_of = {}
        for j, i in enumerate(keep):
            groups_of.setdefault(names[i].replace("Left", "").replace("Right", ""), []).append(j)
        tied = list(groups_of.values())
        cols = [sum(cols[j] for j in g) for g in tied]
        gcols = [sum(gcols[j] for j in g) for g in tied]
        Wfix = browser_weights(rm, names, fixed)
        base = outline(rm, sets_m, Wfix)
        gbase = gaps(rm, sets_m, Wfix, width0_m)
        first = [keep[g[0]] for g in tied]
        lo = np.array([0.4 * defaults[names[i]] for i in first])
        hi = np.array([(ROLL_PRESS_CAP if names[i] in ROLL_PRESS else 2.0) * defaults[names[i]] for i in first])
        sw = np.sqrt(wts)
        for gw in (50, 100):
            # gap rows scaled to count like gw outline vertices each
            X = np.concatenate([np.stack([(c * sw[:, None, None]).ravel() for c in cols], 1),
                                np.stack([(g * sw[:, None] * np.sqrt(gw)).ravel() for g in gcols], 1)])
            y = np.concatenate([((Ot - base) * sw[:, None, None]).ravel(),
                                ((Gt - gbase) * sw[:, None] * np.sqrt(gw)).ravel()])
            sol = np.empty(len(keep))
            for g, v in zip(tied, lsq_linear(X, y, bounds=(lo, hi)).x):
                sol[g] = v
            F = Fr.copy()
            for i, v in zip(keep, sol):
                F[:, i] *= v
            label = f"fit {off:+.2f} gap-w {gw}"
            score = report(label, F)
            W, Mm, _ = look(rm, sets_m, F)
            gm = 100 * Mm["gap"] / Mm["width0"]
            ok = np.mean(gm < -1) <= 0.065 and np.mean(gm[groups["closed (m/b/p)"]] < 0.5) >= 0.90
            results.append((not ok, score, label, off, {names[i]: round(float(v), 2) for i, v in zip(keep, sol)}))

    results.sort(key=lambda r: (r[0], r[1]))
    bad, _, label, off, mult = results[0]
    print(f"\nbest{' (NO setting passes the guards!)' if bad else ''}: {label}")
    for n, v in mult.items():
        print(f"   {n:22s} {v:5.2f}   ({v / defaults[n]:4.2f}x the NIM default {defaults[n]:.2f})")
    print(json.dumps({"malec": {"face": {"lipOpenOffset": off}, "bs": mult}}))


# ── Recording ────────────────────────────────────────────────────────────────
def record(out_path: str, extra_path: str | None = None) -> None:
    """Each sentence is synthesized once and sent to the NIM under several settings,
    so every variant of a clip is on identical audio:
      female / male     what each avatar runs with today (its own voice)
      maledef           his voice, NIM defaults (what the female rig is tuned against)
      maleraw±0.00      his voice, all mouth shapes at 1.0, per lipOpenOffset — for `fit`
      + any variants from extra_path: {"name": {"face": {...}, "bs": {...}}}
    """
    import asyncio
    import subprocess
    sys.path.insert(0, ROOT)
    from dotenv import load_dotenv
    load_dotenv(os.path.join(ROOT, ".env"), override=False)
    from server import config as C
    from server.avatar.a2f_client import A2F_BLENDSHAPE_MULTIPLIERS, A2F_FACE_PARAMS, A2FClient
    from server.providers.tts import UpliftTTS
    extra = json.load(open(extra_path)) if extra_path else {}
    raw = {n: 1.0 for n in FIT_SHAPES}

    async def main():
        client = A2FClient(os.environ.get("A2F_AUDIT_URL", "127.0.0.1:52000"))
        out = {}

        async def run(key, pcm, face, bs):
            names, frames = [], []

            async def collect(n, f):
                if n:
                    names.extend(n)
                frames.extend(f)

            s = await client.open_stream(16000, collect, face_params=face, bs_multipliers=bs)
            await s.write(pcm)
            await s.finish()
            out[key] = {"names": names, "frames": frames}
            print(key, len(frames), "frames", flush=True)

        for avatar in ("female", "male"):
            for lang, sents in SENTENCES.items():
                voice = C.UPLIFT_VOICE_MALE if avatar == "male" else (C.UPLIFT_VOICE_EN if lang == "en" else C.UPLIFT_VOICE)
                tts = UpliftTTS(voice=voice, lang=lang)
                for k, text in enumerate(sents):
                    audio, _ = await tts.synthesize(text)
                    pcm = subprocess.run(["ffmpeg", "-v", "error", "-i", "pipe:0", "-f", "s16le", "-ac", "1",
                                          "-ar", "16000", "pipe:1"], input=audio, capture_output=True, check=True).stdout
                    variants = {avatar: (A2F_FACE_PARAMS.get(avatar), A2F_BLENDSHAPE_MULTIPLIERS.get(avatar))}
                    if avatar == "male":
                        variants["maledef"] = (None, None)
                        for o in RAW_OFFSETS:
                            variants[f"maleraw{o:+.2f}"] = ({"lipOpenOffset": o}, raw)
                        for name, v in extra.items():
                            variants[name] = (v.get("face"), v.get("bs"))
                    for name, (face, bs) in variants.items():
                        await run(f"{name}_{lang}_{k}", pcm, face, bs)
        json.dump(out, open(out_path, "w"))
        await client.close()

    asyncio.run(main())


if __name__ == "__main__":
    cmds = {"record": record, "audit": audit, "fit": fit}
    if len(sys.argv) < 3 or sys.argv[1] not in cmds:
        raise SystemExit(__doc__)
    cmds[sys.argv[1]](*sys.argv[2:])
