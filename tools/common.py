#!/usr/bin/env python3
"""Shared plumbing: where shaders are, what is declared about them, and how to
compile and run one.

Everything in tools/ needs some of this, and when two tools answered the same
question differently the result was never an error - it was a number that looked
fine and described the wrong shader. So it is answered once, here.
"""

import hashlib
import os
import re
import tomllib

TOOLS = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(TOOLS)
SHADERS = os.path.join(REPO, "shaders")
VENDOR = os.path.join(TOOLS, "vendor")
ITERATIONS = os.path.join(TOOLS, "iterations")
BASELINE = os.path.join(TOOLS, "baseline.toml")
PREVIEW = os.path.join(TOOLS, "preview")

RELEASED, CURRENT, ARCHIVE, VENDOR_ROLE = "released", "current", "archive", "vendor"


# --------------------------------------------------------------------------
# paths

def shader_path(name):
    """Resolve a bare filename against shaders/, then vendor/, then iterations/.

    A shader can be moved between those three without rewriting any caller.
    """
    for folder in (SHADERS, VENDOR, ITERATIONS):
        path = os.path.join(folder, name)
        if os.path.isfile(path):
            return path
    raise FileNotFoundError(f"{name} is in none of shaders/, vendor/, iterations/")


def files_on_disk():
    names = []
    for folder in (SHADERS, VENDOR, ITERATIONS):
        if os.path.isdir(folder):
            names += sorted(f for f in os.listdir(folder) if f.endswith(".glsl"))
    return names


# --------------------------------------------------------------------------
# baseline.toml

with open(BASELINE, "rb") as _f:
    _DOC = tomllib.load(_f)

SETTINGS = _DOC["settings"]
CASES = [tuple(c) for c in SETTINGS["cases"]]
MOIRE = SETTINGS["moire"]
MIN_PITCH = SETTINGS["min_pitch"]
TOLERANCE = SETTINGS["tolerance"]
SCALER_REFERENCE = SETTINGS["scaler_reference"]
CRAWL = SETTINGS["crawl"]
CRAWL_CASES = [tuple(x) for x in SETTINGS["crawl_cases"]]

SHADERS_DECLARED = {s["name"]: s for s in _DOC["shader"]}
GOLDEN = _DOC.get("golden", {})

DEVICE = SETTINGS["device"]
PIPELINES = _DOC.get("pipeline", [])
PIPELINES_DIR = os.path.join(TOOLS, "device", "pipelines")


def _resolve_releases():
    """Give every release its source's keys, once, before anything reads them.

    A release is byte-identical to the iteration it copies, so every fact about
    how to measure it - sampler, where its pattern sits, which moire exceedances
    were granted - is identical too. Repeating them in the file would be two
    places to forget; not inheriting them at all measured lcd-perfect.glsl at
    5.823 where the file it was copied from measured 0.365.

    Resolved eagerly rather than on first access. Doing it lazily meant the
    answer depended on whether something had happened to call declared() first:
    pattern_freq() reads this dict directly, so the same shader at the same
    scale returned a different band before and after, and only the gate's
    happening to resolve early kept it right.
    """
    for name, entry in list(SHADERS_DECLARED.items()):
        if RELEASED not in entry.get("role", ()):
            continue
        v = version(name)
        src = f"{entry['family']}-v{v}.glsl" if v else None
        if src in SHADERS_DECLARED:
            merged = dict(SHADERS_DECLARED[src])
            merged.update(entry)      # the release's own keys win
            merged["source"] = src
            SHADERS_DECLARED[name] = merged


def declared(name):
    """A shader's entry, releases already carrying their source's keys."""
    if name not in SHADERS_DECLARED:
        raise KeyError(f"{name} is not declared in tools/baseline.toml")
    return SHADERS_DECLARED[name]


def family(name):
    return declared(name)["family"]


def roles(name):
    return set(declared(name)["role"])


def sampler_is_linear(name):
    return SHADERS_DECLARED.get(name, {}).get("sampler") == "linear"


