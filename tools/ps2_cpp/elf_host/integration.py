"""Run existing PS2 integration tests with an explicit research-only provider.

No production registry or installation manifest is modified. A temporary Python
bootstrap exposes the locally built, unregistered host to the tests and their
export/build subprocesses. Linux execution requires an explicit wibo runner;
it must never be reported as native Windows validation.
"""

import argparse
from dataclasses import replace
import json
import os
from pathlib import Path
import shlex
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[3]
sys.path[:0] = [str(ROOT), str(ROOT / "src")]
ARCHIVE_SHA = "0590d2ca9da8f5903889d66761220d14b47a8d14ba987ca53db84a1650a1fd0a"


def activate() -> None:
    """Scoped to the spawned research-test process and its children only."""
    from decompnet import toolchains

    root = Path(os.environ["DECOMP_EE_HOST_TEST_ROOT"])
    metadata = json.loads((root / "host-build.json").read_text())
    if metadata["archive_sha256"] != ARCHIVE_SHA:
        raise ValueError("Not a research build of the pinned original compiler")
    if any((root / (p + ".exe")).read_bytes()[:2] != b"MZ" for p in metadata["tools"]):
        raise ValueError("Missing Windows compiler host executable")
    get = toolchains.get
    path = toolchains.path
    installed = toolchains.installed
    original = get("ee-gcc-2.96")
    cc = ["{tc}/bin/ee-gcc" + (".exe" if sys.platform == "win32" else ""), "-c"]
    research = replace(original, cc=cc, windows_cc=cc, requires=[], windows_requires=[],
                       parts=[{"platforms": [toolchains.current_platform()], "url": "research-only-unregistered"}])

    def lookup(tid):
        return research if tid == original.id else get(tid)

    def directory(tid, linux=None):
        return root if tid == original.id else path(tid, linux)

    def presence(tid, linux=None):
        if tid == original.id:
            return {"platform": toolchains.current_platform(), "research_only": True,
                    "original_archive_sha256": ARCHIVE_SHA}
        return installed(tid, linux)

    toolchains.get = lookup
    toolchains.path = directory
    toolchains.installed = presence


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--toolchain", required=True, type=Path)
    parser.add_argument("--runner", default="", help="required explicit wibo prefix on Linux")
    parser.add_argument("--work", required=True, type=Path)
    args = parser.parse_args()
    root, work = args.toolchain.resolve(), args.work.resolve()
    if work.exists():
        parser.error("Use a fresh --work directory")
    work.mkdir(parents=True)
    original_driver = None
    if sys.platform != "win32":
        if not args.runner:
            parser.error("Linux research tests require --runner and are not native Windows tests")
        # Keep the original payload and use a shell shim solely for Linux test
        # process launching; the child compiler is the exact Windows PE host.
        driver = root / "bin/ee-gcc"
        if driver.read_bytes()[:4] != b"\x7fELF":
            parser.error("Use a fresh host build (original driver already changed)")
        driver.rename(driver.with_suffix(".research-elf"))
        original_driver = driver.with_suffix(".research-elf")
        command = [*shlex.split(args.runner), str(root / "bin/ee-gcc.exe")]
        driver.write_text("#!/bin/sh\nexec " + shlex.join(command) + ' "$@"\n')
        driver.chmod(0o755)
    bootstrap = work / "bootstrap"
    bootstrap.mkdir()
    (bootstrap / "sitecustomize.py").write_text("from tools.ps2_cpp.elf_host.integration import activate\nactivate()\n")
    env = os.environ.copy()
    env.update(DECOMP_EE_HOST_TEST_ROOT=str(root), DECOMP_TEST_PS2_CPP="1", DECOMP_UPDATES="off",
               PYTHONPATH=os.pathsep.join([str(bootstrap), str(ROOT), str(ROOT / "src"), env.get("PYTHONPATH", "")]))
    results = work / "results.xml"
    command = [sys.executable, "-m", "pytest", "-q", "tests/test_ps2.py", "tests/test_ps2_cpp.py",
               "--junitxml=" + str(results)]
    try:
        with (work / "output.log").open("w") as log:
            result = subprocess.run(command, cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT)
    finally:
        if original_driver:
            driver.unlink()
            original_driver.rename(driver)
    print((work / "output.log").read_text()[-6000:])
    # Required integration cannot pass through skipped tests or an empty run.
    import xml.etree.ElementTree as E
    if not results.exists():
        return result.returncode or 1
    suites = list(E.parse(results).iter("testsuite"))
    count = sum(int(s.get("tests", 0)) for s in suites)
    skipped = sum(int(s.get("skipped", 0)) for s in suites)
    summary = dict(execution="native Windows" if sys.platform == "win32" else "Windows PE under wibo on Linux",
                   original_archive_sha256=ARCHIVE_SHA, exit_code=result.returncode,
                   tests=count, skipped=skipped, research_provider=True, production_registry_changed=False)
    (work / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    if step_summary := os.environ.get("GITHUB_STEP_SUMMARY"):
        with Path(step_summary).open("a", encoding="utf-8") as stream:
            stream.write("## EE integration\n\n```json\n" + json.dumps(summary, indent=2) + "\n```\n")
            if result.returncode:
                stream.write("\n```text\n" + (work / "output.log").read_text()[-12000:] + "\n```\n")
    return result.returncode or (1 if not count or skipped else 0)


if __name__ == "__main__":
    raise SystemExit(main())
