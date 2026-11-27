"""스타터 빌드 라이브러리(JSON) 관리."""
from __future__ import annotations

import json
import os
import re
import shutil
from dataclasses import dataclass, field
from pathlib import Path

from . import datafiles, pob

BUNDLED_LIBRARY = datafiles.DATA_DIR / "starters.json"
KINDS = {
    "starter": "리그 스타터",
    "character": "내 캐릭터",
    "seed": "시드/엔드게임",
    "poe2": "PoE2 스타터",
    "custom": "직접 추가",
}


class LibraryError(RuntimeError):
    pass


def default_library_path() -> Path:
    base = os.environ.get("POE_CHECKER_HOME")
    if base:
        return Path(base) / "library.json"
    if os.name == "nt":
        root = Path(os.environ.get("APPDATA", Path.home()))
        return root / "PoE-Patch-Starter-Checker" / "library.json"
    return Path.home() / ".poe-patch-starter-checker" / "library.json"


@dataclass
class BuildEntry:
    id: str
    name: str
    kind: str = "starter"
    game: str = datafiles.GAME_POE1
    origin: str = ""
    source: str = ""
    note: str = ""
    code_file: str = ""
    code: str = ""

    @property
    def kind_label(self) -> str:
        return KINDS.get(self.kind, self.kind)

    @property
    def game_label(self) -> str:
        return datafiles.GAME_LABELS.get(datafiles.normalize_game(self.game), self.game)

    def payload(self) -> str:
        """PoB 코드 또는 XML 문자열."""
        if self.code:
            return self.code
        if self.code_file:
            path = datafiles.DATA_DIR / self.code_file
            if path.exists():
                return path.read_text(encoding="utf-8", errors="replace")
            raise LibraryError(f"빌드 파일이 없습니다: {self.code_file}")
        raise LibraryError(f"'{self.name}' 에 PoB 코드가 없습니다.")

    def to_dict(self) -> dict:
        out = {
            "id": self.id,
            "name": self.name,
            "kind": self.kind,
            "game": datafiles.normalize_game(self.game),
            "origin": self.origin,
            "source": self.source,
            "note": self.note,
        }
        if self.code_file:
            out["code_file"] = self.code_file
        if self.code:
            out["code"] = self.code
        return out

    @classmethod
    def from_dict(cls, data: dict) -> "BuildEntry":
        kind = data.get("kind", "starter")
        game = data.get("game") or ("poe2" if kind == "poe2" else "poe1")
        return cls(
            id=data["id"],
            name=data.get("name", data["id"]),
            kind=kind,
            game=datafiles.normalize_game(game),
            origin=data.get("origin", ""),
            source=data.get("source", ""),
            note=data.get("note", ""),
            code_file=data.get("code_file", ""),
            code=data.get("code", ""),
        )


