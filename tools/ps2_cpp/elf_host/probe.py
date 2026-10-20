"""Measure original EE compiler parity; never equate wibo with native Windows.

Use --reference-command to record Linux results, then --golden to replay the
same corpus on Windows. All successful cases compare complete object bytes.
Negative cases require a nonzero exit AND no object. Result files are fresh.
"""

import argparse
import hashlib
import json
import os
from pathlib import Path
import shlex
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[3]
sys.path[:0] = [str(ROOT), str(ROOT / "src")]
from decompnet import elfobj


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def cases(work: Path) -> list[dict]:
    sources = {
        "features.cpp": (ROOT / "tests/fixtures/ps2_cpp_features.cpp").read_text(encoding="utf-8"),
        "extended.cpp": (ROOT / "tools/ps2_cpp/reconstruction/extended.cpp").read_text(encoding="utf-8"),
        "game.c": (ROOT / "projects/demo-n64/original/game.c").read_text(encoding="utf-8"),
        "game.h": (ROOT / "projects/demo-n64/original/game.h").read_text(encoding="utf-8"),
        "quoted.cpp": 'typedef TYPE T; extern "C" int size() { return sizeof(T); }\n'
                      'extern "C" const char *message() { return MESSAGE; }\n',
        "include.cpp": '#include "one.h"\n#include "two.h"\n'
                       'extern "C" int includes() { return ONE + TWO; }\n',
        "pipeline.cpp": 'extern "C" int pipeline_table[] = {' + ','.join(str(i) for i in range(6000)) + '};\n',
        "invalid.cpp": "template <class T> T broken( { return ; }\n",
        "missing.cpp": '#include "does-not-exist.h"\n',
        "floating.cpp": 'extern "C" double precise(double x) { return (x + 0.1) * 1.2345678901234567; }\n'
                        'extern "C" float tiny(float x) { return x + 1.1754943508222875e-38f; }\n'
                        'extern "C" double wide() { return 9007199254740992.0 + 1.0; }\n',
        "include space/one.h": "#pragma once\n#define ONE 17\n",
        "include space/two.h": "#pragma once\n#define TWO 23\n",
    }
    for name, text in sources.items():
        path = work / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8", newline="\n")
    result = []
    for source, language in (("features.cpp", "c++"), ("extended.cpp", "c++"), ("game.c", "c")):
        for flags in (["-O2", "-G8"], ["-O2", "-G0"], ["-O0", "-G8"], ["-O1", "-G8"], ["-Os", "-G8"]):
            result.append(dict(name=Path(source).stem + "-" + "-".join(flags), source=source,
                               language=language, flags=flags, success=True))
    result += [
        dict(name="floating", source="floating.cpp", language="c++", flags=["-O2"], success=True),
        dict(name="quoted", source="quoted.cpp", language="c++", flags=["-O2", "-DTYPE=unsigned int", '-DMESSAGE="space and \\"quotes\\""'], success=True),
        dict(name="includes", source="include.cpp", language="c++", flags=["-O2", "-Iinclude space"], success=True),
        dict(name="invalid-cpp", source="invalid.cpp", language="c++", flags=[], success=False),
        dict(name="missing-header", source="missing.cpp", language="c++", flags=[], success=False),
        dict(name="cpp-rejected-as-c", source="features.cpp", language="c", flags=[], success=False),
        dict(name="preprocessor", source="include.cpp", language="c++", flags=["-O2", "-Iinclude space"], success=True, preprocess=True),
    ]
    result += [
        dict(name="pipe-cpp", source="extended.cpp", language="c++", flags=["-pipe", "-O2"], success=True),
        dict(name="pipe-c", source="game.c", language="c", flags=["-pipe", "-O2"], success=True),
        dict(name="pipe-large", source="pipeline.cpp", language="c++", flags=["-pipe", "-O2"], success=True),
        dict(name="pipe-invalid", source="invalid.cpp", language="c++", flags=["-pipe"], success=False),
        dict(name="pipe-missing-header", source="missing.cpp", language="c++", flags=["-pipe"], success=False),
    ]
    for case in result:
        case["source_sha256"] = digest(sources[case["source"]].encode())
    return result


