# Switch module/service development project

This source project links extracted ExeFS NSO modules ahead of time and executes
generated AArch64 C on a bounded source runtime. It has no graphics, audio, save
system, guest thread creation or retail startup qualification.

```
cmake -S . -B build -DCMAKE_C_COMPILER=clang -DCMAKE_BUILD_TYPE=Release
cmake --build build --parallel
./build/switch_runtime assets run.json
```

Clang's GNU C driver (`__int128`/`musttail`) and a C++20 compiler are required.
Linux x86-64 is tested. Windows remains unqualified. Rust and donor checkouts are
not required to build this exported project. The C, runtime and CMake files are
editable; the export manifest records their original hashes.

The host resolves MOD0 symbols, RELA/RELR imports and weak references, registers
all native function tables, runs dependency-ordered initializers and enters
`main` with a main-thread handle and TLS. `rtld` can be loaded for symbols but is
not run as a second guest linker. This host-linked startup does not qualify the
complete Nintendo SDK process-startup ABI. `analysis.json` records module bases,
input hashes, import bindings, entry points and constructor order.

The single-thread service boundary supports bounded heap growth (up to 4 MiB),
thread identity, a monotonic 19.2 MHz tick, debug output, process/thread exit,
handles, and a strict HIPC/CMIF subset. `sm:` can initialize and open `set`;
`set:GetLanguageCode` returns the explicit development locale `en-US`. HIPC
control `QueryPointerBufferSize` reports zero; buffer descriptors, domains,
other services and other commands are unsupported. Invalid handles return their
Horizon error. Unsupported calls, malformed messages and invalid service
pointers stop with an execution report.

`run.json` identifies the input set, constructor/native counts, SVC/IPC counts,
registers, bounded module-data samples and failures. There is no instruction
interpreter or runtime guest-code compiler. `--tamper-code` changes the last
module before running to exercise its function-entry code guard;
`--missing-target` exercises the native miss report after initialization.

All assets are verified before guest execution. Fixed guest-address mappings and
direct generated memory accesses make this a trusted local development harness,
not an isolation boundary. Dynamically loaded code and self-modification within
one function are unsupported. See `THIRD_PARTY.md` and retained license notices.
