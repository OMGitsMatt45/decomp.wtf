"""C++ source selection, symbol linkage and draft generation."""

import pytest
import ctypes
from types import SimpleNamespace
from unittest.mock import Mock

from decompnet import compiler, cpp, project, seeds, toolchains, wsl


@pytest.mark.parametrize("platform,toolchain", [("n64", "gcc-2.7.2-kmc"), ("n64", "ido-7.1"), ("n64", "ido-5.3"), ("gba", "agbcc"), ("psx", "gcc-2.7.2-psx"), ("psx", "gcc-2.8.1-psx"), ("ps2", "ee-gcc-2.96")])
def test_verified_roms_default_to_cpp_and_explicit_c_is_respected(platform, toolchain):
    cfg = {"kind": "rom", "platform": platform, "compiler": {"toolchain": toolchain}}
    assert cpp.language(cfg) == "c++"
    cfg["compiler"]["language"] = "c"
    assert cpp.language(cfg) == "c"
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
void *operator new(unsigned int);
extern void operator delete(void *);
void *operator new[](unsigned int size) { return allocate(size); }
extern "C++" { int overloaded(double); }
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


def test_cpp_staging_normalizes_nested_headers_without_editing_user_files(tmp_path, monkeypatch):
    include = tmp_path / 'headers'
    (include / 'nested').mkdir(parents=True)
    header = include / 'nested/policy.h'
    header.write_bytes(b'#define STEP(x) \\\r\n ((x) + 1)\r\n')
    asset = include / 'unchanged.bin'
    asset.write_bytes(b'\x00\r\n\xff')
    def execute(cfg, work, argv, timeout, **kwargs):
        assert b'\r' not in (work / 'func.cpp').read_bytes()
        assert b'\r' not in (work / 'include/context.h').read_bytes()
        assert b'\r' not in (work / 'include/nested/policy.h').read_bytes()
        assert (work / 'include/unchanged.bin').read_bytes() == asset.read_bytes()
        (work / 'func.o').write_bytes(b'object')
        return SimpleNamespace(returncode=0, stdout='', stderr='')
    monkeypatch.setattr(compiler, '_exec', execute)
    cfg = compiler.CompilerConfig(['g++', '-c', '{src}', '-o', '{obj}'], language='c++',
                                  include_dirs=[include], sandbox='none')
    result = compiler.compile_source(cfg, '#include "nested/policy.h"\r\n', 'int probe(int x) { return STEP(x); }\r\n')
    assert result.ok, result.log
    assert b'\r\n' in header.read_bytes()


@pytest.mark.parametrize("toolchain,target", [("gcc-2.7.2-kmc", "mips-gcc-c++"), ("ido-7.1", "mips-ido-c++"), ("ido-5.3", "mips-ido-c++"), ("agbcc", "gba-gcc-c++"), ("gcc-2.7.2-psx", "mipsel-gcc-c++"), ("gcc-2.8.1-psx", "mipsel-gcc-c++"), ("ee-gcc-2.96", "mipsee-gcc-c++")])
def test_cpp_drafts_request_the_m2c_cpp_target(monkeypatch, toolchain, target):
    calls = []
    monkeypatch.setattr(seeds, "run_m2c", lambda *args: calls.append(args) or "draft")
    assert seeds.generate_from_asm("asm", "probe", toolchain, language="c++") == "draft"
    assert calls[0][2] == target


def test_ps2_cpp_on_windows_requires_installation_of_its_native_package(tmp_path, monkeypatch):
    monkeypatch.setenv("DECOMP_RUNTIME", "native")
    monkeypatch.setenv("DECOMPNET_TOOLCHAINS", str(tmp_path / "empty native tools"))
    monkeypatch.delenv(toolchains.EE_NATIVE_ROOT, raising=False)
    monkeypatch.setattr(toolchains, "current_platform", lambda: "windows-x86_64")
    monkeypatch.setattr(wsl, "status", lambda: pytest.fail("PS2 must not implicitly start WSL"))
    monkeypatch.setattr(wsl, "run", lambda *a, **kw: pytest.fail("PS2 must not run WSL"))
    with pytest.raises(toolchains.ToolchainError, match="ee-gcc-2.96.*is not installed"):
        project.compiler_config(tmp_path, {"kind": "rom", "platform": "ps2", "compiler": {
            "toolchain": "ee-gcc-2.96", "language": "c++"}})
