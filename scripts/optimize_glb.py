#!/usr/bin/env python3
"""Shrink the avatar .glb by removing data the kiosk provably never reads.

girl15.glb is ~56 MB, and the kiosk downloads all of it before MARI can appear.
Two things dominate that, and neither is needed in full:

  1. ANIMATION (32.8 MB of 54.8 MB binary). One clip, "CINEMA_4D_Main", 902
     frames at 30 fps. 2922 of its 3252 channels drive the 975 baked cloth
     joints, which is why it is so much larger than the rig it belongs to.
     AvatarModel.tsx only ever plays three windows of it — breathing 119-241,
     listening 300-393, talking 558-780 — and never seeks outside them, so
     roughly half the keyframes are downloaded and never sampled.

  2. ROTATION PRECISION (3.5 MB). What is left after (1) is 96% cloth: 974
     joints stored as float32 at 30 fps. Quaternions need nowhere near that —
     glTF's normalized int16 encoding, which three.js dequantises in the loader,
     holds one to within 0.067 degrees. Halving them is invisible and costs
     nothing at runtime.

     Two neighbouring ideas were measured and REJECTED. Quantising TRANSLATION
     the same way is not possible: normalized shorts decode into [-1,1] and these
     curves reach 141, with no per-channel scale in glTF to borrow. Resampling
     the cloth to 15 fps reconstructs the dropped keys up to 46 mm off, which is
     real flutter rather than rounding. Precision is free; range and keyframes
     are not.

  3. MORPH TARGET NORMALS (9.8 MB). Every one of the 51 ARKit blendshapes
     carries a NORMAL delta alongside its POSITION delta, at ~100x the size
     (9.84 MB vs 0.10 MB) because the normals are stored uncompressed while the
     positions are quantised. Dropping them makes three.js light the blended
     face from the base mesh normals instead.

None of this resamples or re-times the animation: every keyframe the player can
reach is still a keyframe, geometry and textures are copied byte for byte, and
the 51 blendshape names and their POSITION deltas are untouched. Only the stored
precision of the cloth curves changes, by less than the rig can express.

Usage:
    python scripts/optimize_glb.py IN.glb OUT.glb [--keep-morph-normals]

Re-run it whenever the avatar is re-exported, and re-check KEEP_WINDOWS below
against the female rig's loop windows in frontend/components/avatar/models.ts if
the clip is re-authored: they are the one thing here that encodes an assumption
about the animation rather than reading it out of the file.

This script is aimed at girl15.glb specifically, and there is nothing for it to
do on male1.glb: that rig is 31 MB of textures against 1.0 MB of animation, has
no cloth sim to requantise and no morph targets to strip normals from, so all
three passes together would take under a megabyte off it.
"""

from __future__ import annotations

import argparse
import gzip
import json
import os
import shutil
import struct
import sys
from collections import OrderedDict

JSON_CHUNK = 0x4E4F534A
BIN_CHUNK = 0x004E4942

FPS = 30.0

# Must mirror the FEMALE rig's loop windows in
# frontend/components/avatar/models.ts. Frames outside these windows are never
# sampled: each segment is a self-contained loop and transitions crossfade
# between them rather than playing through. Given as inclusive frame numbers IN
# THE CLIP'S OWN FRAME RATE, which is read off the key spacing (see clip_fps) —
# girl15 is 30fps, male_inital03 is 24fps.
#
# These are the DEFAULT because girl15 is what this script was written for. Any
# other rig has its own windows cut from its own curves and MUST pass them with
# --keep-windows: trimming one rig's animation to another's frame numbers keeps
# the wrong keys, and the failure is silent until the body seeks into a frame
# that is no longer in the file.
KEEP_WINDOWS = [
    (119, 241),  # breathing
    (300, 393),  # listening
    (558, 780),  # talking
]

# Component type -> (struct char, byte size)
CTYPE = {
    5120: ("b", 1), 5121: ("B", 1), 5122: ("h", 2),
    5123: ("H", 2), 5125: ("I", 4), 5126: ("f", 4),
}
NCOMP = {"SCALAR": 1, "VEC2": 2, "VEC3": 3, "VEC4": 4, "MAT4": 16}


def read_glb(path):
    with open(path, "rb") as f:
        magic, version, _total = struct.unpack("<III", f.read(12))
        if magic != 0x46546C67:
            raise SystemExit(f"{path}: not a GLB")
        chunks = {}
        while True:
            head = f.read(8)
            if len(head) < 8:
                break
            length, ctype = struct.unpack("<II", head)
            chunks[ctype] = f.read(length)
    return json.loads(chunks[JSON_CHUNK], object_pairs_hook=OrderedDict), chunks.get(BIN_CHUNK, b"")


