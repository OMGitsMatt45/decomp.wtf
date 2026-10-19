"""C++ source selection, symbol linkage and draft generation."""

import pytest
import ctypes
from types import SimpleNamespace
from unittest.mock import Mock

from decompnet import compiler, cpp, seeds


@pytest.mark.parametrize("toolchain", ["gcc-2.7.2-kmc", "ido-7.1", "ido-5.3"])
def test_verified_n64_roms_default_to_cpp_and_explicit_c_is_respected(toolchain):
    cfg = {"kind": "rom", "platform": "n64", "compiler": {"toolchain": toolchain}}
    assert cpp.language(cfg) == "c++"
    cfg["compiler"]["language"] = "c"
    assert cpp.language(cfg) == "c"
    assert cpp.language({"kind": "rom", "platform": "psx", "compiler": {"toolchain": "gcc-2.7.2-psx"}}) == "c"
    assert cpp.language({"compiler": {"toolchain": "gcc-2.7.2-kmc"}}) == "c"
    with pytest.raises(ValueError, match="compiler.language"):
        cpp.language({"compiler": {"language": "rust"}})


def test_cpp_game_linkage_keeps_templates_classes_and_function_bodies():
    text = '''#define TRIPLE(x) ((x) * 3)
extern int total;
extern int callback(int);
int probe(int value);
void (*callback_pointer)(int);
template<class T> inline T triple(T value) { return value * 3; }
class Player { public: int hp; int get() const { return hp; } };
static int helper(int value) { return value + 1; }
namespace details { int helper(int value) { return value; } }
extern "C++" int overloaded(int value) { return value; }
int probe(int value) { return triple(value) + callback(total); }
struct Player *identity(struct Player *value) { return value; }
'''
    converted = cpp.game_abi(text)
    assert 'extern "C" int total;' in converted
    assert 'extern "C" int callback(int);' in converted
    assert 'extern "C" int probe(int value);' in converted
    assert 'extern "C" int probe(int value)' in converted
    assert 'extern "C" struct Player *identity' in converted
    for line in text.splitlines():
        if not line.startswith(("extern int", "int probe", "struct Player *identity")):
            assert line in converted
    assert cpp.game_abi(converted) == converted


def test_cpp_compilation_writes_cpp_and_uses_identical_linkage_in_context(tmp_path, monkeypatch):
    seen = []

    def execute(cfg, work, argv, timeout, **kwargs):
        seen.append(((work / "func.cpp").read_text(), (work / "include/context.h").read_text(), argv))
        (work / "func.o").write_bytes(b"object")
        return type("Result", (), {"returncode": 0, "stdout": "", "stderr": ""})()

    monkeypatch.setattr(compiler, "_exec", execute)
    cfg = compiler.CompilerConfig(["g++", "-c", "{src}", "-o", "{obj}"], language="c++", c_linkage=True, sandbox="none")
    result = compiler.compile_source(cfg, "extern int total;", "int probe(int v) { return v + total; }")
    assert result.ok
    source, context, command = seen[0]
    assert 'extern "C" int probe' in source and '#line 1 "func.cpp"' in source
    assert context == 'extern "C" int total;'
    assert any(argument.endswith("/func.cpp") for argument in command)


def test_ido_without_a_short_temp_path_returns_an_actionable_compile_error(tmp_path, monkeypatch):
    temp = tmp_path / "Windows profile with spaces"
    temp.mkdir()
    monkeypatch.setattr(compiler, "sys", SimpleNamespace(platform="win32"))
    monkeypatch.setattr(compiler.tempfile, "gettempdir", lambda: str(temp))
    monkeypatch.setattr(ctypes, "windll", SimpleNamespace(kernel32=SimpleNamespace(GetShortPathNameW=Mock(return_value=0))), raising=False)
    cfg = compiler.CompilerConfig(["NCC.exe", "-c", "{src}", "-o", "{obj}"], relative_paths=True, sandbox="none")
    result = compiler.compile_source(cfg, "", "int probe(int x) { return x+1; }")
    assert not result.ok and "Set TMP and TEMP" in result.log


@pytest.mark.parametrize("toolchain,target", [("gcc-2.7.2-kmc", "mips-gcc-c++"), ("ido-7.1", "mips-ido-c++"), ("ido-5.3", "mips-ido-c++")])
def test_cpp_drafts_request_the_m2c_cpp_target(monkeypatch, toolchain, target):
    calls = []
    monkeypatch.setattr(seeds, "run_m2c", lambda *args: calls.append(args) or "draft")
    assert seeds.generate_from_asm("asm", "probe", toolchain, language="c++") == "draft"
    assert calls[0][2] == target
