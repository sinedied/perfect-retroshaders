# vendor

Third-party shaders, kept **only** as benchmark and comparison references.

- Not covered by this repository's MIT licence. Each file is governed by its own
  licence, reproduced in its header.
- Not edited. Keep them byte-identical to upstream so measurements stay honest and
  comparable.
- Not shipped as part of this project's shader set.

| File | Author | Why it's here |
|---|---|---|
| `pixellate.glsl` | Fes, 2011–2012 | **The performance baseline.** 30 SFU slots, and it ships on the target handheld while holding 60fps — so it defines the budget every shader here is measured against. |

## Adding one

Drop the `.glsl` in, keep its header intact, and add a row above. The tools resolve a
bare filename against `../../shaders` then this folder (see `../paths.py`), so no
further wiring is needed; `spirv_cost.py` picks it up automatically.
