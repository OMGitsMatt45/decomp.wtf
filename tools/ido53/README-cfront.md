# Classic IDO 5.3 host overlay

`build-cfront.sh` builds the original classic `CC`, `cfront`, `ptcomp` and
`markc++` and `ptlink` from `decompals/ido-static-recomp` revision
`d5aec59932034b8a20f23f471297a55c45dcbc45`. `native-cfront.patch` contains the
runtime/recompiler changes; `cfront_host.h` implements the driver's observed
host utility operations. The classic driver is installed as `classic-CC` (`classic-CC.exe` on Windows),
so it cannot collide with the original C driver `cc.exe` on a case-insensitive
filesystem. Installation checks the existing backend hashes before and after
copying the overlay. The existing EDG build recipe is independent.

The original compiler inputs are proprietary SGI programs. Their SHA-256
identities are recorded in `cfront-build.json` and checked on installation.
The build emits both the overlay and a corresponding source/input
archive. The existing 5.3 package supplies its original backend and bundled
Windows runtime, with the corresponding runtime source described in
[the application documentation](../../docs/ido-cpp.md).

Build on Linux x86-64, or in an x86-64 MSYS2 shell with `gcc make git python tar`:

```sh
bash tools/ido53/build-cfront.sh /absolute/fresh-build /absolute/artifacts
```

Use the application's native Python environment to install and test it:

```sh
decompnet toolchain install ido-5.3 --accept-license
python -m tools.ido53.install_cfront /absolute/fresh-build/package
DECOMP_TEST_IDO_CFRONT=1 python -m pytest tests/test_ido_cfront.py
```

The tests also require the pinned `binutils-mips` and `m2c` toolchains.
PowerShell sets the switch with `$env:DECOMP_TEST_IDO_CFRONT = '1'`.
They compile with only System32 on PATH on Windows, reject WSL calls, check
original-IRIX code/relocation references, match a C-origin target and rebuild a
clean exported ROM. Verified packages and corresponding sources are published after both native hosts pass.
The regular `ido-5.3` installation includes this overlay; local builds remain optional.

`verify_cfront.py` independently checks the fixtures against the unmodified
IRIX cfront under checksum-pinned QEMU IRIX `v2.11-deb`. The IRIX root needs
`libC.so` linked from its original `libC.a`; see the workflow for that command.
QEMU and the reference shell wrapper are test-only. The application uses host
executables and its Python adapter; it has no WSL, QEMU or shell dependency.

The supported pipeline emits objects for matching and ROM rebuilding. Native
`ptlink` handles cross-unit instantiation, dependency/checksum invalidation and
invalid definitions. `python -m decompnet.ido_prelink --work PROJECT --output combined.o left.o right.o`
supplies its control files and uses the pinned N64 GNU linker for relocatable
output, preserving previous output on failure. See the application documentation
for include/flag arguments and the original argument grammar's limits.
IRIX application executable/startup/shared-library processing remains separate.
