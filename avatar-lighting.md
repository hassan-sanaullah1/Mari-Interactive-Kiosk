# Avatar lighting and materials

What every lighting and material value does, and which one to change for a given symptom. All values live in `frontend/components/avatar/tuning.ts` unless stated. Values below match the file as of 2026-10-15; if you tune in the IDE, this page will drift, so check the file when in doubt.

## How it fits together

There are two lighting setups, one per theme (`STUDIO.dark`, `STUDIO.light`). Each holds six lights, an ambient tint, reflection panels and shadow settings. When the theme changes, the scene eases every value from one setup to the other (`LERP_SPEED`), so the change looks like the room's light sweeping across her.

On top of that, each presenter carries per-theme knobs (`lightThemeLighting`, `darkThemeLighting`: exposure, ambient, fill, environment) and per-material corrections (roughness, reflection, alpha cut, makeup).

Axes used throughout: +x is camera-right, +y is up, +z is toward the camera (negative z is behind her).

## The six lights

| Light | Type | Light theme | Role |
|---|---|---|---|
| `key` | directional | camera-left, high, in front | main light; sets where shadows fall |
| `fill` | directional | camera-right, lower | softens the key's shadows |
| `top` | spot | overhead | sheen on the crown of her hair |
| `rim` | spot | camera-right, behind her | bright edge that separates her from the backdrop |
| `kick` | spot | low, in front | floor bounce on jaw and forearms |
| `face` | spot | centred, in front | soft lift on the face |

Each light has three separate sets of values. Changing the wrong one is the most common reason an edit "does nothing".

### 1. Colour: `STUDIO.<theme>.colors`

A light's colour is multiplied with the surface colour it hits, so it tints everything that light reaches. Current light-theme values:

| Light | Value | Effect |
|---|---|---|
| `key` | `#fffcfa` | near-white, very slightly warm; the main colour cast on her front |
| `fill` | `#fffcfa` | colour in her shadow side |
| `top` | `#fffbf3` | colour of the hair sheen |
| `rim` | `#d8e6ff` | pale cool; the only cool light, so it reads as an edge |
| `kick` | `#000000` | black means this light adds nothing right now |
| `face` | `#fffdfc` | tint of the face lift |
| `ambientColor` | `#fffefd` | tints the ambient light, which reaches every surface equally |

To shift the whole look warmer or cooler, move all of them together. One light moved alone looks like a coloured spotlight.

### 2. Placement: `STUDIO.<theme>.placement`

`position: [x, y, z]` decides which side of a feature is lit, not how bright. Moving the key from camera-left to camera-right flips which cheek is in shadow.

| Light | Position | Spot settings |
|---|---|---|
| `key` | `[-2.4, 2.9, 2.2]` | none (directional) |
| `fill` | `[2.6, 1.6, 1.4]` | none (directional) |
| `top` | `[0, 3.2, 0.8]` | angle 0.5, penumbra 1 |
| `rim` | `[2, 2.4, -2.2]` | angle 0.8, penumbra 1 |
| `kick` | `[0.3, 0.35, 2.2]` | angle 1, penumbra 1 |
| `face` | `[0, 2, 1.2]` | angle 0.22, penumbra 0.8, distance 2 |

Spot settings:

- `angle`: half-width of the light cone in radians. Smaller is a tighter spotlight.
- `penumbra`: 0 is a hard-edged cone, 1 is fully soft falloff.
- `distance`: how far the light reaches before fading to nothing (0 means unlimited).
- `decay`: how fast it fades with distance. 2 is physical inverse-square, used on every spot.

The `intensity` inside `placement` is only the value the light starts with. The frame loop overwrites it straight away from `states` below, so editing it alone changes nothing visible.

`kick` sits at height 0.35, below her head (about 1.45) but not under her chin. At height -1.2 it lit her nostrils and under-brows from below, which reads as a torch held under the face.

### 3. Brightness: `STUDIO.<theme>.states`

This is the real brightness control. The scene eases each light toward the value for the current conversation state.

| State | key | fill | rim | kick | top |
|---|---|---|---|---|---|
| idle | 2.2 | 0.7 | 2.5 | 1.7 | 1.1 |
| listening | 2.4 | 0.75 | 2.7 | 1.7 | 1.15 |
| thinking | 2.05 | 0.75 | 2.3 | 1.6 | 1 |
| speaking | 2.4 | 0.75 | 2.9 | 1.8 | 1.25 |

- Scale all five together to make her brighter or dimmer overall.
- Change the ratio of `key` to `fill` to change contrast. A higher ratio looks more sculpted, a lower one looks softer and flatter.
- `face` has no entry here. Its brightness comes from `placement.face.intensity` (0.9 in light, 1.6 in dark).
- `VOICE_BOOST` adds a little extra to `key`, `rim` and `kick` while she speaks, so the light breathes with her voice. `fill` and `top` take none.
- Light-theme `fill` here is the final value. It is multiplied by the rig's `lightThemeLighting.fill`, which is why that knob stays near 1.

