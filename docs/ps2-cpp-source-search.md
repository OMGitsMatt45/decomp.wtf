# EE-GCC 2.96 source / Windows acquisition investigation

Target: **Sony/Cygnus `2.96-ee-001003-1`**, including its C++ frontend and EE
backend. This investigation has not acquired verified corresponding source or
an authentic native Windows build. The existing Linux implementation remains
supported; native Windows availability is unchanged.

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

## New archive lead: contents not yet verified

The preserved [PS2 SDK collection file listing](https://archive.org/download/ps2_sdks/)
lists **[`ee001003_1.tgz`](https://archive.org/download/ps2_sdks/ee001003_1.tgz)**
at 36.0 MB. It also lists a `SCE Tool-Libs 2.4.2 - DTL-S2324_broken.zip`
collection. These are acquisition leads, not confirmed source distributions.
The filename alone cannot establish their contents or compatibility.

The current research workspace's outbound allowlist denies Archive.org downloads
with HTTP 403 at the proxy. Consequently the `.tgz` has not been downloaded,
hashed, listed or classified. Public web indexing exposes the collection listing
but has not exposed this archive's members. Access to `archive.org` and its
normal download subdomains is needed to inspect it, or the relevant source
bundle can be supplied from an existing copy. No access restriction was bypassed.

On acquisition, inspect the archive without executing its files. Look for the
source archive, matching Sony patches and configuration script. Check the actual
GCC version and target changes, including the C++ frontend. A genuine Windows
candidate must be a PE executable whose own identity is correct; its generated
instructions, relocations and data must then agree with the pinned Linux
compiler. Finally run the PS2 C++ matching and clean export suite on native
Windows and Linux. Until those checks pass, no new compatibility is claimed.
