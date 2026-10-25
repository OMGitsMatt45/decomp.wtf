"""Period profiles preserve other workers' verified function settings."""

import json

import pytest

from decompnet.app.engine import RomNetwork
from decompnet.network import NetworkError
from decompnet.project import function_config
from decompnet.rom import psx_modules


def test_interleaved_profile_updates_preserve_both_functions(tmp_path, monkeypatch):
    database, workspace = tmp_path / "app.db", tmp_path / "projects"
    first = RomNetwork(database, workspace)
    second = RomNetwork(database, workspace)
    cfg = {"kind": "rom", "platform": "psx", "compiler": {
        "toolchain": "gcc-2.7.2-psx", "flags": ["-O2", "-G8"], "language": "c++"}}
    with first.store.tx() as db:
        project = db.execute("INSERT INTO projects(slug,root,config) VALUES(?,?,?)",
                             ("original-game", str(workspace), json.dumps(cfg))).lastrowid
        db.execute("INSERT INTO context_versions(project_id,version,header,unit) VALUES(?,?,?,?)",
                   (project, 1, "", ""))
        for name in ("first_function", "second_function"):
            db.execute("INSERT INTO functions(project_id,name,size,n_insns,status) VALUES(?,?,?,?,?)",
                       (project, name, 8, 2, "open"))
    original_profile, interleaved = psx_modules.profile, False

    def update_other_function(default, override):
        nonlocal interleaved
        if not interleaved:
            interleaved = True
            second.set_function_compiler("original-game", "second_function", {"flags": ["-O1", "-G8"]})
        return original_profile(default, override)

    # The second connection commits after the first worker reads the project.
    monkeypatch.setattr(psx_modules, "profile", update_other_function)
    selected = first.set_function_compiler("original-game", "first_function", {
        "toolchain": "gcc-2.8.1-psx", "flags": ["-O2", "-G0"]})
    assert interleaved and selected["toolchain"] == "gcc-2.8.1-psx"
    saved = first.cfg(first.project_row("original-game"))
    assert set(saved["function_compilers"]) == {"first_function", "second_function"}
    assert function_config(saved, "first_function")["compiler"]["flags"] == ["-O2", "-G0"]
    assert function_config(saved, "second_function")["compiler"]["flags"] == ["-O1", "-G8"]


@pytest.mark.parametrize("unit,version", [("", 2), ("source-unit", 2)],
                         ids=["updated-shared-header", "new-unit-header"])
def test_matched_profile_rejects_context_changes_during_validation(tmp_path, monkeypatch, unit, version):
    first = RomNetwork(tmp_path / "app.db", tmp_path)
    second = RomNetwork(tmp_path / "app.db", tmp_path)
    cfg = {"kind": "rom", "platform": "psx", "compiler": {
        "toolchain": "gcc-2.7.2-psx", "flags": ["-O2", "-G8"], "language": "c++"}}
    with first.store.tx() as db:
        project = db.execute("INSERT INTO projects(slug,root,config) VALUES(?,?,?)",
                             ("original-game", str(tmp_path), json.dumps(cfg))).lastrowid
        db.execute("INSERT INTO context_versions(project_id,version,header,unit) VALUES(?,?,?,?)",
                   (project, 1, "/* original context */", ""))
        db.execute("INSERT INTO functions(project_id,name,size,n_insns,status,unit) VALUES(?,?,?,?,?,?)",
                   (project, "matched_function", 8, 2, "matched", "source-unit"))

    def concurrent_context_edit(candidate, checked_header, only):
        assert checked_header == "/* original context */"
        assert only[0]["name"] == "matched_function"
        with second.store.tx() as db:
            db.execute("INSERT INTO context_versions(project_id,version,header,unit) VALUES(?,?,?,?)",
                       (project, version, "/* independently validated new context */", unit))
        return []

    # Compilation is irrelevant to this interleaving: it represents a successful
    # validation that finishes after another connection commits a new header.
    monkeypatch.setattr(first, "regression_test", concurrent_context_edit)
    with pytest.raises(NetworkError, match="context changed concurrently"):
        first.set_function_compiler("original-game", "matched_function", {"flags": ["-O2", "-G0"]})
    saved = first.cfg(first.project_row("original-game"))
    assert "matched_function" not in saved.get("function_compilers", {})
    assert first._context(project, "source-unit")["header"] == "/* independently validated new context */"
