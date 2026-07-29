"""Where shaders live, for the tools in this folder.

    ../shaders     the shaders this repo owns and ships
    ./vendor       third-party shaders, kept only as benchmark and comparison
                   references. Not ours, not part of the MIT grant, not edited.
    ./iterations   superseded versions of our own shaders, kept for the record.
                   Still registered in shaders.py, so they keep being verified
                   rather than rotting.

Tools resolve a bare filename against all three, so a shader can be dropped into
vendor/ or iterations/ and referenced by name from any tool without further
wiring. Only shaders/ is listed by default: the archive should not turn up in a
cost table or a compile report unless it was asked for.
"""

import os

TOOLS = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(TOOLS)
SHADERS = os.path.join(REPO, "shaders")
VENDOR = os.path.join(TOOLS, "vendor")
ITERATIONS = os.path.join(TOOLS, "iterations")


def shader_path(name):
    """Resolve a shader filename against shaders/, then vendor/, then iterations/."""
    for folder in (SHADERS, VENDOR, ITERATIONS):
        path = os.path.join(folder, name)
        if os.path.isfile(path):
            return path
    raise FileNotFoundError(
        f"{name} is in none of {SHADERS}, {VENDOR}, {ITERATIONS}")


def _glsl_in(folder):
    if not os.path.isdir(folder):
        return []
    return sorted(f for f in os.listdir(folder) if f.endswith(".glsl"))


def list_shaders(include_vendor=False, include_iterations=False):
    """The shaders this repo ships, optionally plus the references and the archive."""
    names = _glsl_in(SHADERS)
    if include_vendor:
        names += _glsl_in(VENDOR)
    if include_iterations:
        names += _glsl_in(ITERATIONS)
    return names