def write_glb(path, gltf, binary):
    js = json.dumps(gltf, separators=(",", ":")).encode()
    js += b" " * (-len(js) % 4)              # chunks must be 4-byte aligned
    binary += b"\x00" * (-len(binary) % 4)
    total = 12 + 8 + len(js) + (8 + len(binary) if binary else 0)
    with open(path, "wb") as f:
        f.write(struct.pack("<III", 0x46546C67, 2, total))
        f.write(struct.pack("<II", len(js), JSON_CHUNK))
        f.write(js)
        if binary:
            f.write(struct.pack("<II", len(binary), BIN_CHUNK))
            f.write(binary)


def accessor_bytes(gltf, binary, idx):
    """Raw elements of an accessor as a list of tuples, honouring bufferView
    byteStride (interleaved accessors are read element by element, not as a
    flat slice)."""
    acc = gltf["accessors"][idx]
    n = acc["count"]
    ncomp = NCOMP[acc["type"]]
    ch, csize = CTYPE[acc["componentType"]]
    elem = ncomp * csize
    if "bufferView" not in acc:
        return [(0,) * ncomp] * n, acc
    bv = gltf["bufferViews"][acc["bufferView"]]
    base = bv.get("byteOffset", 0) + acc.get("byteOffset", 0)
    stride = bv.get("byteStride") or elem
    fmt = "<" + ch * ncomp
    return [struct.unpack_from(fmt, binary, base + i * stride) for i in range(n)], acc


def quant_short(x: float) -> int:
    """Float in [-1,1] -> glTF normalized signed short."""
    return max(-32767, min(32767, int(round(x * 32767.0))))


class BinBuilder:
    """Accumulates the new BIN chunk, keeping each bufferView 4-byte aligned."""

    def __init__(self):
        self.parts = []
        self.size = 0

    def add(self, data: bytes) -> int:
        pad = -self.size % 4
        if pad:
            self.parts.append(b"\x00" * pad)
            self.size += pad
        offset = self.size
        self.parts.append(data)
        self.size += len(data)
        return offset

    def build(self) -> bytes:
        return b"".join(self.parts)


