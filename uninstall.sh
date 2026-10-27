#!/usr/bin/env bash
# Removes OpenMine. Same options as "install.sh --uninstall":
#   ./uninstall.sh            remove the per-user installation (~/.local)
#   ./uninstall.sh --system   remove the system-wide installation (/usr/local)
#   ./uninstall.sh --purge    also delete settings and statistics
exec bash "$(dirname "$0")/install.sh" --uninstall "$@"
