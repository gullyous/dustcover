# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 gullyous

"""
make_release_body.py <tag>
--------------------------
Composes the GitHub release body for a version tag (e.g. v1.4.2) from that
version's CHANGELOG.md section, so release pages and the in-app update dialog
show what actually changed instead of a generic app description. Used by the
release workflow (.github/workflows/build.yml); writes dist/release_body.md.
"""

import os
import re
import sys


def changelog_section(md, version):
    """The body of CHANGELOG.md's `## [version]` section (without the header)."""
    out, capturing = [], False
    for line in md.splitlines():
        m = re.match(r"^##\s*\[([^\]]+)\]", line)
        if m:
            if capturing:
                break
            capturing = m.group(1).strip() == version
            continue
        if capturing:
            out.append(line.rstrip())
    return "\n".join(out).strip()


def compose(md, tag):
    version = tag.lstrip("vV").strip()
    section = changelog_section(md, version)
    if not section:
        section = "See CHANGELOG.md in the repository for details."
    return (
        f"What's new in v{version}\n\n"
        f"{section}\n\n"
        "---\n"
        "Existing installs: update from Settings > Updates (or the tray's "
        "\"Check for updates...\"). New here? Grab `Dustcover.exe` below; "
        "no install needed. The build is unsigned, so SmartScreen may warn the "
        "first time (More info -> Run anyway).\n"
    )


def main():
    # The CI runner pipes stdout through cp1252; a non-ASCII changelog line
    # would crash the print below and block the whole release. Force UTF-8.
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    if len(sys.argv) < 2:
        print("usage: make_release_body.py <tag>", file=sys.stderr)
        return 1
    with open("CHANGELOG.md", encoding="utf-8") as f:
        md = f.read()
    body = compose(md, sys.argv[1])
    os.makedirs("dist", exist_ok=True)
    with open(os.path.join("dist", "release_body.md"), "w", encoding="utf-8") as f:
        f.write(body)
    print(body)
    return 0


if __name__ == "__main__":
    sys.exit(main())
