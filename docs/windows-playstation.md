# Native Windows PlayStation tools

Both PS1 C compilers, GCC 2.7.2 and GCC 2.8.1, have Windows source ports. Select
the compiler that matches the game in the app, then install it in **Compilers & tools**.
They run directly on Windows and preserve the original compiler target patches.
The compiler implementations and decompiled output remain C.

## GCC 2.8.1 and its assembler

The source port uses GNU GCC 2.8.1 with the target patches from
[`decompals/old-gcc` 0.17](https://github.com/decompals/old-gcc/tree/cf70ec58bce58128732062bc9930045c82904cbb).
Host changes handle Windows argument quoting, temporary files, child exit codes,
and the old build system. The C compiler's optimization passes are unchanged.

The existing binutils 2.6 assembler rejects expressions such as `%hi($LC0)` emitted
by GCC 2.8.1: its operand parser mistakes that local label for a register. Windows
therefore uses the pinned `binutils-mips` v0.10 assembler with `-EL -mips1 -mabi=32`.
GCC 2.7.2 keeps its original binutils 2.6. Existing Linux toolchain entries are unchanged.

Windows integration compares code and relocations for eight functions from each
PS1 compiler against the pinned Linux compiler. The GCC 2.8.1 reference uses that
same newer assembler, so this proves compiler parity across hosts; it does not
claim equivalence with every original PSY-Q assembler. Fixtures cover branches,
loops, calls, strings, globals, floating point constants, 64-bit arithmetic,
structures and a switch table. The tests also exercise preprocessing and failed builds.

The native archive includes `corresponding-source.tar.gz`, licenses and a clean
build recipe. The checked-in recipe is [`tools/windows/build-psx281.py`](../tools/windows/build-psx281.py).

## PS2: native assembler available, EE-GCC 2.96 still unavailable

The native `binutils-mips` tools already support the Emotion Engine. Windows CI
assembles little-endian R5900 code containing `lq`, `paddw` and `sq` without WSL.
This provides the assembler; it does not provide the matching C compiler.

The app's PS2 compiler is specifically `2.96-ee-001003-1`, from
[`decompme/compilers`](https://github.com/decompme/compilers/tree/master/platforms/ps2/ee-gcc2.96).
Its Linux archive is pinned to SHA-256
`0590d2ca9da8f5903889d66761220d14b47a8d14ba987ca53db84a1650a1fd0a`.
Matching source or a verified native Windows build has not been located.

Sources investigated include the public branches of
[`GirianSeed/ee-gcc`](https://github.com/GirianSeed/ee-gcc/branches),
[`aap/ee-gcc`](https://github.com/aap/ee-gcc/branches), and
[`SSXModding/ps2-ee-toolchain`](https://github.com/SSXModding/ps2-ee-toolchain).
The EE sources there identify as 2.9-era releases, including `2.9-ee-991111`, rather
than `2.96-ee-001003-1`. They cannot be substituted for a matching decompilation.
An independently documented [compiler investigation](https://github.com/z3xox/Tenkaichi3Decomp/blob/ec3c85a98cffd9cd22c22ac14cd62fb584d23664/docs/decomp_guide.md)
also reports substantial output differences between those versions.

To enable EE-GCC 2.96, the next useful input is its corresponding source or a
verifiable Windows build of that exact compiler. A source port must then pass
machine-code and relocation comparisons against the pinned Linux binary before
the Windows catalog enables it. The app continues to mark it unavailable.
