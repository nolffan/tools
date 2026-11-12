# Sourced by the shell scripts here: REPO, the project the tools work for, as
# layout.py's PROJECT (the tools are at <project>/tools or
# <project>/ext/tools, or $TOOLS_PROJECT says), and TOOLS, the tools' own
# directory.
TOOLS="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(dirname "$TOOLS")"
if [ "$(basename "$REPO")" = ext ]; then REPO="$(dirname "$REPO")"; fi
REPO="$(cd "${TOOLS_PROJECT:-$REPO}" && pwd)"
