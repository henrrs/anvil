#!/usr/bin/env python3
"""Plan, apply, and reverse the PATH entry used by OpenCode's official installer."""

from __future__ import annotations

import argparse
import json
import os
import shlex
import sys
import tempfile
from pathlib import Path


def choose_file(home: Path, xdg: Path, shell: str) -> Path:
    name = Path(shell).name
    if name == "zsh":
        choices = [home / ".zshrc", home / ".zshenv", xdg / "zsh/.zshrc", xdg / "zsh/.zshenv"]
        fallback = home / ".zshrc"
    elif name == "fish":
        choices = [xdg / "fish/config.fish"]
        fallback = xdg / "fish/config.fish"
    else:
        choices = [home / ".bashrc", home / ".bash_profile", home / ".profile", xdg / "bash/.bashrc"]
        fallback = home / ".bashrc"
    return next((path for path in choices if path.is_file()), fallback)


def path_line(path: Path, shell: str) -> str:
    if Path(shell).name == "fish":
        quoted = "'" + str(path).replace("\\", "\\\\").replace("'", "\\'") + "'"
        return f"fish_add_path {quoted}"
    return f"export PATH={shlex.quote(str(path))}:\"$PATH\""


def atomic_write(path: Path, content: str, mode: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        os.fchmod(fd, mode)
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    except BaseException:
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise


def command_resolves_to(install_dir: Path, path_value: str) -> bool:
    expected = os.path.realpath(install_dir / "opencode")
    for item in path_value.split(os.pathsep):
        candidate = Path(item or ".") / "opencode"
        if candidate.is_file() and os.access(candidate, os.X_OK):
            return os.path.realpath(candidate) == expected
    return False


def main() -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="action", required=True)
    for action in ("plan", "apply"):
        p = sub.add_parser(action)
        p.add_argument("--home", type=Path, required=True)
        p.add_argument("--xdg-config-home", type=Path, required=True)
        p.add_argument("--install-dir", type=Path, required=True)
        p.add_argument("--shell", default="bash")
        p.add_argument("--path", default="")
    p_remove = sub.add_parser("remove")
    p_remove.add_argument("--file", type=Path, required=True)
    p_remove.add_argument("--line", required=True)
    p_remove.add_argument("--file-preexisted", choices=("yes", "no"), required=True)
    args = parser.parse_args()
    if args.action in ("plan", "apply"):
        file = choose_file(args.home, args.xdg_config_home, args.shell)
        line = path_line(args.install_dir, args.shell)
        effective = command_resolves_to(args.install_dir, args.path)
        current = file.read_text(encoding="utf-8") if file.is_file() else ""
        already = line in current.splitlines()
        needs_add = not effective and not already
        unwritable = file.is_symlink() or (file.exists() and not os.access(file, os.W_OK)) or (not file.exists() and not os.access(file.parent, os.W_OK))
        manual_required = needs_add and unwritable
        added = needs_add and not manual_required
        result = {"file": str(file), "line": line, "added": added, "file_preexisted": file.is_file(), "manual_required": manual_required}
        if args.action == "apply" and added:
            marker = "# Anvil: OpenCode install directory"
            separator = "" if not current or current.endswith("\n") else "\n"
            content = current + separator + f"\n{marker}\n{line}\n"
            mode = file.stat().st_mode & 0o777 if file.exists() else 0o600
            atomic_write(file, content, mode)
        print(json.dumps(result))
        return 0
    if not args.file.exists():
        return 0
    if args.file.is_symlink():
        print(f"WARN  Skipping PATH cleanup for symlinked startup file: {args.file}", file=sys.stderr)
        return 0
    content = args.file.read_text(encoding="utf-8")
    lines = content.splitlines(keepends=True)
    marker = "# Anvil: OpenCode install directory"
    retained = [item for item in lines if item.rstrip("\r\n") not in (args.line, marker)]
    new_content = "".join(retained)
    if args.file_preexisted == "no" and not new_content.strip():
        args.file.unlink()
    elif new_content != content:
        atomic_write(args.file, new_content, args.file.stat().st_mode & 0o777)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