def run(command: list[str], case: dict, work: Path, prefix: str) -> dict:
    output = work / (prefix + "-" + case["name"] + (".i" if case.get("preprocess") else ".o"))
    args = [*command, "-E" if case.get("preprocess") else "-c", "-x", case["language"], *case["flags"]]
    if case["language"] == "c++":
        args += ["-fno-exceptions", "-fno-rtti", "-fconserve-space"]
    proc = subprocess.run([*args, case["source"], "-o", str(output)], cwd=work,
                          stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=60)
    result = dict(exit_code=proc.returncode, log=proc.stdout.decode(errors="replace"), object_present=output.exists())
    if output.exists():
        obj = output.read_bytes()
        result.update(object_sha256=digest(obj))
        if not case.get("preprocess"):
            result["functions"] = len(elfobj.list_functions(obj))
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidate-command", required=True, help="shell-quoted command prefix; never executed by a shell")
    reference = parser.add_mutually_exclusive_group(required=True)
    reference.add_argument("--reference-command")
    reference.add_argument("--golden", type=Path)
    parser.add_argument("--execution", required=True, help="actual execution method: native Windows, wibo on Linux, etc.")
    parser.add_argument("--work", required=True, type=Path)
    args = parser.parse_args()
    work = args.work.resolve()
    if work.exists():
        parser.error("Use a fresh --work directory")
    work.mkdir(parents=True)
    selected = cases(work)
    inputs = {p.relative_to(work).as_posix(): digest(p.read_bytes()) for p in sorted(work.rglob("*")) if p.is_file()}
    golden = json.loads(args.golden.read_text()) if args.golden else None
    if golden and (golden.get("cases") != selected or golden.get("inputs") != inputs):
        if os.environ.get("GITHUB_ACTIONS"):
            changed = [p for p, sha in inputs.items() if golden.get("inputs", {}).get(p) != sha]
            print("::error title=EE corpus mismatch::Reference input hashes differ: " + ", ".join(changed), flush=True)
        parser.error("Reference corpus/flags/source hashes differ")
    reference_results = []
    results = []
    for index, case in enumerate(selected):
        expected = run(shlex.split(args.reference_command), case, work, "reference") if not golden else golden["results"][index]
        if (expected["exit_code"] == 0) != case["success"] or expected["object_present"] != case["success"]:
            raise RuntimeError(f"Broken reference case {case['name']}: {expected}")
        reference_results.append(expected)
        actual = run(shlex.split(args.candidate_command), case, work, "candidate")
        passed = actual["exit_code"] == expected["exit_code"] and actual["object_present"] == case["success"]
        if case["success"]:
            passed = passed and (case.get("preprocess") or case["name"] == "pipe-large" or actual.get("functions", 0) > 0) \
                and actual.get("object_sha256") == expected["object_sha256"]
        results.append(dict(case=case["name"], passed=passed, candidate=actual))
        print(f"{case['name']}: {'PASS' if passed else 'FAIL'}", flush=True)
        if not passed and os.environ.get("GITHUB_ACTIONS"):
            diagnostic = json.dumps(actual, ensure_ascii=True)[-3000:]
            diagnostic = diagnostic.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")
            print(f"::error title=EE parity {case['name']}::{diagnostic}", flush=True)
    report = dict(experimental=True, execution=args.execution, inputs=inputs,
                  candidate_command=shlex.split(args.candidate_command),
                  all_passed=all(r["passed"] for r in results),
                  counts=dict(passed=sum(r["passed"] for r in results), total=len(results),
                              successful_compilations=sum(c["success"] and not c.get("preprocess", False) for c in selected),
                              preprocessing_checks=sum(c.get("preprocess", False) for c in selected)), runs=results)
    (work / "report.json").write_text(json.dumps(report, indent=2) + "\n")
    (work / "reference.json").write_text(json.dumps(dict(cases=selected, inputs=inputs, results=reference_results), indent=2) + "\n")
    if summary := os.environ.get("GITHUB_STEP_SUMMARY"):
        text = f"## EE compiler parity\n\n{report['counts']['passed']}/{len(results)} passed. Execution: {args.execution}.\n"
        for result in results:
            if not result["passed"]:
                text += f"\n### {result['case']}\n\n```json\n{json.dumps(result['candidate'], indent=2)[-6000:]}\n```\n"
        with Path(summary).open("a", encoding="utf-8") as stream:
            stream.write(text)
    return 0 if report["all_passed"] else 1


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as error:
        if os.environ.get("GITHUB_ACTIONS"):
            diagnostic = str(error).replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")
            print(f"::error title=EE parity runner::{type(error).__name__}: {diagnostic}", flush=True)
        raise