def colour_param(name):
    """The parameter drawing this shader's colour pattern, or None.

    Declared per family in baseline.toml. Returns None when the family has no
    colour pattern, and also when this particular version predates the one it
    declares - the archive reaches back to versions with no such control, and a
    crawl measurement that silently passed an unknown parameter would be
    measuring the shipped default while claiming to measure the maximum.
    """
    p = SETTINGS.get("colour", {}).get(family(name))
    return p if p and p in parameters(name) else None


def by_role(*want):
    want = set(want)
    return [n for n, s in SHADERS_DECLARED.items() if want & set(s["role"])]


def families():
    out = []
    for s in _DOC["shader"]:
        if s["family"] != "vendor" and s["family"] not in out:
            out.append(s["family"])
    return out


def current(fam):
    """The newest iteration of a family: what a default run gates on.

    Never derive this by sorting names: "v8" sorts above "v10", so the newest
    version silently stops being tested the moment a family reaches two digits.
    That happened.
    """
    for name, s in SHADERS_DECLARED.items():
        if s["family"] == fam and CURRENT in s["role"]:
            return name
    return None


def released(fam):
    """The shipped copy of a family, or None if nothing has been released yet.

    Optional by design. `shaders/` holds only what the owner has approved for
    release, so a family being iterated on has nothing there at all.
    """
    for name, s in SHADERS_DECLARED.items():
        if s["family"] == fam and RELEASED in s["role"]:
            return name
    return None


def working_set():
    """What a default run covers: everything a user could actually be running,
    plus the candidate for each family. Falls back to the candidates alone while
    nothing is released."""
    return by_role(RELEASED, CURRENT)


def resolve(args):
    """Turn command-line arguments into shader names.

    Nothing given means the working set. A family name means that family's
    released and current versions. A filename means itself.
    """
    if not args:
        return working_set()
    out = []
    for a in args:
        if a in SHADERS_DECLARED:
            out.append(a)
        elif a in families():
            for n in (released(a), current(a)):
                if n and n not in out:
                    out.append(n)
        elif a + ".glsl" in SHADERS_DECLARED:
            out.append(a + ".glsl")
        else:
            raise SystemExit(f"unknown shader or family: {a}")
    return out


def version(name):
    """The version a shader's own header claims, as a string like "9" or "2a".

    The header is where the version lives, not the filename: a released copy is
    `<family>.glsl` with no suffix, and it still has to say which iteration it
    is. Returns None if the title line does not declare one.
    """
    m = TITLE.match(read(name).split("\n", 1)[0])
    return m.group(2) if m else None


def filename_version(name):
    """The version in a filename, or None for an unsuffixed release copy."""
    m = re.match(r'^(.*?)-v([0-9]+[a-z]?)\.glsl$', name)
    return m.group(2) if m else None


def source_iteration(name):
    """For a release copy, the iteration it must be identical to."""
    return f"{family(name)}-v{version(name)}.glsl"



def moire_allowance(name, case):
    """A recorded exception to the moire limit, if one was granted for this case."""
    for entry in declared(name).get("moire_allow", []):
        if tuple(entry["case"]) == tuple(case):
            return entry["value"]
    return None


def crawl_allowance(name, case):
    """A recorded exception to the crawl limit, if one was granted.

    Same mechanism as moire_allow and used for the same reason: a figure that is
    known, measured, written down and not yet fixed is better recorded than
    either ignored or quietly relabelled as acceptable. An allowance stops the
    number getting WORSE while the fix is worked out.
    """
    for entry in declared(name).get("crawl_allow", []):
        if tuple(entry["case"]) == tuple(case):
            return entry["value"]
    return None