## Per-theme knobs: `lightThemeLighting` / `darkThemeLighting`

Female light theme: `{ exposure: 0.8, ambient: 0.2, fill: 1, environment: 0.75 }`.
Male light theme: `{ exposure: 0.98, ambient: 0.5, fill: 1.15, environment: 1.2 }`.
Dark baseline (`DARK_LIGHTING`): `{ exposure: 1, ambient: 0.3, fill: 1, environment: 1 }`.

### `exposure`

Scales the light of the whole scene before the renderer's tone curve (ACES filmic) squeezes it into screen range. It is not a plain brightness slider.

- Raise it: bright areas get pushed into the part of the curve that rolls off toward white, so skin loses saturation and looks washed out.
- Lower it: colours stay richer, but very dark saturated colours (lipstick, deep shadows) lose headroom and go grey or black.

It is the broadest knob in the rig and the easiest to overcorrect. Fixing "too bright" with exposure alone tends to trade washed-out highlights for crushed shadows.

### `ambient`

A flat light added equally to every surface, regardless of which way it faces. It creates no shading by itself; it only raises the darkest areas.

- Raise it: shadows fill in, contrast drops, she looks flatter.
- Lower it: shadows deepen and she looks more three-dimensional. Too low and the shadow side loses all detail.

`exposure` scales everything including highlights. `ambient` only lifts the floor.

### `fill`

A multiplier on the `fill` light's per-state brightness. At 1 it does nothing. It exists so a presenter can brighten or dim its fill without touching the shared studio.

### `environment`

Scales how strongly the reflection panels (below) show up as reflections on glossy surfaces. It does almost nothing to matte skin or cloth. It matters mostly for the eyes, nails and teeth, combined with `materialEnvIntensity`.

## Reflection panels: `STUDIO.<theme>.environment`

Invisible rectangles that exist only to be reflected in shiny surfaces. They are not drawn and do not light her the way the six lights do. Light theme:

| Panel | Intensity | Colour | Represents |
|---|---|---|---|
| window wall | 2.6 | `#fffcfb` | camera-left, tall |
| ceiling cove | 2 | `#fff6e6` | flat overhead |
| marble floor | 1.5 | `#fffcf9` | flat below |
| dark side | 0.3 | `#5a6478` | the dim room on camera-right |

- `resolution` is 512 (256 in dark). Higher means less banding in sharp reflections such as the eye highlight.
- The dim fourth panel is deliberate. An environment made only of bright panels wraps every shiny surface in uniform white and flattens it.

## Shadows: `STUDIO.<theme>.shadow`

Shadow mapping is switched on once for the whole canvas (`shadows` on `<Canvas>`) and cannot be toggled per theme without rebuilding the renderer. So both themes have shadows and the per-theme dial is `intensity`. Only the `key` light casts.

| Field | Light | Dark | What it does |
|---|---|---|---|
| `intensity` | 0.2 | 0.55 | 0 to 1; how dark the cast shadow is. 0 is invisible, 1 is black. The one to change for stronger or weaker shadows. |
| `mapSize` | 2048 | 2048 | shadow texture resolution; sharper edges, more GPU cost. Drop to 1024 first if frame rate suffers. |
| `bias` | -0.0002 | -0.0002 | depth offset that prevents speckle ("shadow acne"); too far and shadows detach from the object. |
| `normalBias` | 0.01 | 0.01 | same purpose, offset along the surface; works better on curved surfaces like a face. |
| `extent` | 1 | 1 | half-width in metres of the shadow area around her. |
| `targetY` | 1.1 | 1.1 | height the shadow area aims at (her torso). |

There is no ground under her, so every visible shadow is a self-shadow: hair on the forehead, nose on the cheek, chin on the neck. Every mesh has `castShadow` and `receiveShadow` on (`AvatarModel.tsx`). Opaque materials use `shadowSide = BackSide` there, because the model marks every material double-sided and three.js would otherwise cast shadows from both faces, which makes a closed surface shadow itself.

## Materials (female presenter, `RIG_TUNING.female`)

Material names come from the `dress2.glb` export. The file has one base-colour texture per material and no normal, roughness or ambient-occlusion maps, so each material has exactly one roughness number and one reflection number for its whole surface. These two values are the whole shine vocabulary.

### `materialRoughness`

0 is mirror-sharp, 1 is fully matte.

| Material | Value | Why |
|---|---|---|
| `Kameez:lambert2` | 0.5 | export omits it; glTF would default to fully matte (no highlight) |
| `pasted__lambert10` (green dupatta) | 0.9 | kept dull on purpose; 0.5 made it look like satin |
| `lambert11` (eyes) | 0.08 | a cornea is wet; this is what produces the catchlight |
| `lambert16` (nails) | 0.25 | lacquered |
| `lambert9`, `lambert10`, `lambert15` (teeth, tongue) | 0.35 | enamel and wet tongue |
| `lambert20` to `lambert23` (hair cards) | 0.32 | tighter highlight so the top light lays a sheen on the crown |

