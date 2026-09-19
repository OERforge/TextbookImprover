#!/usr/bin/env bash

# Copyright 2026 Robert Szarka
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <https://www.gnu.org/licenses/>.

# The conversion is convert.py now. This wrapper keeps every documented
# command working -- `bash $T/bin/convert.sh --zip` and the rest -- for one
# release, and then goes. Everything the shell script had learned, and
# every comment that recorded it, moved into convert.py with the code.

# If it was started as `sh convert.sh`, WSL runs it under dash, which has
# no BASH_SOURCE -- re-exec under bash so it works either way. Must stay
# POSIX-parseable and above anything bash-specific.
if [ -z "${BASH_VERSION:-}" ]; then
  exec bash "$0" "$@"
fi

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"

if ! command -v python3 >/dev/null 2>&1; then
  echo "python3 not found. It runs the conversion, so it is required:" >&2
  echo "    sudo apt install python3 python3-yaml" >&2
  exit 1
fi

exec python3 "$script_dir/convert.py" "$@"