def check_baseline():
    """Every declared shader is on disk, every shader on disk is declared, every
    family has a current version, and any release really is a copy of one.

    The disk-to-baseline direction matters as much as the other one. A new
    version nobody declares would simply not be tested, and dropping out of the
    matrix silently is the failure this whole harness exists to stop.
    """
    errors = []
    for name in SHADERS_DECLARED:
        try:
            shader_path(name)
        except FileNotFoundError:
            errors.append(f"{name}: declared in baseline.toml but not on disk")
    for name in files_on_disk():
        if name not in SHADERS_DECLARED:
            errors.append(f"{name}: on disk but not declared in baseline.toml")
    for fam in families():
        if current(fam) is None:
            errors.append(f"{fam}: no current version declared")

    # A release is a copy of an approved iteration, so the two files must be
    # byte-identical. Which iteration is read off the release's own header,
    # which is the only place its version is written down.
    for name in os.listdir(SHADERS) if os.path.isdir(SHADERS) else []:
        if not name.endswith(".glsl"):
            continue
        if name not in SHADERS_DECLARED:
            continue  # already reported above; family() would raise on it
        if filename_version(name):
            errors.append(f"{name}: a release carries no version in its "
                          f"filename, only in its header")
            continue
        v = version(name)
        if v is None:
            errors.append(f"{name}: header does not say which version it is")
            continue
        src = f"{family(name)}-v{v}.glsl"
        try:
            if read(name) != open(os.path.join(ITERATIONS, src)).read():
                errors.append(f"{name}: not identical to {src}, which its "
                              f"header says it is a copy of")
        except FileNotFoundError:
            errors.append(f"{name}: header claims v{v} but {src} does not exist")
    return errors


# --------------------------------------------------------------------------
# device pipelines
#
# A pipeline is a minarch .cfg, the same file a user installs. Only the keys
# tools/device reads are understood here; anything else in the file is a core
# option and is ignored, exactly as it is on the device.

_CFG_PASS = re.compile(
    r"^minarch_shader([123])(_filter|_srctype|_scaletype|_upscale)?$")


def parse_cfg(path):
    """{"scaling", "scale_filter", "passes": [...], "params": {...}}."""
    passes, params = {}, {}
    scaling, scale_filter = "Aspect", "NEAREST"
    with open(path) as f:
        for raw in f:
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = (p.strip() for p in line.split("=", 1))
            key = key.lstrip("-")  # a locked option, in NextUI's sense
            if key == "minarch_screen_scaling":
                scaling = value
            elif key == "minarch_scale_filter":
                scale_filter = value.upper()
            elif key == "minarch_nrofshaders":
                pass
            elif m := _CFG_PASS.match(key):
                slot = passes.setdefault(int(m.group(1)), {})
                slot[(m.group(2) or "_shader").lstrip("_")] = value
            elif re.fullmatch(r"-?\d+(\.\d+)?", value):
                params[key] = float(value)
    ordered = [passes[i] for i in sorted(passes)]
    return dict(scaling=scaling, scale_filter=scale_filter,
                passes=ordered, params=params)


def pipeline_cfg(entry):
    return os.path.join(PIPELINES_DIR, entry["cfg"])


def check_pipelines():
    """Every declared pipeline resolves, and runs its shaders as declared.

    The sampler check is the one that earns its place. A pipeline naming a
    one-tap shader through NEAREST does not measure that shader, it measures
    nearest-neighbour - the same defect tools/vendor/README.md records costing
    a comparison table its meaning once already.
    """
    errors = []
    for entry in PIPELINES:
        path = pipeline_cfg(entry)
        if not os.path.exists(path):
            errors.append(f"{entry['label']}: {entry['cfg']} does not exist")
            continue
        cfg = parse_cfg(path)
        if not cfg["passes"]:
            errors.append(f"{entry['label']}: names no shader pass")
        for i, p in enumerate(cfg["passes"], 1):
            name = p.get("shader")
            if name is None:
                errors.append(f"{entry['label']} pass {i}: no shader")
                continue
            if name not in SHADERS_DECLARED:
                errors.append(f"{entry['label']} pass {i}: {name} is not "
                              f"declared in baseline.toml")
                continue
            try:
                shader_path(name)
            except FileNotFoundError:
                errors.append(f"{entry['label']} pass {i}: {name} not on disk")
                continue
            want = "LINEAR" if sampler_is_linear(name) else "NEAREST"
            got = p.get("filter", "NEAREST").upper()
            if got != want:
                errors.append(f"{entry['label']} pass {i}: {name} runs "
                              f"{got} but baseline.toml declares {want}")
    labels = [e["label"] for e in PIPELINES]
    for dup in {l for l in labels if labels.count(l) > 1}:
        errors.append(f"{dup}: declared twice")
    return errors


