# Native Windows period compiler ports

PE32 Windows programs, running directly on Windows x64. No WSL, Linux, MSYS, Cygwin or emulator is required on Windows.

- `gcc-2.7.2-kmc-windows-i686-v2.zip`: original KMC GCC2.7.2 and binutils2.6 Windows host ports.
- `gcc-2.7.2-kmc-windows-source-v2.zip`: complete corresponding source, host portability patches, licenses and tested build recipe for KMC and binutils. Download beside the binary archives to rebuild.
- `binutils-2.6-windows-i686-v2.zip`: the same native binutils2.6 tools, for the PlayStation compiler packages.
- `gcc-2.7.2-psx-windows-x86_64-v2.zip`: original patched PSX GCC2.7.2, licenses, complete corresponding source and tested build recipe.
- `agbcc-windows-i686.zip`: native agbcc/old_agbcc, headers, licenses, complete corresponding source and build recipe.

GCC/binutils/agbcc retain their GPL licensing. The application pins immutable Git commit URLs and SHA-256 checksums. Compiler target logic is preserved; source patches only implement Windows host compatibility. Older filenames in the branch history are development candidates.
