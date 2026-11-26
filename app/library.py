"""Path-only file library with user-created groups."""

from __future__ import annotations

import os
import threading
import time
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path

from . import storage
from .config import data_dir, quarantine_file

UNSORTED_ID = "unsorted"
UNSORTED_NAME = "Unsorted"
ALLOWED_SUFFIXES = {
    ".pdf",
    ".epub",
    ".pptx",
    ".png",
    ".jpg",
    ".jpeg",
    ".webp",
    ".srt",
    ".vtt",
    ".txt",
    ".md",
}
MAX_NAME = 80


class LibraryError(ValueError):
    pass


def _display_path(raw: str) -> str:
    path = os.path.expanduser(raw.strip().strip('"'))
    if not os.path.isabs(path):
        path = os.path.join(os.getcwd(), path)
    return os.path.normpath(os.path.abspath(path))


def _path_key(path: str) -> str:
    return os.path.normcase(path)


@dataclass
class Group:
    id: str
    name: str
    order: int

    def public(self, builtin: bool = False) -> dict:
        return {"id": self.id, "name": self.name, "builtin": builtin}


@dataclass
class File:
    id: str
    path: str
    name: str
    group_id: str
    added_at: float
    last_opened: float = 0.0

    def public(self) -> dict:
        path = Path(self.path)
        return {
            "id": self.id,
            "name": self.name,
            "path": self.path,
            "groupId": self.group_id,
            "exists": path.is_file(),
            "addedAt": self.added_at,
            "lastOpened": self.last_opened,
        }


