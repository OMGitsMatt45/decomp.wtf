# Period compilers in a Linux cloud

When a cloud kernel lacks 32-bit x86 execution, the original Linux KMC, PS1
and PS2 compilers fail with `Exec format error`. Docker shares that kernel, so
changing containers alone does not fix it. An explicit QEMU user-mode runner
can execute the original programs, including their compiler child processes.

If bubblewrap cannot create user namespaces, select the supported Docker
compiler sandbox. These settings apply to Linux projects that use the default
`auto` sandbox; an explicit project sandbox takes precedence:

```sh
export DECOMP_COMPILER_SANDBOX=docker
export DECOMP_COMPILER_IMAGE=debian:trixie-slim@sha256:62bd423aeee912639ca8ee681c2b762cb3e25137e0a92b20be455898a9f034ad
export DECOMP_QEMU_I386=/absolute/path/to/qemu-i386-static
decomp
```

Use a static Linux x86-64 QEMU executable so it needs no additional libraries
inside the container. Ubuntu 24.04 supplies `/usr/bin/qemu-i386-static` in
`qemu-user-static`; Debian 13 supplies static executables in `qemu-user`.
Install/extract it using the environment's supported package workflow. The
cloud validation used Debian QEMU 10.0.13, package SHA256
`ca6ede739327a20ae5a3498230c8a3a9a072c586e131bc6bcc1201eb1725e336`.
The caller needs access to the supported Docker daemon. Toolchain installation
still uses the environment's configured HTTPS proxy and destination policy.

The registered toolchains and required runtimes must be installed normally.
The Linux `runtime-i386` entry now uses a pinned Debian 13 glibc package; an
existing installation of its previous package needs reinstalling:

```sh
decompnet toolchain install runtime-i386 --force
```

For a single registered-toolchain project, the equivalent settings are
`compiler.sandbox = "docker"`, `compiler.image = "…"` and
`compiler.qemu_i386 = "/absolute/path/to/qemu-i386-static"` in `project.toml`.
Set `compiler.qemu_i386 = ""` to opt that project out of the environment default.
Native Windows selection does not read these Linux environment defaults.

Each compile creates a temporary mirror of any pinned toolchain containing
i386 executables. Its launchers run the unchanged originals through QEMU and
give GCC launchers for its child phases. Native executables remain native.
The original trees, emulator and temporary mirror are mounted read-only;
only the compile work directory and container temporary directory are writable.
The Docker process retains its network prohibition, memory/process limits,
dropped capabilities and `no-new-privileges` setting. No host binfmt registration
or privileged container is required.

## Validation

The five Docker/QEMU reference cases compare machine code and relocations for
39 function outputs: KMC C and C++, PS1 GCC 2.7.2 and 2.8.1 C++, and EE-GCC 2.96
C++. Each also rejects invalid source and verifies the original toolchain files
remain unchanged. Run them with the settings above:

```sh
DECOMP_TEST_LINUX_I386=1 python -m pytest -q tests/test_linux_i386_real.py
```

The operational workflow runs these cases separately on Linux after its native
compiler suite. IDO 5.3's native SGI/EDG and classic cfront C++ frontends also
matched their eight-function reference snapshots inside the Docker sandbox in
the cloud check; they do not need i386 emulation.

The running app compiled and scored candidates against the supplied N64 and
PS1 images. For the PS2 image, a deliberately changed constant failed matching,
then the correct C++ function matched byte-for-byte, propagated to its two
identical overlays, and exported without assembly fallback. All seven supplied
inputs again rebuilt identically in the scopes recorded in
[rom-input-validation.md](rom-input-validation.md).

This does not establish GBA compiler execution in this cloud: its pinned Arm
toolchain download still needs the environment's destination rules applied.
Unmatched functions remain assembly in exports. Console/emulator bootability
has not been tested. Destination-policy denials require the supported environment
configuration workflow.