def clip_fps(gltf, binary) -> float:
    """The clip's frame rate, from the spacing of its densest keyframe curve.

    Not assumed: male_inital03.glb is the same animation as male_inital02.glb
    re-exported at 24fps, and trimming it by 30fps frame numbers keeps the wrong
    keys with no error until the body seeks into one that is gone.
    """
    longest = []
    for anim in gltf.get("animations", []):
        for samp in anim["samplers"]:
            if gltf["accessors"][samp["input"]]["count"] > len(longest):
                longest = [t for (t,) in accessor_bytes(gltf, binary, samp["input"])[0]]
    if len(longest) < 3:
        return FPS
    steps = sorted(b - a for a, b in zip(longest, longest[1:]))
    return float(round(1.0 / steps[len(steps) // 2]))


def optimize(src, dst, drop_morph_normals=True, quantize=True,
             keep_windows=None, trim_anim=True):
    gltf, binary = read_glb(src)
    before = len(binary)
    fps = clip_fps(gltf, binary)
    print(f"  clip frame rate     : {fps:g} fps (windows are read in these frames)")

    # ---- 1. trim animation keyframes to the windows the player can reach ----
    # Keys are selected by their POSITION IN THE CURVE, not by matching their
    # timestamp against a computed frame time. Two things make the latter wrong:
    # the clip's first key sits at t=1/FPS rather than 0, and the stored floats
    # do not round-trip exactly (frame 557 is 18.566668 in the file against a
    # computed 18.566667). Comparing floats silently dropped keys that were in
    # range, which showed up as a 1.35-unit jump on a cloth joint mid-window.
    #
    # So: derive the frame index of each key from the curve itself, and keep a
    # frame if any window contains it. One frame of margin each side, because a
    # crossfade samples slightly past a window edge and the loop-entry search
    # compares against the frame before the window starts.
    windows = KEEP_WINDOWS if keep_windows is None else keep_windows

    def wanted(frame_idx: int) -> bool:
        # trim_anim False keeps every key — for a rig whose animation is a small
        # fraction of the file and whose windows are not worth encoding here.
        if not trim_anim:
            return True
        return any(a - 1 <= frame_idx <= b + 1 for a, b in windows)

    anim_kept = anim_total = 0
    new_acc = []          # accessors rebuilt as (data, accessor-json)
    acc_map = {}          # old accessor idx -> new idx
    quantised = [0, 0]    # [rotation channels, translation channels]

    # A sampler carries no path of its own; only the channel that points at it
    # knows whether it drives rotation or translation. Only cloth joints are
    # quantised — the 110 body joints are 0.58 MB in total, so there is nothing
    # to win there and the skeleton keeps full float precision.
    channel_path = {}
    cloth_nodes = {i for i, nd in enumerate(gltf.get("nodes", []))
                   if "a_cloth" in str(nd.get("name", ""))}
    for anim_ in gltf.get("animations", []):
        for ch_ in anim_["channels"]:
            if ch_["target"]["node"] in cloth_nodes:
                channel_path[id(anim_["samplers"][ch_["sampler"]])] = ch_["target"]["path"]

    def emit(data: bytes, acc_json) -> int:
        new_acc.append((data, acc_json))
        return len(new_acc) - 1

    for anim in gltf.get("animations", []):
        for samp in anim["samplers"]:
            in_idx, out_idx = samp["input"], samp["output"]
            times, tacc = accessor_bytes(gltf, binary, in_idx)
            values, vacc = accessor_bytes(gltf, binary, out_idx)
            anim_total += len(times)

            if len(times) <= 2:
                # A 2-key constant channel is already minimal; keep as-is.
                sel = list(range(len(times)))
            else:
                # Frame index from the key's own time, rounded to the nearest
                # frame — robust to the export's float error and to the clip not
                # starting at t=0.
                t0 = times[0][0]
                sel = [i for i, (t,) in enumerate(times)
                       if wanted(int(round((t - t0) * fps)) + int(round(t0 * fps)))]
                if len(sel) < 2:
                    sel = [0, len(times) - 1]
            anim_kept += len(sel)

            key = ("in", in_idx, tuple(sel))
            if key not in acc_map:
                tch, _ = CTYPE[tacc["componentType"]]
                data = b"".join(struct.pack("<" + tch, times[i][0]) for i in sel)
                ta = OrderedDict(componentType=tacc["componentType"], count=len(sel),
                                 type="SCALAR",
                                 min=[min(times[i][0] for i in sel)],
                                 max=[max(times[i][0] for i in sel)])
                acc_map[key] = emit(data, ta)
            samp["input"] = acc_map[key]

            # Output stride: CUBICSPLINE stores in/value/out tangents per key.
            per = 3 if samp.get("interpolation") == "CUBICSPLINE" else 1
            vch, _ = CTYPE[vacc["componentType"]]
            ncomp = NCOMP[vacc["type"]]
            fmt = "<" + vch * ncomp
            rows = [values[i * per + k] for i in sel for k in range(per)]

            path = channel_path.get(id(samp))
            if (quantize and vacc["componentType"] == 5126
                    and path == "rotation"
                    and samp.get("interpolation") != "CUBICSPLINE"):
                # Rotations are unit quaternions, so they already live in [-1,1]
                # and glTF's "normalized short" encoding applies directly.
                # Translations are not bounded, so they are scaled into that range
                # by the node's own TRS: the curve is divided by its peak magnitude
                # and the node keeps that factor. Both are exactly the encodings
                # glTF defines for animation output, and three.js dequantises them
                # in the loader — there is no runtime cost and no shader change.
                if path == "rotation":
                    data = b"".join(
                        struct.pack("<4h", *(quant_short(c) for c in row)) for row in rows)
                    va = OrderedDict(componentType=5122, count=len(rows),
                                     type="VEC4", normalized=True)
                    samp["output"] = emit(data, va)
                    quantised[0] += 1
                    continue
                # Translation is deliberately NOT quantised. A normalized short
                # output decodes into [-1,1] and is read straight as metres, but
                # these curves reach 141 (the rig is authored in centimetres under
                # a 0.01-scaled root), so the encoding cannot represent them.
                # glTF has no per-channel scale to borrow, and folding one into
                # the node's own scale would rescale its children and its mesh
                # too. So translation keeps float32 and only rotation is halved.

            out = [struct.pack(fmt, *row) for row in rows]
            va = OrderedDict(componentType=vacc["componentType"], count=len(rows),
                             type=vacc["type"])
            samp["output"] = emit(b"".join(out), va)

    # ---- 2. drop morph target NORMAL (and TANGENT) deltas ----
    dropped = 0
    if drop_morph_normals:
        for mesh in gltf.get("meshes", []):
            for prim in mesh.get("primitives", []):
                for target in prim.get("targets", []):
                    for attr in ("NORMAL", "TANGENT"):
                        if attr in target:
                            del target[attr]
                            dropped += 1

    # ---- 3. copy every accessor still referenced, then rewrite the buffer ----
    # Anything not reachable from meshes/skins/animations after the edits above
    # (the removed morph normals, the discarded keyframes) is simply not copied.
    referenced = set()

    def mark(i):
        if i is not None:
            referenced.add(i)

    for mesh in gltf.get("meshes", []):
        for prim in mesh.get("primitives", []):
            for i in prim.get("attributes", {}).values():
                mark(i)
            mark(prim.get("indices"))
            for target in prim.get("targets", []):
                for i in target.values():
                    mark(i)
    for skin in gltf.get("skins", []):
        mark(skin.get("inverseBindMatrices"))

    builder = BinBuilder()
    old_to_new = {}
    out_accessors = []

    for old in sorted(referenced):
        acc = gltf["accessors"][old]
        if "bufferView" in acc:
            bv = gltf["bufferViews"][acc["bufferView"]]
            ncomp = NCOMP[acc["type"]]
            ch, csize = CTYPE[acc["componentType"]]
            elem = ncomp * csize
            base = bv.get("byteOffset", 0) + acc.get("byteOffset", 0)
            stride = bv.get("byteStride") or elem
            if stride == elem:
                data = binary[base:base + elem * acc["count"]]
            else:  # de-interleave
                data = b"".join(binary[base + i * stride: base + i * stride + elem]
                                for i in range(acc["count"]))
            new_acc_json = OrderedDict(
                (k, v) for k, v in acc.items()
                if k not in ("bufferView", "byteOffset")
            )
            offset = builder.add(data)
            new_acc_json["bufferView"] = None   # patched below
            new_acc_json["_off"] = offset
            new_acc_json["_len"] = len(data)
            new_acc_json["_target"] = bv.get("target")
        else:
            new_acc_json = OrderedDict(acc)

        # Sparse accessors (the 551 morph POSITION deltas here) hold their data in
        # two *separate* bufferViews referenced from accessor.sparse, not in
        # accessor.bufferView — which may be absent entirely. Those views have to
        # be copied and repointed too; leaving the original indices behind makes
        # them address the old table, and three.js then builds a typed array from
        # the wrong view and throws "Invalid typed array length".
        if "sparse" in new_acc_json:
            sparse = OrderedDict(new_acc_json["sparse"])
            for part in ("indices", "values"):
                sub = OrderedDict(sparse[part])
                bvs = gltf["bufferViews"][sub["bufferView"]]
                start = bvs.get("byteOffset", 0) + sub.get("byteOffset", 0)
                if part == "indices":
                    _c, csz = CTYPE[sub["componentType"]]
                    nbytes = sparse["count"] * csz
                else:
                    _c, csz = CTYPE[new_acc_json["componentType"]]
                    nbytes = sparse["count"] * NCOMP[new_acc_json["type"]] * csz
                sub["_off"] = builder.add(binary[start:start + nbytes])
                sub["_len"] = nbytes
                sub.pop("byteOffset", None)
                sparse[part] = sub
            new_acc_json["sparse"] = sparse

        old_to_new[old] = len(out_accessors)
        out_accessors.append(new_acc_json)

    # images keep their bytes verbatim
    image_views = {}
    for img in gltf.get("images", []):
        if "bufferView" in img:
            bv = gltf["bufferViews"][img["bufferView"]]
            start = bv.get("byteOffset", 0)
            data = binary[start:start + bv["byteLength"]]
            image_views[img["bufferView"]] = (builder.add(data), len(data))

    # animation accessors built in step 1
    for data, acc_json in new_acc:
        acc_json = acc_json
        acc_json["_off"] = builder.add(data)
        acc_json["_len"] = len(data)
        acc_json["_target"] = None

    # ---- assemble bufferViews ----
    buffer_views = []

    def view_for(off, length, target):
        bvj = OrderedDict(buffer=0, byteOffset=off, byteLength=length)
        if target is not None:
            bvj["target"] = target
        buffer_views.append(bvj)
        return len(buffer_views) - 1

    final_accessors = []
    for acc_json in out_accessors:
        a = OrderedDict((k, v) for k, v in acc_json.items() if not k.startswith("_"))
        if "_off" in acc_json:
            a["bufferView"] = view_for(acc_json["_off"], acc_json["_len"], acc_json["_target"])
        if "sparse" in acc_json:
            sp = OrderedDict(acc_json["sparse"])
            for part in ("indices", "values"):
                sub = OrderedDict((k, v) for k, v in sp[part].items() if not k.startswith("_"))
                sub["bufferView"] = view_for(sp[part]["_off"], sp[part]["_len"], None)
                sp[part] = sub
            a["sparse"] = sp
        final_accessors.append(a)
    anim_base = len(final_accessors)
    for _data, acc_json in new_acc:
        a = OrderedDict((k, v) for k, v in acc_json.items() if not k.startswith("_"))
        a["bufferView"] = view_for(acc_json["_off"], acc_json["_len"], None)
        final_accessors.append(a)

    for img in gltf.get("images", []):
        if "bufferView" in img:
            off, length = image_views[img["bufferView"]]
            img["bufferView"] = view_for(off, length, None)

    # ---- repoint every accessor reference ----
    for mesh in gltf.get("meshes", []):
        for prim in mesh.get("primitives", []):
            prim["attributes"] = OrderedDict(
                (k, old_to_new[v]) for k, v in prim.get("attributes", {}).items())
            if "indices" in prim:
                prim["indices"] = old_to_new[prim["indices"]]
            if "targets" in prim:
                prim["targets"] = [OrderedDict((k, old_to_new[v]) for k, v in t.items())
                                   for t in prim["targets"]]
    for skin in gltf.get("skins", []):
        if "inverseBindMatrices" in skin:
            skin["inverseBindMatrices"] = old_to_new[skin["inverseBindMatrices"]]
    for anim in gltf.get("animations", []):
        for samp in anim["samplers"]:
            samp["input"] += anim_base
            samp["output"] += anim_base

    gltf["accessors"] = final_accessors
    gltf["bufferViews"] = buffer_views
    new_bin = builder.build()
    gltf["buffers"] = [OrderedDict(byteLength=len(new_bin))]

    write_glb(dst, gltf, new_bin)

    print(f"  animation keyframes : {anim_total} -> {anim_kept} "
          f"({100 * anim_kept / max(anim_total, 1):.0f}%)")
    print(f"  quantised channels  : {quantised[0]} rotation, {quantised[1]} translation")
    print(f"  morph deltas dropped: {dropped}")
    print(f"  binary              : {before / 1e6:.1f} MB -> {len(new_bin) / 1e6:.1f} MB")

    # Ship the gzipped copy alongside it. The app requests THIS file (see
    # components/avatar/state.ts): a static .gz is served with a real
    # Content-Length, where Next's on-the-fly gzip can only answer chunked.
    gz_path = dst + ".gz"
    with open(dst, "rb") as fin, gzip.GzipFile(gz_path, "wb", compresslevel=9, mtime=0) as fout:
        shutil.copyfileobj(fin, fout)
    print(f"  wrote {os.path.basename(gz_path)}   : {os.path.getsize(gz_path) / 1e6:.1f} MB "
          f"(what the browser actually downloads)")
    return 0


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("src")
    ap.add_argument("dst")
    ap.add_argument("--keep-morph-normals", action="store_true",
                    help="keep morph target NORMAL deltas (larger file, "
                         "marginally different face shading)")
    ap.add_argument("--no-quantize", action="store_true",
                    help="keep cloth rotation/translation as float32")
    ap.add_argument("--keep-windows", metavar="A-B,C-D,...",
                    help="inclusive frame windows to keep, in the clip's own "
                         "frame rate, overriding the female rig's. REQUIRED "
                         "for any rig other than girl15 — see KEEP_WINDOWS.")
    ap.add_argument("--no-trim-anim", action="store_true",
                    help="keep every animation keyframe (skips pass 1)")
    a = ap.parse_args()
    windows = None
    if a.keep_windows:
        windows = []
        for part in a.keep_windows.split(","):
            lo, hi = part.split("-")
            windows.append((int(lo), int(hi)))
    return optimize(a.src, a.dst, drop_morph_normals=not a.keep_morph_normals,
                    quantize=not a.no_quantize, keep_windows=windows,
                    trim_anim=not a.no_trim_anim)


if __name__ == "__main__":
    sys.exit(main())
