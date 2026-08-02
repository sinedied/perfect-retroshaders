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
| `sharp-shimmerless.glsl` | zadpos — public domain | **The one-tap scaler.** Same area average as `pixellate` from a SINGLE tap: it solves for the texcoord whose bilinear fetch already is the weighted sum. 50 ops, 0 SFU, the cheapest thing here — and the construction this repo prototyped and rejected, because it needs `filter_linear0 = true` and leans on the GPU's subtexel precision. `equivalence.py` section 6 measures it. |
| `sharp-shimmerless-grid.glsl` | zadpos — public domain | **Prior art for the core idea.** Treats pixels as ideal rectangles and computes the exact area an input pixel occupies on an output pixel, transcendental-free. `lcd-perfect` uses the separable antiderivative form of the same maths. |
| `dmg_dot_matrix.glsl` | Status_Librarian_313, modified by sinedied | The naive `step()`-on-`mod()` grid with a **post-blend output gamma** — the exact construction AGENTS.md measures at a beat of 1.53 (γ=1.4) / 3.06 (γ=2.0). Kept as the moiré counter-example. |
| `res-independent-scanlines.glsl` | RiskyJumps — public domain | **A scanline pass that costs almost nothing.** One `sin()` on a resolution-independent phase, no prefilter and no mask. Half of the `sharp-shimmerless + scanlines` reference stack `crt-turbo` has to beat. |
| `image-adjustment.glsl` | hunterk — public domain | **The grading pass the reference stacks bolt on.** Brightness, contrast, saturation, gamma and a full colour-temperature model as a separate pass, which is what makes "how much does grading cost on its own" answerable against something real. |

## Adding one

Drop the `.glsl` in, keep its header intact, and add a row above. The tools resolve a
bare filename against `../../shaders` then this folder (see `../paths.py`), so no
further wiring is needed; `spirv_cost.py` picks it up automatically.

Two things a vendored shader does need declaring, because neither can be guessed:

- **Its sampler**, if its `.glslp` asks for `filter_linear0 = true`. Add it to
  `LINEAR_SAMPLED` in `../gl_check.py`. Both `sharp-shimmerless` variants take one tap
  and have the texture unit do the blend, so under NEAREST they are not a slightly
  different shader, they are nearest-neighbour. This is not hypothetical: the
  `sharp-shimmerless-grid` beat figure in the lcd comparison table was **3.14 measured
  through NEAREST and 0.72 through the sampler it ships with**.
- **Its parameters**, only where they should differ from its own `#pragma` defaults.
  Those defaults are read from the file now, so an empty dict means "as shipped". It
  used to mean "every uniform at 0", which is what rendered `pixellate` in the
  `INTERPOLATE_IN_LINEAR_GAMMA = 0` mode it does not ship in — flattering it in every
  preview by removing the one thing wrong with it.
