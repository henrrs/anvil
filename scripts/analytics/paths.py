"""Private, global Analytics paths, kept outside managed OpenCode config."""

from __future__ import annotations

import os
import stat
from dataclasses import dataclass
from pathlib import Path

from .errors import IntegrityError


@dataclass(frozen=True)
class AnalyticsPaths:
    root: Path
    state: Path
    runtime: Path
    database: Path
    workspace: Path
    datasets: Path
    snapshots: Path
    logs: Path

    @classmethod
    def discover(cls, *, create: bool = False) -> "AnalyticsPaths":
        home = Path(os.environ.get("HOME", str(Path.home()))).expanduser()
        root = Path(os.environ.get("ANVIL_HOME", str(home / ".anvil"))).expanduser()
        return cls.from_root(root, create=create)

    @classmethod
    def from_root(cls, root: Path | str, *, create: bool = False) -> "AnalyticsPaths":
        root = Path(root).expanduser().absolute()
        state = root / "analytics"
        result = cls(
            root=root,
            state=state,
            runtime=state / "runtime.json",
            database=state / "context.db",
            workspace=root / "workspaces" / "analytics",
            datasets=state / "datasets",
            snapshots=state / "snapshots",
            logs=state / "logs",
        )
        result.validate(create=create)
        return result

    def validate(self, *, create: bool = False) -> None:
        """Reject symlinked roots and secure directories owned by this feature."""
        dirs = (self.root, self.state, self.workspace.parent, self.workspace, self.datasets,
                self.snapshots, self.logs)
        for directory in dirs:
            if directory.exists() or directory.is_symlink():
                if directory.is_symlink():
                    raise IntegrityError(f"Analytics path must not be a symlink: {directory}")
                if not directory.is_dir():
                    raise IntegrityError(f"Analytics path is not a directory: {directory}")
            elif create:
                directory.mkdir(parents=True, mode=0o700, exist_ok=True)
            else:
                continue
            if directory.exists():
                self.secure_directory(directory)

        for file_path in (self.runtime, self.database):
            if file_path.is_symlink():
                raise IntegrityError(f"Analytics file must not be a symlink: {file_path}")
            if file_path.exists() and not file_path.is_file():
                raise IntegrityError(f"Analytics path is not a regular file: {file_path}")
            if file_path.exists():
                try:
                    file_path.chmod(0o600)
                except OSError as exc:
                    raise IntegrityError(f"Could not secure Analytics file: {file_path}") from exc
        for suffix in ("-wal", "-shm"):
            sidecar = Path(str(self.database) + suffix)
            if sidecar.is_symlink():
                raise IntegrityError("SQLite sidecar files must not be symlinks")
            if sidecar.exists() and not sidecar.is_file():
                raise IntegrityError("SQLite sidecar paths must be regular files")

    def secure_directory(self, directory: Path) -> None:
        candidate = directory.absolute()
        if candidate.is_symlink() or not candidate.is_dir():
            raise IntegrityError("Analytics directory must be a real directory")
        if candidate == self.root:
            return
        if candidate != self.root:
            try:
                candidate.relative_to(self.root)
            except ValueError as exc:
                # The analytics workspace is a sibling beneath the shared Anvil root.
                if candidate != self.workspace and candidate != self.workspace.parent:
                    raise IntegrityError("Refusing to secure a directory outside the Analytics root") from exc
        try:
            candidate.chmod(0o700)
        except OSError as exc:
            raise IntegrityError("Could not secure Analytics directory") from exc

    def secure_file(self, path: Path) -> None:
        """Apply private mode to a regular file contained in the Analytics root."""
        candidate = path.absolute()
        try:
            candidate.relative_to(self.root)
        except ValueError as exc:
            raise IntegrityError("Refusing to secure a file outside the Analytics root") from exc
        if candidate.is_symlink() or not candidate.is_file():
            raise IntegrityError("Analytics state file must be a regular, non-symlink file")
        try:
            candidate.chmod(stat.S_IRUSR | stat.S_IWUSR)
        except OSError as exc:
            raise IntegrityError("Could not secure Analytics state file") from exc