### `materialEnvIntensity`

How much of the reflection panels a material shows. 1 is the default.

| Material | Value | Why |
|---|---|---|
| `lambert11` (eyes) | 2.2 | bright enough reflection to read as a catchlight |
| `lambert16` (nails) | 1.8 | glossy lacquer |
| `lambert9`, `lambert10` (teeth) | 0.8 | slightly below default |
| `lambert14`, `lambert17`, `lambert12` (face, arms, legs) | 0.55 | at 1 the skin reads as plastic |
| `lambert20` to `lambert23` (hair cards) | 0.15 | near-black hair reflecting a bright room reads as grey sheen |
| `lambert19` (scalp) | 0.1 | same reason |
| `pasted__lambert10` (dupatta) | 0.2 | shine comes from reflection as well as roughness, so it is damped on both |

Eyes need both values together. Roughness makes the highlight tight; the reflection value makes it bright enough to see.

### `alphaTest`

Cut-off that discards nearly transparent pixels on hair cards.

- `lambert19` (scalp): 0.35. Its colour sits just over the "mask-only" threshold, so it was taking the soft cut and showing a haze at the hairline.
- `lambert20` to `lambert23` (hair cards): 0.22. At this screen size each pixel averages strand and gap, so the default cut leaves a translucent grey fringe. Too high and strands break into spikes.

### Skin: `skinMaterials`, `skinEmissive`, `skinRoughness`

- `skinMaterials` (`lambert14`, `lambert17`, `lambert12`): the materials that get the emissive lift.
- `skinEmissive` (0.25): a self-lit boost driven from the skin's own texture, so it brightens skin without erasing its shading. It is independent of every light, which means it lands equally on lit and shadow sides and carries the texture's own warm tone. It is per presenter, not per theme, so changing it also changes dark mode.
- `skinRoughness` (null): keep the export's value.

### Other per-material fields

- `materialTint`: per-material brightness scale. Empty for her. The male rig uses it to pull his brighter textures down to her level.
- `materialSpecular`: forces specular strength. Empty for her; the male rig uses it to tame hair sheen.
- `backLight` (`rim: 1, kick: 1`): per-presenter multiplier on the two back lights. Both stay 1 for her; the male rig sets both to 0 because they mirror off his hair and clothing.

## Makeup: `makeupDesaturation`

Current value: `0.01` (female). Not a light at all. When the model loads, a one-time pass reads the face texture and desaturates the red and pink pixels (lipstick, cheek flush) by this fraction. 0 keeps the original colour, 1 turns them fully grey. It runs before any lighting, so it is the correct control for lip and cheek colour.

Do not use `exposure` or `ambient` to fix lip colour. Lowering exposure crushes dark reds toward grey, which looks like the makeup was removed. The male rig has no makeup material, so his value (0.2) is never used.

## Picking the right value

| Symptom | Change | Not this |
|---|---|---|
| too bright or too dim overall | all `states` values together | `exposure` alone |
| too flat | lower `ambient`; raise key-to-fill ratio | `exposure` |
| too harsh | raise `ambient` or `fill`; lower `shadow.intensity` | `key` position |
| too warm or too cool | all light colours together | one light's colour |
| wrong side is lit | `key.position` | `key` brightness |
| shadows too dark or light | `shadow.intensity` | `ambient` |
| lips or cheeks not red enough | `makeupDesaturation` | any lighting value |
| eyes have no catchlight | `materialEnvIntensity` and `materialRoughness` on `lambert11` | `face` light |
| hair looks silver instead of black | `materialEnvIntensity` on hair cards | hair roughness |
| fringe looks like translucent wisps | `alphaTest` on hair cards | hair roughness |
| green dupatta too shiny | roughness up, `materialEnvIntensity` down on `pasted__lambert10` | lights |
| edit "does nothing" | you probably edited `placement.<light>.intensity`; edit `states` | |

## What lighting cannot fix

These are properties of the 3D file. Only a re-export fixes them.

1. **No normal maps.** Surfaces are geometrically smooth: no pores, lip relief, cloth weave or hair-strand definition.
2. **No roughness maps.** One roughness per material, so lips, eyelids and cheeks share a number.
3. **No ambient-occlusion maps.** Nothing darkens in the nostrils, eye sockets, under the chin or where hair meets scalp. This is most of the missing depth, and a baked AO map on the head would help more than any light change.
4. **Makeup is painted into the face texture**, so it can't be relit or removed. The load-time desaturation only works around it.
5. **Hair is four alpha-card materials plus a scalp card.** At this screen size they blur into haze, which `alphaTest` only partly hides.
6. **Every material is double-sided**, which costs rendering time and is why `shadowSide` is needed.
7. **File size.** `dress2.glb` is about 70 MB (52 MB gzipped), mostly one large texture.
