"""Portable, declarative compiler profiles shared by N64 projects and rooms."""

from .. import cpp, toolchains

COMPILERS = ("ido-5.3", "ido-7.1", "gcc-2.7.2-kmc")


def profile(default: dict, override: dict) -> dict:
    if not isinstance(override, dict) or set(override) - {"toolchain", "flags", "language", "cpp_frontend"}:
        raise ValueError("N64 function profiles accept toolchain, flags, language and cpp_frontend only")
    name = override.get("toolchain", default.get("toolchain"))
    if name not in COMPILERS:
        raise ValueError("choose an N64 IDO 5.3, IDO 7.1 or KMC compiler")
    same = name == default.get("toolchain")
    flags = override.get("flags", default.get("flags", toolchains.get(name).flags) if same else toolchains.get(name).flags)
    if not isinstance(flags, list) or len(flags) > 128 or any(
            not isinstance(f, str) or len(f) > 2048 or any(c in f for c in "\0\r\n") for f in flags):
        raise ValueError("compiler flags must be a bounded list of single-line strings")
    language = override.get("language", default.get("language", "c++"))
    result = {"toolchain": name, "flags": list(flags), "language": language}
    cpp.language({"kind": "rom", "platform": "n64", "compiler": result})
    frontend = override.get("cpp_frontend", default.get("cpp_frontend", "edg") if same else "edg")
    if frontend not in ("edg", "cfront") or (frontend == "cfront" and name != "ido-5.3"):
        raise ValueError("classic cfront requires IDO 5.3; IDO 7.1 uses EDG")
    if name.startswith("ido-"):
        result["cpp_frontend"] = frontend
    return result


def optimization(compiler: dict, level: str) -> dict:
    if level not in ("O0", "O1", "O2"):
        raise ValueError("optimization must be O0, O1 or O2")
    return {**compiler, "flags": ["-" + level, *[f for f in compiler["flags"] if not f.startswith("-O")]]}
