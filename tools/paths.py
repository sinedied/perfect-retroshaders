"""Where shaders live, for the tools in this folder.

    ../shaders     the shaders this repo owns
    ./vendor       third-party shaders, kept only as benchmark and comparison
                   references. Not ours, not part of the MIT grant, not edited.

Tools resolve a bare filename against both, so a vendored shader can be dropped
into vendor/ and referenced by name from any tool without further wiring.
"""

import os

TOOLS = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(TOOLS)
SHADERS = os.path.join(REPO, "shaders")
VENDOR = os.path.join(TOOLS, "vendor")


def shader_path(name):
    """Resolve a shader filename against shaders/ then vendor/."""
    for folder in (SHADERS, VENDOR):
        path = os.path.join(folder, name)
        if os.path.isfile(path):
            return path
    raise FileNotFoundError(
        f"{name} is in neither {SHADERS} nor {VENDOR}")


def list_shaders(include_vendor=False):
    """Every .glsl this repo owns, optionally plus the vendored references."""
    names = sorted(f for f in os.listdir(SHADERS) if f.endswith(".glsl"))
    if include_vendor and os.path.isdir(VENDOR):
        names += sorted(f for f in os.listdir(VENDOR) if f.endswith(".glsl"))
    return names