class Library:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path or (data_dir() / "library.json")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._groups: list[Group] = []
        self._files: list[File] = []
        self._load()

    # -- persistence -----------------------------------------------------

    def _load(self) -> None:
        payload, source = storage.read_json(self.path)
        if source == "unreadable":
            quarantine_file(self.path)
            return
        if source == "backup" and isinstance(payload, dict):
            storage.heal(self.path, payload)
        # A file that is valid JSON but not our shape used to crash the whole
        # app at startup (AttributeError on a list); treat it as empty instead.
        if not isinstance(payload, dict):
            return
        raw = payload
        groups = raw.get("groups")
        files = raw.get("files")
        for entry in groups if isinstance(groups, list) else []:
            try:
                if not isinstance(entry, dict):
                    continue
                group = Group(
                    id=str(entry["id"]),
                    name=str(entry["name"]),
                    order=int(entry.get("order", 0)),
                )
            except (KeyError, TypeError, ValueError):
                continue
            if group.id and group.id != UNSORTED_ID:
                self._groups.append(group)
        for entry in files if isinstance(files, list) else []:
            try:
                if not isinstance(entry, dict):
                    continue
                group_id = str(entry.get("groupId", UNSORTED_ID))
                if group_id != UNSORTED_ID and not any(
                    group.id == group_id for group in self._groups
                ):
                    group_id = UNSORTED_ID
                file = File(
                    id=str(entry["id"]),
                    path=str(entry["path"]),
                    name=str(entry.get("name") or Path(entry["path"]).name),
                    group_id=group_id,
                    added_at=float(entry.get("addedAt", 0)),
                    last_opened=float(entry.get("lastOpened", 0)),
                )
            except (KeyError, TypeError, ValueError):
                continue
            if file.id and file.path:
                self._files.append(file)

    def _save(self) -> None:
        payload = {
            "groups": [asdict(group) for group in self._groups],
            "files": [
                {
                    "id": file.id,
                    "path": file.path,
                    "name": file.name,
                    "groupId": file.group_id,
                    "addedAt": file.added_at,
                    "lastOpened": file.last_opened,
                }
                for file in self._files
            ],
        }
        with self._lock:
            storage.write_json(self.path, payload)

    # -- groups ----------------------------------------------------------

    def groups(self) -> list[Group]:
        ordered = sorted(self._groups, key=lambda group: (group.order, group.name.casefold()))
        ordered.append(Group(UNSORTED_ID, UNSORTED_NAME, 10_000))
        return ordered

    def _group_exists(self, group_id: str) -> bool:
        return group_id == UNSORTED_ID or any(
            group.id == group_id for group in self._groups
        )

    def create_group(self, name: str) -> Group:
        name = name.strip()[:MAX_NAME]
        if not name:
            raise LibraryError("Group name can't be empty.")
        if name.casefold() == UNSORTED_NAME.casefold():
            raise LibraryError("'Unsorted' is reserved for ungrouped files.")
        if any(group.name.casefold() == name.casefold() for group in self._groups):
            raise LibraryError("A group with that name already exists.")
        order = max((group.order for group in self._groups), default=0) + 1
        group = Group(id=uuid.uuid4().hex, name=name, order=order)
        with self._lock:
            self._groups.append(group)
            self._save()
        return group

    def rename_group(self, group_id: str, name: str) -> Group:
        name = name.strip()[:MAX_NAME]
        if not name:
            raise LibraryError("Group name can't be empty.")
        if name.casefold() == UNSORTED_NAME.casefold():
            raise LibraryError("'Unsorted' is reserved for ungrouped files.")
        with self._lock:
            group = next((item for item in self._groups if item.id == group_id), None)
            if group is None:
                raise LibraryError("Group not found.")
            if any(
                item.id != group_id and item.name.casefold() == name.casefold()
                for item in self._groups
            ):
                raise LibraryError("A group with that name already exists.")
            group.name = name
            self._save()
        return group

    def delete_group(self, group_id: str) -> None:
        if group_id == UNSORTED_ID:
            raise LibraryError("The Unsorted group can't be deleted.")
        with self._lock:
            group = next((item for item in self._groups if item.id == group_id), None)
            if group is None:
                raise LibraryError("Group not found.")
            self._groups = [item for item in self._groups if item.id != group_id]
            for file in self._files:
                if file.group_id == group_id:
                    file.group_id = UNSORTED_ID
            self._save()

    # -- files -----------------------------------------------------------

    def get_file(self, file_id: str) -> File:
        with self._lock:
            file = next((item for item in self._files if item.id == file_id), None)
        if file is None:
            raise LibraryError("File not found in the library.")
        return file

    def add_file(self, raw_path: str, group_id: str = UNSORTED_ID) -> tuple[File, bool]:
        path = _display_path(raw_path)
        suffix = Path(path).suffix.lower()
        if suffix not in ALLOWED_SUFFIXES:
            raise LibraryError(
                "Only PDF, EPUB, PowerPoint, image, SRT, VTT and TXT files can be added."
            )
        if not Path(path).is_file():
            raise LibraryError(f"File not found: {path}")
        group_id = group_id if self._group_exists(group_id) else UNSORTED_ID
        key = _path_key(path)
        with self._lock:
            existing = next(
                (item for item in self._files if _path_key(item.path) == key), None
            )
            if existing is not None:
                if group_id != existing.group_id:
                    existing.group_id = group_id
                    self._save()
                return existing, False
            file = File(
                id=uuid.uuid4().hex,
                path=path,
                name=Path(path).name,
                group_id=group_id,
                added_at=time.time(),
            )
            self._files.append(file)
            self._save()
        return file, True

    def import_paths(
        self, paths: list[str], group_id: str = UNSORTED_ID
    ) -> tuple[list[File], list[str]]:
        added: list[File] = []
        errors: list[str] = []
        for raw in paths:
            try:
                file, was_added = self.add_file(raw, group_id)
                if was_added:
                    added.append(file)
            except LibraryError as exc:
                errors.append(str(exc))
        return added, errors

    def move_file(self, file_id: str, group_id: str) -> File:
        if not self._group_exists(group_id):
            raise LibraryError("Group not found.")
        with self._lock:
            file = next((item for item in self._files if item.id == file_id), None)
            if file is None:
                raise LibraryError("File not found in the library.")
            file.group_id = group_id
            self._save()
        return file

    def remove_file(self, file_id: str) -> None:
        with self._lock:
            before = len(self._files)
            self._files = [item for item in self._files if item.id != file_id]
            if len(self._files) == before:
                raise LibraryError("File not found in the library.")
            self._save()

    def touch(self, file_id: str) -> None:
        with self._lock:
            file = next((item for item in self._files if item.id == file_id), None)
            if file is not None:
                file.last_opened = time.time()
                self._save()

    # -- read models -----------------------------------------------------

    def snapshot(self) -> dict:
        with self._lock:
            files = sorted(self._files, key=lambda file: file.name.casefold())
            groups = self.groups()
        opened = max(self._files, key=lambda file: file.last_opened, default=None)
        return {
            "groups": [
                group.public(builtin=group.id == UNSORTED_ID) for group in groups
            ],
            "files": [file.public() for file in files],
            "lastOpenedFileId": opened.id if opened and opened.last_opened else None,
        }
