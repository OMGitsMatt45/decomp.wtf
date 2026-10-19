"""Diagnose native IDO path/environment handling with no MSYS on PATH."""
import os
from pathlib import Path
import subprocess
import sys
import tempfile

tools = Path(sys.argv[1]).resolve()
root = tools.parent / "IDO source check"
root.mkdir(exist_ok=True)
cpp = root / "probe.cpp"
cpp.write_text('#ifndef __cplusplus\n#error C++ required\n#endif\ntemplate<class T> class Box { public: T value; };\nextern "C" int probe(int x) { Box<int> b; int &r = b.value; r = x + 1; return b.value; }\n', encoding="utf-8", newline="\n")
c = root / "probe.c"
c.write_text("int probe(int x) { return x+1; }\n", encoding="utf-8", newline="\n")
base = {**os.environ, "PATH": str(Path(os.environ["SystemRoot"]) / "System32"), "TMPDIR": Path(tempfile.gettempdir()).as_posix()}
passed = False
for mode, driver, source, override in [("relative", "NCC.exe", cpp, False), ("windows", "NCC.exe", cpp, False), ("posix", "NCC.exe", cpp, False),
                                       ("redirect", "NCC.exe", cpp, True), ("c", "cc.exe", c, True)]:
    obj = root / f"{mode}.o"
    env = dict(base)
    env.pop("USR_LIB", None)
    if override:
        env["USR_LIB"] = tools.as_posix()
    path = str if mode == "windows" else lambda p: p.as_posix()
    argv = [path(tools / driver), "-v", "-c", "-O2", "-mips2", "-G", "0", "-non_shared", path(source), "-o", path(obj)]
    if mode == "relative":
        argv[-3:] = [source.name, "-o", obj.name]
    result = subprocess.run(argv, env=env, cwd=root, capture_output=True, text=True, errors="replace", timeout=60)
    print(f"{mode}: exit={result.returncode} (0x{result.returncode & 0xffffffff:08x}), object={obj.exists()}", flush=True)
    print(result.stdout + result.stderr, flush=True)
    if driver == "NCC.exe" and result.returncode == 0 and obj.exists():
        assert obj.read_bytes().startswith(b"\x7fELF")
        passed = True
print("Created files:", [p.name for p in root.iterdir()], flush=True)
for path in root.glob("*.stackdump"):
    print(path.name, path.read_text(errors="replace"), flush=True)
assert passed, "No native C++ invocation succeeded"