# --------------------------------------------------------------------------
# shader text

VERSION_HEADER = "#version 410 core\n"


def read(name):
    with open(shader_path(name)) as f:
        return f.read()


def essl1_to_410(src, stage):
    """Translate an ESSL-1.00 shader well enough for a 4.1 core context.

    The shaders here carry the COMPAT_* macro block and compile at either
    version, so they come back untouched. Vendored references often do not -
    dmg_dot_matrix.glsl is written straight against ESSL 1.00 - and macOS offers
    no context old enough to take them as they are. Only the keywords that
    changed are rewritten, per stage, and the vendor file is never touched on
    disk. The #ifdef VERTEX / #else pair needs no help: the fragment stage
    leaves VERTEX undefined and falls into the else.
    """
    if "COMPAT_VARYING" in src:
        return src
    out = re.sub(r"\battribute\b", "in", src)
    out = re.sub(r"\bvarying\b", "out" if stage == "vert" else "in", out)
    out = re.sub(r"\btexture2D\b", "texture", out)
    if stage == "frag" and "gl_FragColor" in out:
        # gl_ is a reserved prefix, so this cannot be done with a #define
        out = "out vec4 FragColor;\n" + re.sub(r"\bgl_FragColor\b", "FragColor", out)
    return out


def stage_source(src, stage, version=VERSION_HEADER):
    """A single stage of a shader, preprocessed the way the frontend's loader does."""
    src = essl1_to_410(src, stage) if version == VERSION_HEADER else src
    body = "".join(l + "\n" for l in src.split("\n")
                   if not l.startswith("#pragma parameter"))
    define = ("#define VERTEX\n" if stage == "vert"
              else "#define FRAGMENT\n#define PARAMETER_UNIFORM\n")
    return version + define + body


# "// dmg-perfect v9 - a Game Boy dot matrix over a pixel-perfect scale."
# The version belongs here rather than in the filename, because a released copy
# is <family>.glsl with no suffix and still has to say which iteration it is.
TITLE = re.compile(r'^(?://\s*|\s+)([a-z][a-z-]*?)(?:\s+v([0-9]+[a-z]?))?\s+-\s+(\S.*)$')

PRAGMA = re.compile(
    r'#pragma parameter\s+(\w+)\s+"([^"]*)"\s+'
    r'(-?[\d.]+)\s+(-?[\d.]+)\s+(-?[\d.]+)\s+(-?[\d.]+)')


def parameters(name):
    """Every #pragma parameter a shader declares: name -> (label, default, lo, hi, step)."""
    out = {}
    for line in read(name).split("\n"):
        m = PRAGMA.match(line.strip())
        if m:
            out[m.group(1)] = (m.group(2),) + tuple(float(g) for g in m.groups()[2:])
    return out


def defaults(name, **override):
    """A shader's shipped defaults, read out of its own #pragma lines.

    Always pass these. An unset uniform is 0, PARAMETER_UNIFORM is defined, and
    0 is a legal-looking value, so an empty dict does not fail - it renders a
    different shader. That has caused three separate rounds of wrong numbers,
    including a whole benchmark table.
    """
    p = {k: v[1] for k, v in parameters(name).items()}
    p.update(override)
    return p


# --------------------------------------------------------------------------
# GL

def context():
    import moderngl
    return moderngl.create_standalone_context(require=410)


def program(ctx, name):
    src = read(name)
    return ctx.program(vertex_shader=stage_source(src, "vert"),
                       fragment_shader=stage_source(src, "frag"))


class Programs(dict):
    """Compiled programs, cached. Compiling dominates the runtime otherwise."""

    def __init__(self, ctx):
        super().__init__()
        self.ctx = ctx

    def __missing__(self, name):
        self[name] = program(self.ctx, name)
        return self[name]


