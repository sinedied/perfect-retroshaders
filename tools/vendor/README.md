# vendor

Third-party shaders, kept **only** as benchmark and comparison references.

- Not covered by this repository's MIT licence. Each file is governed by its own
  licence, reproduced in its header.
- Not edited. Keep them byte-identical to upstream so measurements stay honest and
  comparable.
- Not shipped as part of this project's shader set.

| File | Author / licence | Why it's here |
|---|---|---|
| `pixellate.glsl` | Fes, 2011–2012 | **The performance baseline.** 30 SFU slots, and it ships on the target handheld while holding 60fps — so it defines the budget every shader here is measured against. |
| `lcd1x.glsl` | Gigaherz (public domain), edited by jdgleaver — GPL-2.0-or-later | **The LCD baseline `lcd-perfect` is answering.** Two `sin()` calls, point-sampled with no prefilter, `BRIGHTEN_SCANLINES` 1–32 / `BRIGHTEN_LCD` 1–12 inverse-sense knobs, no gamma, no brightness compensation. |
| `lcd3x.glsl` | Gigaherz (public domain), cg2glsl output | `lcd1x`'s ancestor, with the "colour separation" `lcd1x` drops. Its stripe is a 2-phase R/G-vs-B split (`vec3(0, 0, -π)`), which is **not** luminance neutral — the counter-example for the 3-phase stripe. |
| `sharp-shimmerless-grid.glsl` | zadpos — public domain | **Prior art for the core idea.** Treats pixels as ideal rectangles and computes the exact area an input pixel occupies on an output pixel, transcendental-free. `lcd-perfect` uses the separable antiderivative form of the same maths. |
| `dmg_dot_matrix.glsl` | Status_Librarian_313, modified by sinedied | The naive `step()`-on-`mod()` grid with a **post-blend output gamma** — the exact construction AGENTS.md measures at a beat of 1.53 (γ=1.4) / 3.06 (γ=2.0). Kept as the moiré counter-example. |

## Adding one

Drop the `.glsl` in, keep its header intact, and add a row above. The tools resolve a
bare filename against `../../shaders` then this folder (see `../paths.py`), so no
further wiring is needed; `spirv_cost.py` picks it up automatically.
