"""Fail CI when a supposedly full run silently skips a required platform suite."""

import argparse
import sys
import xml.etree.ElementTree as ET
from collections import defaultdict


DS_REQUIRED = {"test_ds", "test_ds_rom_check", "test_ds_bios", "test_ds_modes", "test_ds_units",
               "test_ds_encrypted", "test_ds_inputs", "test_ds_modules", "test_ds_arm7", "test_objdiff_errors"}
REQUIRED = {"test_period_compilers", "test_n64_cpp", "test_ido_cpp", "test_ido_cfront",
            "test_psx", "test_psx_cpp", "test_ps2", "test_ps2_cpp", "test_gba", "test_gba_cpp",
            "test_gc", "test_export", "test_rom", "test_app_engine", "test_optional_tools",
            "test_assembly_exports", "test_boot_utilities", "test_overlays",
            "test_fork_judge", "test_fork_link", "test_fork_rooms", "test_collab", "test_bridge", "test_app_server"} | DS_REQUIRED


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("results")
    scope = parser.add_mutually_exclusive_group()
    scope.add_argument("--ds-only", action="store_true")
    scope.add_argument("--ds-execution", action="store_true")
    args = parser.parse_args()
    results = ET.parse(args.results)
    modules = defaultdict(list)
    for case in results.iter("testcase"):
        modules[case.get("classname", "").split(".")[-1]].append(case)
    required = ({"test_ds_execution"} if args.ds_execution else DS_REQUIRED if args.ds_only else
                REQUIRED | ({"test_windows_native"} if sys.platform == "win32" else set()))
    for module in sorted(required):
        cases = modules[module]
        assert cases, f"Required suite missing: {module}"
        assert all(len(case) == 0 for case in cases), f"Required suite failed or skipped: {module}"
        print(f"{module}: {len(cases)} passed, none skipped")
    cases = list(results.iter("testcase"))
    skipped = sum(case.find("skipped") is not None for case in cases)
    label = "Nintendo DS execution" if args.ds_execution else "Nintendo DS qualification" if args.ds_only else "Full operational check"
    print(f"::notice::{label}: {len(cases) - skipped} passed, {skipped} platform/private-ROM skips")


if __name__ == "__main__":
    main()
