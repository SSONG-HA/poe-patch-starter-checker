"""「스타터 최신화」 — 원격 카탈로그 동기화.

프로그램을 다시 설치하지 않아도 새 시즌 스타터 목록·PoB 코드를 받아 라이브러리에
안전하게 병합한다.

- 원격: `data/starter_catalog.json` (기본값은 이 저장소 main 브랜치의 raw URL)
- 병합 규칙: 카탈로그에 있는 빌드는 이름·종류·설명·PoB 코드를 갱신하고, 없던 빌드는
  추가한다. **사용자가 직접 추가한 빌드(kind=custom)는 절대 건드리지 않는다.**
  카탈로그에서 빠진 로컬 빌드도 지우지 않고 보존한다.
- 빌드 본문은 `pob_code`(Base64) / `pob_xml` / `pob_code_url`(상대·절대 경로 또는 URL)
  / `pobb_in`(pobb.in 주소) 중 하나로 받는다. 받은 본문은 파싱에 성공해야만 반영한다.
"""
from __future__ import annotations

import hashlib
import json
import os
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

from . import datafiles, library as library_mod, pob
from .patchnotes import USER_AGENT

CATALOG_URL = (
    "https://raw.githubusercontent.com/SSONG-HA/poe-patch-starter-checker/"
    "main/poe_checker/data/starter_catalog.json"
)
CATALOG_ENV = "POE_CHECKER_CATALOG_URL"
MAX_BYTES = 16 * 1024 * 1024


class CatalogError(RuntimeError):
    """카탈로그를 읽거나 빌드 본문을 받지 못했을 때."""


def digest(text: str) -> str:
    return hashlib.sha256((text or "").strip().encode("utf-8")).hexdigest()


def _is_url(location: str) -> bool:
    return location.startswith("http://") or location.startswith("https://")


def _read_local(location: str) -> str | None:
    if location.startswith("file://"):
        path = Path(urllib.parse.urlparse(location).path)
    else:
        path = Path(location)
    if path.exists() and path.is_file():
        return path.read_text(encoding="utf-8", errors="replace")
    return None


