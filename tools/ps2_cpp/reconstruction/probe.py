"""Compare an explicitly selected experimental frontend with original EE 2.96.

Linux investigation harness: the original driver and assembler are retained.
The candidate is invoked through a counted -B wrapper. Exit 1 means compilation
or parity failed. Passing this finite corpus alone would not certify a toolchain.
"""

import argparse
from io import BytesIO
import hashlib
import json
from pathlib import Path
import shlex
import sys

ROOT = Path(__file__).resolve().parents[3]
sys.path[:0] = [str(ROOT / "src"), str(ROOT)]

from decompnet import compiler, project
from elftools.elf.elffile import ELFFile
from elftools.elf.relocation import RelocationSection
from tests.fixtures.generate_native_compiler_parity import describe_functions


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def describe(obj: bytes) -> dict:
    elf = ELFFile(BytesIO(obj))
    data = {}
    for index, section in enumerate(elf.iter_sections()):
        if not section["sh_flags"] & 2 or section.name in (".text", ".reginfo"):
            continue
        entry = {"size": section["sh_size"], "alignment": section["sh_addralign"],
            "type": section["sh_type"], "relocations": []}
        if section["sh_type"] != "SHT_NOBITS":
            entry["bytes"] = section.data().hex()
        for relsec in elf.iter_sections():
            if not isinstance(relsec, RelocationSection) or relsec["sh_info"] != index:
                continue
            symbols = elf.get_section(relsec["sh_link"])
            for rel in relsec.iter_relocations():
                sym = symbols.get_symbol(rel["r_info_sym"])
                name = sym.name
                if not name and isinstance(sym["st_shndx"], int):
                    name = elf.get_section(sym["st_shndx"]).name
                entry["relocations"].append({"offset": rel["r_offset"], "type": rel["r_info_type"],
                    "symbol": name, "addend": rel["r_addend"] if rel.is_RELA() else None})
        data[section.name] = entry
    return {"functions": describe_functions(obj), "allocated_data": data}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--frontend", type=Path, required=True)
    parser.add_argument("--runner", default="", help="explicit command prefix, e.g. 'qemu-i386 -L /sysroot'")
    parser.add_argument("--execution", required=True, help="record actual execution method; never label emulation native")
    parser.add_argument("--work", type=Path, required=True)
    args = parser.parse_args()
    if sys.platform != "linux":
        parser.error("This counted POSIX wrapper harness runs on Linux")
    frontend, work = args.frontend.resolve(), args.work.resolve()
    if work.exists():
        parser.error("Use a fresh --work directory")
    work.mkdir(parents=True)
    marker = work / "invocations"
    front = work / "frontend"
    front.mkdir()
    wrapper = front / "cc1plus"
    wrapper.write_text("#!/bin/sh\nprintf '%s\\n' invoked >> " + shlex.quote(str(marker)) +
        "\nexec " + shlex.join([*shlex.split(args.runner), str(frontend)]) + ' "$@"\n')
    wrapper.chmod(0o755)
    report = {"experimental": True, "execution": args.execution, "frontend_sha256": sha(frontend.read_bytes()),
        "source_manifest_sha256": sha((Path(__file__).parent / "inputs.json").read_bytes()), "runs": []}

    def config(flags: list[str]):
        return project.compiler_config(ROOT, {"kind": "rom", "platform": "ps2", "compiler": {
            "toolchain": "ee-gcc-2.96", "language": "c++", "flags": flags, "sandbox": "none"}})

    for fixture in (ROOT / "tests/fixtures/ps2_cpp_features.cpp", Path(__file__).with_name("extended.cpp")):
        source = fixture.read_text()
        for flags in (["-O2", "-G8"], ["-O2", "-G0"], ["-O0", "-G8"], ["-O1", "-G8"], ["-Os", "-G8"]):
            cfg = config(flags)
            reference = compiler.compile_source(cfg, "", source)
            if not reference.ok:
                raise RuntimeError("Reference compiler failed: " + reference.log)
            expected = describe(reference.obj)
            cfg.cmd[1:1] = ["-B" + str(front) + "/"]
            candidate = compiler.compile_source(cfg, "", source)
            one = {"fixture": fixture.name, "source_sha256": sha(source.encode()), "flags": flags,
                "reference_ok": True, "reference_description_sha256": sha(json.dumps(expected, sort_keys=True).encode()),
                "reference_function_count": len(expected["functions"]), "candidate_ok": candidate.ok, "log": candidate.log}
            if candidate.ok:
                actual = describe(candidate.obj)
                one.update(exact=[n for n, v in expected["functions"].items() if actual["functions"].get(n) == v],
                    different=[n for n, v in expected["functions"].items() if actual["functions"].get(n) != v],
                    extra=[n for n in actual["functions"] if n not in expected["functions"]],
                    allocated_data_equal=expected["allocated_data"] == actual["allocated_data"])
                one["parity"] = not one["different"] and not one["extra"] and one["allocated_data_equal"]
                (work / (fixture.stem + "-" + "-".join(flags) + ".o")).write_bytes(candidate.obj)
            else:
                one["parity"] = False
            report["runs"].append(one)
            print(f"{fixture.name} {' '.join(flags)}: compiled={candidate.ok} parity={one['parity']}", flush=True)
    report["candidate_invocations"] = len(marker.read_text().splitlines()) if marker.exists() else 0
    report["all_parity"] = report["candidate_invocations"] == len(report["runs"]) and all(r["parity"] for r in report["runs"])
    (work / "report.json").write_text(json.dumps(report, indent=2) + "\n")
    return 0 if report["all_parity"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
