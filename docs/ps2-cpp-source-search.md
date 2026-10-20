# EE-GCC 2.96 source / Windows acquisition investigation

Target: **Sony/Cygnus `2.96-ee-001003-1`**, including its C++ frontend and EE
backend. This investigation has not acquired verified corresponding source or
an authentic native Windows build. The existing Linux implementation remains
supported; native Windows availability is unchanged.

The follow-up [source reconstruction experiment](ps2-cpp-reconstruction.md)
now provides pinned preparation/build recipes and original-compiler comparison
records. Both host frontend builds completed, but the C++ probes failed; the
missing exact source has not been reconstructed successfully.

## A mislabeled Windows candidate was ruled out

The [SDK 2.4 snapshot at `5c8bdf31`](https://github.com/AngheloAlf/sce_ps2_sdk_24/tree/5c8bdf31f6bdd82ba4456413594198b5bd469f43/local/sce/ee/gcc/lib/gcc-lib/ee/2.96-ee-001003-1)
contains both Linux programs and Windows `.exe` files in a directory named
`2.96-ee-001003-1`. The directory name is misleading for the Windows files:
both compiler frontends identify as **SN GCC 2.95.3 v1.07**. Direct SHA-256
comparison also establishes that all three files below are byte-identical to
`ee-gcc2.95.3-107/lib/gcc-lib/ee/2.95.3/` in decomp.me's
[`ps2_compilers.tar.xz`](https://github.com/decompme/compilers/releases/download/compilers/ps2_compilers.tar.xz)
(SHA-256 `f337a65a4fbab5cf0e335efe266dcbc7cf69b19c665c6b3a8924736df151a02a`).

| File under the SDK's 2.96 directory | SHA-256 | Actual identity |
| :-- | :-- | :-- |
| `cc1.exe` | `e626c1fc04d0cad6835fc3478237365e5e46563d341d6d263632b07b582c9bf2` | SN 2.95.3-107 C frontend |
| `cc1plus.exe` | `e57ad9e28fc6abd97bb099cfad4f5294ad8b6c916f54f8df1e562a8f36e84220` | SN 2.95.3-107 C++ frontend |
| `cpp.exe` | `2db8234d5a1a13e9bf119449ebf0c6ad69f04ab03baf6bacb9e7b3b292a42e96` | SN 2.95.3-107 preprocessor |

These executables must not be registered as EE-GCC 2.96 or used as its fallback.
A versioned folder, executable extension or SDK release label does not establish
compiler identity.

## More specific source acquisition targets

The same snapshot's [EE 2.96 build instructions](https://github.com/AngheloAlf/sce_ps2_sdk_24/blob/5c8bdf31f6bdd82ba4456413594198b5bd469f43/local/sce/1st_read/bldgcc.txt)
identify these inputs relative to the original `sce/ee/gcc` directory:

- `src/src.tar.gz`: the source bundle;
- `sce-patch`: the accompanying Sony patch;
- `config.sh`: the build configuration script.

The inspected snapshot does not contain these source/build inputs, and querying
its source-directory commit history found no recoverable source archive. The
instructions establish historical filenames, not possession of the source or
proof that a different archive matches this compiler.

GirianSeed and aap's published EE-GCC branches/releases contain 2.9-era source;
ps2dev's public EE branches contain later homebrew GCC versions. They do not
provide a verified replacement for the target source. The current decomp.me
2.96 package supplies the Linux binary tools already used by decomp.wtf.

## Uploaded archive inspected: patch recovered, base source absent

The preserved [PS2 SDK collection file listing](https://archive.org/download/ps2_sdks/)
lists **[`ee001003_1.tgz`](https://archive.org/download/ps2_sdks/ee001003_1.tgz)**
at 36.0 MB. The user supplied a smaller recompression, **`ee001003_1.7z`**,
which was successfully downloaded and inspected. Its identity is:

- Size: **12,873,050 bytes**.
- SHA-256: `858912fc80f4c2d993f693fbc72afec273372f5a2547aeff9e96196e416d7a72`.
- 2,417 members: 2,347 regular files and 70 directories; 140,200,481
  uncompressed bytes, under `ee001003_1/`.

Every regular member was read and hashed with libarchive. File headers identify
52 host executables as Linux i386 ELF32 and eight target objects as MIPS ELF32;
no regular member has a Windows MZ/PE executable header. The original `.tgz`
was not independently downloaded or hashed, so these facts apply specifically
to the supplied `.7z`. Archive documentation was treated as evidence; its setup
scripts and commands were not executed.

The upload recovers **`sce/ee/gcc/sce-patch`** (170,044 bytes) and
**`sce/ee/gcc/config.sh`** (134 bytes). However, **`sce/ee/gcc/src/` is empty**:
there is no `src/src.tar.gz`, unpacked compiler source, or C++ frontend source.
The build document `sce/1st_read/bldgcc_e.txt` specifically requires that missing
archive before applying the patch. Installed headers and library template
implementation files are not compiler source.

The driver and both frontends are byte-identical to the pinned decomp.me Linux
compiler:

| Path relative to `sce/ee/gcc` | SHA-256 |
| :-- | :-- |
| `bin/ee-gcc` | `b8c284d16c9c0a0e8788e9522c46881e224ad01fa1c732aed43f821cc32f168b` |
| `lib/gcc-lib/ee/2.96-ee-001003-1/cc1` | `59ec92b3f9f3513e0633331af304733e3094de30884e662a8cb584a51c1c42b5` |
| `lib/gcc-lib/ee/2.96-ee-001003-1/cc1plus` | `560e6f276134d109e2b4c05ee9c72d4f9215ffc86d784eb4491a3dadf316bf9a` |

### Why the recovered patch does not complete a Windows source port

This is an incremental patch to **already EE-patched GNUPro source**. Its
`gcc/version.c` hunk changes `2.96-ee-001003` to `2.96-ee-001003-1`; it is not
a patch from stock GNU GCC to the EE compiler. It changes 44 files, including
13 GCC files, and assumes existing R5900 target support. For example, its
`gcc/config/mips/mips.c` change is a single hunk around line 9675. It does not
provide the complete backend, configuration or C++ frontend.

As a concrete alternative check, the GCC portion was dry-run against the
available [2.9 source at `b595ded6`](https://github.com/SSXModding/ps2-ee-toolchain/tree/b595ded606227e93b8c4a447446c1d2ac093827d/ee/gcc)
using `patch --dry-run --batch --forward --fuzz=0 -p3`. It failed: 15 hunks
failed and three were ignored because `cpplex.c` and `config/float-r5900.h`
are missing. The version and MIPS backend hunks fail as well. Some common
runtime changes apply, but that does not establish a matching compiler tree.
The source checkout was not modified.

The uploaded `cc1plus` was also invoked explicitly under QEMU i386 on Linux
with the existing PS2 C++ fixture and original driver/assembler. All seven
functions' code and relocations agree with `tests/fixtures/ps2_cpp_parity.json`,
including templates, references and overloads. This is a supplemental identity
check under emulation, **not native Windows or native Linux validation** and
not an exported-project rebuild. The prior native Linux CI evidence remains
documented in [PS2 C++ support](ps2-cpp.md#verification).

The compact [upload audit record](ps2-cpp-upload-audit.json) preserves hashes,
patch targets, configuration, dry-run results and compilation probe results.
It contains no SDK binaries or patch payload.

### Exact remaining acquisition target

Obtain **`sce/ee/gcc/src/src.tar.gz` corresponding to this release**, or its
unpacked GNUPro EE `2.96-ee-001003` base tree, to use with the recovered patch
and configuration. The patch SHA-256 is
`1fba1eae60d1625d9cab841267766bccea54ee0080f6257294798e51a85b4735`;
the configuration SHA-256 is
`ac76c7386224262c3c84bb7d09ba69e0a38da44bc6399922519bc7416ee01511`.
The separately listed `SCE Tool-Libs 2.4.2 - DTL-S2324_broken.zip` remains
an unverified lead; its member listing could not be retrieved. No matching
base source was acquired in the follow-up search.

An authentic native Windows build of this exact frontend/backend is the other
accepted input. A candidate must be a PE executable with the correct identity,
then pass instruction, relocation and data parity against the pinned Linux
compiler, followed by strict matching and clean exported-project rebuilds on
native Windows and Linux. The recovered patch/configuration narrow the missing
input, but **native Windows support remains blocked and is not advertised**.