def draw(ctx, prog, src_u8, out_w, out_h, params, linear=False):
    """One pass, read back, rows in the source's order."""
    import numpy as np
    import moderngl

    in_h, in_w = src_u8.shape[:2]
    tex = ctx.texture((in_w, in_h), 3, src_u8.tobytes())
    f = moderngl.LINEAR if linear else moderngl.NEAREST
    tex.filter = (f, f)
    tex.repeat_x = tex.repeat_y = False  # CLAMP_TO_EDGE
    tex.use(0)

    for k, v in params.items():
        if k in prog:
            prog[k].value = float(v)
    # a uniform a shader does not use is optimised out of the program, so every
    # one of these has to be guarded rather than just the optional ones
    for k, v in (("Texture", 0),
                 ("OutputSize", (float(out_w), float(out_h))),
                 ("TextureSize", (float(in_w), float(in_h))),
                 ("InputSize", (float(in_w), float(in_h))),
                 ("OrigInputSize", (float(in_w), float(in_h)))):
        if k in prog:
            prog[k].value = v
    if "MVPMatrix" in prog:
        prog["MVPMatrix"].write(np.identity(4, "f4").tobytes())

    # the same quad the frontend's runShaderPass uploads: x,y,z,w, u,v,s,t
    verts = np.array([
        -1.0,  1.0, 0.0, 1.0,  0.0, 1.0, 0.0, 0.0,
        -1.0, -1.0, 0.0, 1.0,  0.0, 0.0, 0.0, 0.0,
         1.0,  1.0, 0.0, 1.0,  1.0, 1.0, 0.0, 0.0,
         1.0, -1.0, 0.0, 1.0,  1.0, 0.0, 0.0, 0.0,
    ], "f4")
    vbo = ctx.buffer(verts.tobytes())
    names = [n for n in ("VertexCoord", "TexCoord") if n in prog]
    vao = ctx.vertex_array(prog, [(vbo, " ".join("4f4" for _ in names), *names)])

    fbo = ctx.framebuffer(color_attachments=[ctx.texture((out_w, out_h), 3)])
    fbo.use()
    ctx.viewport = (0, 0, out_w, out_h)
    fbo.clear(0.0, 0.0, 0.0, 1.0)
    vao.render(moderngl.TRIANGLE_STRIP)

    data = np.frombuffer(fbo.read(components=3), np.uint8).reshape(out_h, out_w, 3)
    for o in (tex, vbo, vao, fbo):
        o.release()
    return data


def render(ctx, progs, name, src_u8, out_w, out_h, params=None, **override):
    """Render a named shader at its shipped defaults, sampled as it declares.

    Taking both the defaults and the sampler from the declaration rather than
    from the caller is the point: a caller that forgets either gets the shader's
    real behaviour instead of whatever zero happens to mean for it.
    """
    p = defaults(name) if params is None else dict(params)
    p.update(override)
    return draw(ctx, progs[name], src_u8, out_w, out_h, p,
                linear=sampler_is_linear(name))


# --------------------------------------------------------------------------
# sources

def flat(w=320, h=240, level=128):
    import numpy as np
    return np.full((h, w, 3), level, np.uint8)


def checkerboard(w=320, h=240):
    """Maximum energy at the source pixel grid - the worst case for moire."""
    import numpy as np
    yy, xx = np.mgrid[0:h, 0:w]
    return (((yy + xx) % 2) * 255).astype(np.uint8)[..., None].repeat(3, axis=2)


def rows(w=320, h=240, on=200):
    import numpy as np
    img = np.zeros((h, w, 3), np.uint8)
    img[::2] = on
    return img