def _http_get(location: str, *, timeout: float = 25.0) -> str:
    request = urllib.request.Request(location, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read(MAX_BYTES + 1)
    except urllib.error.HTTPError as exc:
        raise CatalogError(f"카탈로그 응답 {exc.code} — 주소를 확인해 주세요: {location}") from exc
    except urllib.error.URLError as exc:
        raise CatalogError(f"카탈로그에 연결하지 못했습니다: {exc.reason}") from exc
    except OSError as exc:  # pragma: no cover - 환경별 소켓 오류
        raise CatalogError(f"카탈로그를 읽지 못했습니다: {exc}") from exc
    if len(raw) > MAX_BYTES:
        raise CatalogError("카탈로그가 너무 큽니다(16MB 초과).")
    return raw.decode("utf-8", errors="replace")


def read_source(location: str, *, fetcher=None, timeout: float = 25.0) -> str:
    """URL·파일 경로 어느 쪽이든 텍스트를 읽는다(오프라인 테스트는 fetcher 주입)."""
    if fetcher is not None:
        return fetcher(location)
    text = _read_local(location)
    if text is not None:
        return text
    if _is_url(location):
        return _http_get(location, timeout=timeout)
    raise CatalogError(f"카탈로그 파일을 찾지 못했습니다: {location}")


def _base_of(location: str) -> str:
    if _is_url(location):
        return location.rsplit("/", 1)[0] + "/"
    path = Path(location)
    return str(path.parent)


def resolve_location(location: str, *, base: str = "") -> str:
    """카탈로그 안의 상대 경로를 카탈로그 위치 기준으로 풀어낸다."""
    if not location:
        return ""
    if _is_url(location) or location.startswith("file://"):
        return location
    path = Path(location)
    if path.is_absolute():
        return location
    if base and _is_url(base):
        return urllib.parse.urljoin(base, location)
    if base:
        joined = Path(base) / location
        if joined.exists() or not path.exists():
            return str(joined)
    return location


@dataclass
class CatalogBuild:
    id: str
    name: str = ""
    kind: str = "starter"
    game: str = datafiles.GAME_POE1
    origin: str = ""
    note: str = ""
    source: str = ""
    pob_code: str = ""
    pob_xml: str = ""
    pob_code_url: str = ""
    pobb_in: str = ""
    sha256: str = ""

    @classmethod
    def from_dict(cls, data: dict) -> "CatalogBuild":
        build_id = str(data.get("id") or "").strip()
        if not build_id:
            raise CatalogError("카탈로그 빌드에 id 가 없습니다.")
        kind = data.get("kind") or "starter"
        game = data.get("game") or ("poe2" if kind == "poe2" else datafiles.GAME_POE1)
        return cls(
            id=build_id,
            name=data.get("name") or build_id,
            kind=kind,
            game=datafiles.normalize_game(game),
            origin=data.get("origin", ""),
            note=data.get("note", ""),
            source=data.get("source", ""),
            pob_code=(data.get("pob_code") or "").strip(),
            pob_xml=data.get("pob_xml") or "",
            pob_code_url=data.get("pob_code_url") or data.get("code_url") or "",
            pobb_in=data.get("pobb_in") or data.get("pobb_in_url") or "",
            sha256=(data.get("sha256") or "").strip(),
        )

    def inline_payload(self) -> str:
        return self.pob_code or self.pob_xml


@dataclass
class Catalog:
    location: str
    updated: str = ""
    base_url: str = ""
    builds: list[CatalogBuild] = field(default_factory=list)

    def get(self, build_id: str) -> CatalogBuild | None:
        for build in self.builds:
            if build.id == build_id:
                return build
        return None


def parse_catalog(text: str, *, location: str = "") -> Catalog:
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise CatalogError(f"카탈로그 JSON 을 읽지 못했습니다: {exc}") from exc
    if not isinstance(data, dict):
        raise CatalogError("카탈로그 형식이 올바르지 않습니다(객체가 아님).")
    rows = data.get("builds")
    if isinstance(rows, dict):
        rows = [{"id": key, **(value if isinstance(value, dict) else {})} for key, value in rows.items()]
    if not isinstance(rows, list):
        raise CatalogError("카탈로그에 builds 목록이 없습니다.")
    builds = [CatalogBuild.from_dict(row) for row in rows if isinstance(row, dict)]
    base = data.get("base_url") or (_base_of(location) if location else "")
    return Catalog(
        location=location,
        updated=str(data.get("updated") or ""),
        base_url=base.rstrip("/") + "/" if base and not base.endswith("/") else base,
        builds=builds,
    )


def load_catalog(url: str | None = None, *, fetcher=None) -> Catalog:
    location = url or os.environ.get(CATALOG_ENV) or CATALOG_URL
    text = read_source(location, fetcher=fetcher)
    return parse_catalog(text, location=location)


def normalize_payload(text: str) -> str:
    """카탈로그 빌드 본문(코드/XML)을 검증하고 PoB 코드로 정규화한다."""
    body = (text or "").strip()
    if not body:
        raise CatalogError("빌드 본문이 비어 있습니다.")
    if pob.looks_like_xml(body):
        xml = body
        code = pob.encode_pob_code(xml)
    else:
        code = "".join(body.split())
        xml = pob.decode_pob_code(code)
    pob.parse_pob_xml(xml)  # 파싱 실패 시 PobError
    return code


def payload_for(build: CatalogBuild, *, base_url: str = "", fetcher=None,
                pobb_fetcher=None) -> str:
    """카탈로그 항목 → PoB 코드(없으면 빈 문자열)."""
    inline = build.inline_payload()
    if inline:
        return normalize_payload(inline)
    if build.pob_code_url:
        location = resolve_location(build.pob_code_url, base=base_url)
        return normalize_payload(read_source(location, fetcher=fetcher))
    if build.pobb_in:
        fetch = pobb_fetcher or pob.fetch_pobb
        return normalize_payload(fetch(build.pobb_in))
    return ""


@dataclass
class SyncReport:
    location: str = ""
    updated_label: str = ""
    added: list[str] = field(default_factory=list)
    updated: list[str] = field(default_factory=list)
    unchanged: list[str] = field(default_factory=list)
    preserved: list[str] = field(default_factory=list)
    custom_kept: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    dry_run: bool = False
    saved: bool = False

    @property
    def changed(self) -> bool:
        return bool(self.added or self.updated)

    def summary(self) -> str:
        bits = [
            f"추가 {len(self.added)}", f"갱신 {len(self.updated)}",
            f"변경 없음 {len(self.unchanged)}", f"보존 {len(self.preserved)}",
        ]
        if self.custom_kept:
            bits.append(f"내 빌드 {len(self.custom_kept)}개 그대로")
        if self.errors:
            bits.append(f"오류 {len(self.errors)}")
        head = "스타터 최신화" + ("(미리보기)" if self.dry_run else "")
        return f"{head}: " + " · ".join(bits)

    def lines(self) -> list[str]:
        out = [self.summary()]
        if self.updated_label:
            out.append(f"카탈로그 기준일: {self.updated_label}")
        if self.location:
            out.append(f"카탈로그: {self.location}")
        for build_id in self.added:
            out.append(f"  + {build_id}")
        for build_id in self.updated:
            out.append(f"  ↻ {build_id}")
        for message in self.errors:
            out.append(f"  ! {message}")
        if self.saved:
            out.append("라이브러리에 저장했습니다.")
        elif self.dry_run and self.changed:
            out.append("미리보기라 저장하지 않았습니다.")
        return out

    def to_dict(self) -> dict:
        return {
            "catalog": self.location,
            "catalog_updated": self.updated_label,
            "added": self.added,
            "updated": self.updated,
            "unchanged": self.unchanged,
            "preserved": self.preserved,
            "custom_kept": self.custom_kept,
            "errors": self.errors,
            "dry_run": self.dry_run,
            "saved": self.saved,
        }


def sync_library(lib: library_mod.BuildLibrary, *, url: str | None = None,
                 catalog: Catalog | None = None, fetcher=None, pobb_fetcher=None,
                 dry_run: bool = False, validate: bool = True) -> SyncReport:
    """원격 카탈로그를 라이브러리에 병합한다. 커스텀 빌드는 보존한다."""
    if catalog is None:
        catalog = load_catalog(url)
    report = SyncReport(location=catalog.location, updated_label=catalog.updated, dry_run=dry_run)
    catalog_ids: set[str] = set()

    for item in catalog.builds:
        catalog_ids.add(item.id)
        existing = lib.get(item.id)
        if existing is not None and existing.kind == "custom":
            report.custom_kept.append(item.id)
            continue
        current = ""
        if existing is not None:
            try:
                current = existing.payload().strip()
            except (library_mod.LibraryError, OSError):
                current = ""
        expected = item.sha256
        if existing is not None and expected and digest(current) == expected:
            # 본문이 같으면 내려받지 않고 메타데이터만 맞춘다
            changed_meta = any(
                (
                    existing.name != (item.name or existing.name),
                    existing.kind != (item.kind or existing.kind),
                    datafiles.normalize_game(existing.game) != item.game,
                    existing.origin != item.origin,
                    existing.note != item.note,
                )
            )
            existing.name = item.name or existing.name
            existing.kind = item.kind if item.kind in library_mod.KINDS else existing.kind
            existing.game = item.game
            existing.origin = item.origin
            existing.note = item.note
            if item.source:
                existing.source = item.source
            if changed_meta:
                report.updated.append(item.id)
            else:
                report.unchanged.append(item.id)
            continue

        try:
            code = payload_for(item, base_url=catalog.base_url, fetcher=fetcher,
                               pobb_fetcher=pobb_fetcher)
        except (CatalogError, pob.PobError, OSError) as exc:
            report.errors.append(f"{item.id}: {exc}")
            continue
        if validate and not code:
            report.errors.append(f"{item.id}: 빌드 본문이 없습니다.")
            continue

        if existing is None:
            entry = library_mod.BuildEntry(
                id=item.id,
                name=item.name or item.id,
                kind=item.kind if item.kind in library_mod.KINDS else "starter",
                game=item.game,
                origin=item.origin,
                source=item.source,
                note=item.note,
                code=code,
            )
            lib.builds.append(entry)
            lib._profiles.pop(entry.id, None)
            report.added.append(item.id)
        else:
            if existing.code.strip() == code:
                report.unchanged.append(item.id)
                continue
            existing.name = item.name or existing.name
            existing.kind = item.kind if item.kind in library_mod.KINDS else existing.kind
            existing.game = item.game
            existing.origin = item.origin
            existing.note = item.note
            existing.source = item.source or existing.source
            existing.code = code
            existing.code_file = ""
            lib._profiles.pop(existing.id, None)
            report.updated.append(item.id)

    for build in lib.builds:
        if build.id not in catalog_ids:
            report.preserved.append(build.id)

    if report.changed and not dry_run:
        lib.save()
        report.saved = True
    return report
