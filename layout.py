"""Where things are, for the scripts here.

The tools are a submodule of the project they work for, at either of:

  <project>/tools/        (with toolchains/ beside it), or
  <project>/ext/tools/    (with ext/toolchains/: the layout the projects use)

PROJECT is the project's root (progress/, out/, src/, build/), unless
$TOOLS_PROJECT says otherwise (lithtools keeps its submodules in ext/ at the
top of the repository and its project in legacy/talon/). sibling(name) is
one of the other submodules, which sit beside the tools in either layout.
There is no rez/ submodule: a project installs the retail game from your
own disc images (isos/) into out/retail/, and gives its path to the tools
that read it.
"""

import os

TOOLS = os.path.dirname(os.path.abspath(__file__))
_PARENT = os.path.dirname(TOOLS)
PROJECT = os.path.abspath(os.environ.get("TOOLS_PROJECT") or (
    os.path.dirname(_PARENT) if os.path.basename(_PARENT) == "ext" else _PARENT))


def sibling(name):
    """The submodule `name` (for example toolchains) beside the tools."""
    return os.path.join(_PARENT, name)
