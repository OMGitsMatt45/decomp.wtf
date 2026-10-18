# Native Windows period compiler ports

These are real PE32 programs for Windows x64, built from the original compiler sources with MinGW.
They do not require WSL, Linux, MSYS, Cygwin, or an emulator when run on Windows.

- `gcc-2.7.2-kmc-windows-i686.zip`: original KMC GCC 2.7.2 and binutils 2.6 Windows host port.
- `gcc-2.7.2-kmc-windows-source.zip`: complete corresponding source, portability patches, licenses and build recipe for the KMC binaries. Download alongside the binary archive to rebuild.
- `agbcc-windows-i686.zip`: native agbcc/old_agbcc, headers, licenses, complete corresponding source and build recipe.

GCC/binutils/agbcc retain their GPL licensing; license texts and source provenance are in the archives. The application pins immutable Git commit URLs and SHA-256 checksums for these downloads. Compiler target logic is preserved; host portability changes are included as source patches.
