from __future__ import annotations

import json

from conftest import FIXTURES, make_pob_code
from poe_checker import cli


def _library_file(tmp_path):
    path = tmp_path / "library.json"
    path.write_text(
        json.dumps(
            {
                "schema": 1,
                "builds": [
                    {
                        "id": "rf",
                        "name": "RF 빌드",
                        "kind": "custom",
                        "code": make_pob_code(main="Righteous Fire"),
                    }
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return path


def test_cli_json_output(tmp_path, capsys):
    lib = _library_file(tmp_path)
    out = tmp_path / "report.json"
    code = cli.main(
        [
            "--patch-file",
            str(FIXTURES / "patch_notes_synthetic_full.txt"),
            "--library",
            str(lib),
            "--json",
            str(out),
            "--quiet",
        ]
    )
    assert code == 0
    payload = json.loads(out.read_text(encoding="utf-8"))
    assert payload["tool"]
    assert payload["builds"][0]["verdict"] == "red"
    assert payload["buffs"]


def test_cli_text_and_md_output(tmp_path):
    lib = _library_file(tmp_path)
    txt = tmp_path / "report.txt"
    md = tmp_path / "report.md"
    code = cli.main(
        [
            "--patch-file",
            str(FIXTURES / "patch_notes_330_new_gems.txt"),
            "--library",
            str(lib),
            "--out",
            str(txt),
            "--md",
            str(md),
            "--quiet",
        ]
    )
    assert code == 0
    assert "스타터 생존 검증" in txt.read_text(encoding="utf-8")
    assert md.read_text(encoding="utf-8").startswith("# ")


def test_cli_list_builds(tmp_path, capsys):
    lib = _library_file(tmp_path)
    assert cli.main(["--library", str(lib), "--list-builds"]) == 0
    captured = capsys.readouterr().out
    assert "RF 빌드" in captured


def test_cli_add_build(tmp_path):
    lib = _library_file(tmp_path)
    code = cli.main(
        [
            "--library",
            str(lib),
            "--add-build",
            make_pob_code(main="Winter Orb"),
            "--name",
            "콜드 빌드",
        ]
    )
    assert code == 0
    payload = json.loads(lib.read_text(encoding="utf-8"))
    assert any(row["name"] == "콜드 빌드" for row in payload["builds"])


def test_cli_missing_source(tmp_path):
    lib = _library_file(tmp_path)
    assert cli.main(["--library", str(lib)]) == 2


def test_cli_bad_patch_file(tmp_path):
    lib = _library_file(tmp_path)
    assert cli.main(["--library", str(lib), "--patch-file", str(tmp_path / "nope.txt")]) == 3