@dataclass
class BuildLibrary:
    path: Path
    builds: list[BuildEntry] = field(default_factory=list)
    _profiles: dict[str, pob.BuildProfile] = field(default_factory=dict, repr=False)
    _errors: dict[str, str] = field(default_factory=dict, repr=False)

    # -- load / save ------------------------------------------------------
    @classmethod
    def load(cls, path: str | os.PathLike | None = None, *, seed: bool = True,
             sync: bool | None = None) -> "BuildLibrary":
        """라이브러리를 읽는다. 기본 경로일 때는 앱에 동봉된 스타터 갱신분을 자동 반영한다."""
        target = Path(path) if path else default_library_path()
        if sync is None:
            sync = path is None
        bundled = cls._read_bundled() if seed else None
        if not target.exists():
            if bundled:
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(json.dumps(bundled, ensure_ascii=False, indent=2), encoding="utf-8")
            else:
                return cls(path=target, builds=[])
        try:
            data = json.loads(target.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise LibraryError(f"라이브러리 JSON 을 읽지 못했습니다: {exc}") from exc
        builds = [BuildEntry.from_dict(row) for row in data.get("builds", [])]
        library = cls(path=target, builds=builds)
        library._sync_meta = bundled
        if bundled and sync and cls._needs_sync(data, bundled):
            library.builds = cls._merge_bundled(builds, bundled)
            data = {"schema": bundled.get("schema", 1), "builds": [b.to_dict() for b in library.builds]}
            library._sync_meta = bundled
            library.save(bundled_meta=bundled)
        return library

    # -- 동봉 스타터 동기화 ------------------------------------------------
    @staticmethod
    def _read_bundled() -> dict | None:
        if not BUNDLED_LIBRARY.exists():
            return None
        try:
            return json.loads(BUNDLED_LIBRARY.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return None

    @staticmethod
    def _needs_sync(data: dict, bundled: dict) -> bool:
        """앱에 동봉된 스타터 목록이 갱신됐으면 사용자 라이브러리에 반영한다."""
        if data.get("bundled_updated") != bundled.get("updated"):
            return True
        if int(data.get("schema", 1)) < int(bundled.get("schema", 1)):
            return True
        return False

    @staticmethod
    def _merge_bundled(current: list[BuildEntry], bundled: dict) -> list[BuildEntry]:
        """동봉 빌드는 새 버전으로 갱신하고, 사용자가 직접 추가한 빌드는 그대로 둔다."""
        bundled_entries = [BuildEntry.from_dict(row) for row in bundled.get("builds", [])]
        bundled_ids = {entry.id for entry in bundled_entries}
        custom = [b for b in current if b.id not in bundled_ids and b.kind == "custom"]
        other = [b for b in current if b.id not in bundled_ids and b.kind != "custom"]
        return bundled_entries + other + custom

    def save(self, bundled_meta: dict | None = None) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        meta = bundled_meta if bundled_meta is not None else getattr(self, "_sync_meta", None)
        payload = {
            "schema": (meta or {}).get("schema", 2),
            "builds": [build.to_dict() for build in self.builds],
        }
        if meta:
            payload["bundled_updated"] = meta.get("updated", "")
        tmp = self.path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(self.path)

    # -- queries ----------------------------------------------------------
    def get(self, build_id: str) -> BuildEntry | None:
        for build in self.builds:
            if build.id == build_id:
                return build
        return None

    def profile(self, build: BuildEntry) -> pob.BuildProfile:
        if build.id in self._profiles:
            return self._profiles[build.id]
        profile = pob.load_build(build.payload(), name=build.name, notes=build.note,
                                 game=build.game)
        profile.source = build.source or profile.source
        self._profiles[build.id] = profile
        return profile

    def builds_for(self, game: str | None = None) -> list[BuildEntry]:
        if not game:
            return list(self.builds)
        target = datafiles.normalize_game(game)
        return [b for b in self.builds if datafiles.normalize_game(b.game) == target]

    def profiles(self, game: str | None = None) -> list[tuple[BuildEntry, pob.BuildProfile]]:
        out = []
        self._errors.clear()
        for build in self.builds_for(game):
            try:
                out.append((build, self.profile(build)))
            except (pob.PobError, LibraryError) as exc:
                self._errors[build.id] = str(exc)
        return out

    @property
    def errors(self) -> dict[str, str]:
        return dict(self._errors)

    # -- mutations --------------------------------------------------------
    def _new_id(self, name: str) -> str:
        base = re.sub(r"[^0-9a-z가-힣]+", "-", name.lower()).strip("-") or "build"
        existing = {b.id for b in self.builds}
        if base not in existing:
            return base
        index = 2
        while f"{base}-{index}" in existing:
            index += 1
        return f"{base}-{index}"

    def add(self, source: str, *, name: str = "", kind: str = "custom", note: str = "",
            game: str | None = None) -> BuildEntry:
        """pobb.in URL·PoB 코드·XML 파일을 검사한 뒤 라이브러리에 추가한다."""
        source = (source or "").strip()
        if not source:
            raise LibraryError("PoB 코드나 pobb.in 주소를 입력해 주세요.")
        xml = pob.resolve_source(source)  # 한 번만 내려받고/풀어서 검사한다
        profile = pob.parse_pob_xml(xml, source=source if "\n" not in source else "붙여넣은 코드")
        if name.strip():
            label = name.strip()
        else:
            main = profile.main_skill_names[0] if profile.main_skill_names else "빌드"
            label = f"{main} {profile.ascendancy or profile.class_name}".strip()
        # 항상 코드 형태로 정규화해 저장한다(파일 의존 없이 이동 가능).
        stored = pob.encode_pob_code(xml)
        resolved_game = datafiles.normalize_game(game) if game else profile.game
        entry = BuildEntry(
            id=self._new_id(label),
            name=label,
            kind=kind if kind in KINDS else "custom",
            game=resolved_game,
            source=source if source.startswith("http") else "직접 입력",
            note=note,
            code=stored,
        )
        self.builds.append(entry)
        self._profiles[entry.id] = profile
        self.save()
        return entry

    def remove(self, build_id: str) -> bool:
        for index, build in enumerate(self.builds):
            if build.id == build_id:
                del self.builds[index]
                self._profiles.pop(build_id, None)
                self.save()
                return True
        return False

    def rename(self, build_id: str, name: str) -> bool:
        build = self.get(build_id)
        if not build:
            return False
        build.name = name
        self.save()
        return True

    # -- helpers ----------------------------------------------------------
    def rows(self, game: str | None = None) -> list[dict]:
        rows = []
        for build in self.builds_for(game):
            try:
                profile = self.profile(build)
                rows.append(
                    {
                        "id": build.id,
                        "name": build.name,
                        "kind": build.kind_label,
                        "game": build.game_label,
                        "game_key": build.game,
                        "class": profile.ascendancy or profile.class_name,
                        "level": profile.level or "",
                        "main": ", ".join(profile.main_skill_names[:2]),
                        "tree": profile.tree_version,
                        "error": "",
                    }
                )
            except (pob.PobError, LibraryError) as exc:
                rows.append(
                    {
                        "id": build.id,
                        "name": build.name,
                        "kind": build.kind_label,
                        "game": build.game_label,
                        "game_key": build.game,
                        "class": "",
                        "level": "",
                        "main": "",
                        "tree": "",
                        "error": str(exc),
                    }
                )
        return rows