def bars(w=320, h=240):
    """Vertical colour bars: catches a channel swap or a stripe phase error."""
    import numpy as np
    img = np.zeros((h, w, 3), np.uint8)
    palette = [(255, 255, 255), (255, 255, 0), (0, 255, 255), (0, 255, 0),
               (255, 0, 255), (255, 0, 0), (0, 0, 255), (16, 16, 16)]
    for i, c in enumerate(palette):
        img[:, i * w // len(palette):(i + 1) * w // len(palette)] = c
    return img


def border_grid(w=320, h=240, step=20):
    """A grid with a differently coloured edge on each side.

    The only pattern that shows what a geometric change did to the *borders*,
    and the two colours are load-bearing: the retention check counts red- and
    blue-dominant pixels separately, so a single-colour border makes one of the
    two counts zero and the measurement collapses to zero for every shader.
    crt-perfect-v7 shipped having cropped its entire border off-screen while
    every number in the harness read perfect.
    """
    import numpy as np
    img = np.full((h, w, 3), 20, np.uint8)
    img[::step, :] = 255
    img[:, ::step] = 255
    img[0:3, :] = img[-3:, :] = (255, 60, 60)
    img[:, 0:3] = img[:, -3:] = (60, 160, 255)
    return img


def scene(w=320, h=240):
    """A gradient with hard edges: gradients show banding, edges show ringing."""
    import numpy as np
    yy, xx = np.mgrid[0:h, 0:w]
    img = np.zeros((h, w, 3), np.float64)
    img[..., 0] = 255.0 * xx / max(w - 1, 1)
    img[..., 1] = 255.0 * yy / max(h - 1, 1)
    img[..., 2] = 128.0
    block = ((xx // 16) + (yy // 16)) % 2 == 0
    img[block & (xx > w // 2)] = (255, 255, 255)
    img[block & (xx <= w // 2)] = (0, 0, 0)
    return img.astype(np.uint8)


SOURCES = {"flat": flat, "checkerboard": checkerboard, "rows": rows,
           "bars": bars, "border-grid": border_grid, "scene": scene}


# --------------------------------------------------------------------------
# goldens

GOLDEN_MARK = "# --- goldens, generated by tools/test.py --record ---"


def golden_key(case):
    sw, sh, ow, oh = case
    return f"{sw}x{sh}->{ow}x{oh}"


def golden_hash(img):
    return hashlib.sha256(img.tobytes()).hexdigest()[:16]


def write_goldens(table):
    """Rewrite the generated golden block at the end of baseline.toml.

    Everything above the marker is hand-written and is never touched.
    """
    with open(BASELINE) as f:
        text = f.read()
    head = text.split(GOLDEN_MARK)[0].rstrip() + "\n\n"
    body = [GOLDEN_MARK]
    for name in sorted(table):
        body.append(f'\n[golden."{name}"]')
        for key in sorted(table[name]):
            body.append(f'"{key}" = "{table[name][key]}"')
    with open(BASELINE, "w") as f:
        f.write(head + "\n".join(body) + "\n")


# --------------------------------------------------------------------------
# reporting

class Report:
    """Pass/fail accumulation, so every tool prints and exits the same way."""

    def __init__(self, title):
        self.title = title
        self.failures = []
        self.notes = []
        self.checked = 0

    def ok(self, label, detail=""):
        self.checked += 1
        print(f"  \033[32mok\033[0m   {label}" + (f"  {detail}" if detail else ""))

    def fail(self, label, detail=""):
        self.checked += 1
        self.failures.append(f"{label}  {detail}".strip())
        print(f"  \033[31mFAIL\033[0m {label}" + (f"  {detail}" if detail else ""))

    def note(self, text):
        self.notes.append(text)

    def check(self, cond, label, detail=""):
        (self.ok if cond else self.fail)(label, detail)
        return cond

    def done(self):
        print()
        for n in self.notes:
            print(f"  note: {n}")
        if self.failures:
            print(f"\n{self.title}: \033[31m{len(self.failures)} of "
                  f"{self.checked} failed\033[0m")
            return 1
        print(f"{self.title}: \033[32m{self.checked} ok\033[0m")
        return 0


# Fold each release's source keys into it, at import, before any caller can
# observe an unresolved entry. Last in the file because it needs version(),
# which needs TITLE and read().
_resolve_releases()
