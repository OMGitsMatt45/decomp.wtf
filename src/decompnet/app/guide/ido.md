# Matching IDO 5.3 / 7.1 (most first-party N64 games)

Usual flags: `-O2 -mips2` (some files `-O1`, `-g`, or `-mips1`). If almost nothing matches, the project
may need a different version (5.3 vs 7.1) or flags: tell the user, they can switch it in the app.

Source language
- IDO 5.3/7.1 ROM projects default to C++ through the original SGI/EDG frontend (`NCC`/`edgcpfe`),
  retaining IDO's optimizer, code generator and assembler. Keep original game functions and external
  declarations at C linkage; the judge and export add this to plain global declarations/functions.
- This is a period C++ dialect. Templates, classes and references work, but use no host standard
  headers or unsupported runtime features. The same expression can generate different code through
  the C and C++ frontends; matching still requires the original bytes and relocated data.
- Explicit `compiler.language = "c"` selects the original C frontend. Each IDO version uses its
  own SGI/EDG 2.19 binary and original backend; never switch 5.3 to 7.1 to accept C++ syntax.
- Exports record the selected `cpp_frontend`. IDO 5.3 can explicitly select `"cfront"` after
  installing/updating `ido-5.3` normally. This retains the original classic CC driver,
  cfront, repository helpers and 5.3 backend. Missing classic components fail; EDG is never
  substituted. Native `ptlink` supports cross-unit instantiation; `python -m decompnet.ido_prelink`
  supplies its control files and links a relocatable N64 object for shared projects.
  Individual app function compilations keep private repositories. Full IRIX executable
  startup/shared-library processing remains outside this ROM toolchain.

Traits
- Unconditional jumps inside functions are `b label` (`beq $zero, $zero`).
- IDO is sensitive to how code is written on a line. Splitting or joining statements
  (`a = b; c = a;` vs `c = a = b;`) changes the output.
- It reuses registers in a predictable order; extra temporaries often *don't* help, while reordering
  statements or changing where a variable is first assigned does.
- Common idioms: `if (x) { } else { }` with empty blocks, `do { ... } while (0);` around a sequence,
  re-reading a global instead of keeping it in a local, `*(&x)`.

Floats
- IDO keeps float constants in .rodata (`lwc1 $f4, %lo(D_...)`) unless they're simple: writing `1.0f`
  vs `1.0` (double) matters.

Argument home slots
- IDO stores `$a0-$a3` to the caller's frame (`sw $a0, 0x18($sp)`) when their address is taken or at
  -O0/-g. Spills like that tell you a parameter is used after a call.

Static functions
- `static` functions may be called with a different convention only in the same file; for matching a
  single function it rarely matters, but keep the name the ROM uses.
