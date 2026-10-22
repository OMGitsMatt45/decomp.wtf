"""Fail CI when a supposedly full run silently skips a required platform suite."""

import sys
import xml.etree.ElementTree as ET
from collections import defaultdict


REQUIRED = {"test_period_compilers", "test_n64_cpp", "test_ido_cpp", "test_ido_cfront",
            "test_psx", "test_psx_cpp", "test_ps2", "test_ps2_cpp", "test_gba", "test_gba_cpp",
            "test_gc", "test_ds", "test_ds_rom_check", "test_ds_bios", "test_ds_modes", "test_ds_units",
            "test_ds_encrypted", "test_export", "test_rom", "test_app_engine", "test_optional_tools",
            "test_assembly_exports", "test_boot_utilities", "test_overlays",
            "test_fork_judge", "test_fork_link", "test_fork_rooms", "test_collab", "test_bridge", "test_app_server"}


def main():
    results = ET.parse(sys.argv[1])
    modules = defaultdict(list)
    for case in results.iter("testcase"):
        modules[case.get("classname", "").split(".")[-1]].append(case)
    required = REQUIRED | ({"test_windows_native"} if sys.platform == "win32" else set())
    for module in sorted(required):
        cases = modules[module]
        assert cases, f"Required suite missing: {module}"
        assert all(len(case) == 0 for case in cases), f"Required suite failed or skipped: {module}"
        print(f"{module}: {len(cases)} passed, none skipped")
    cases = list(results.iter("testcase"))
    skipped = sum(case.find("skipped") is not None for case in cases)
    print(f"::notice::Full operational check: {len(cases) - skipped} passed, {skipped} platform/private-ROM skips")


if __name__ == "__main__":
    main()
