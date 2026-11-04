# Switch CPU source development project

This project contains statically translated AArch64 C and runtime sources from
nxport/LASRecomp. It is a single-module CPU probe. It has no Horizon kernel,
graphics, audio, input or save runtime and does not run retail games.

Build with CMake, Clang as the C compiler, and a C++20 host compiler:

```
cmake -S . -B build -DCMAKE_C_COMPILER=clang -DCMAKE_BUILD_TYPE=Release
cmake --build build --parallel
./build/switch_probe assets/image.bin run.json
```

On Windows use a Clang GNU-driver toolchain (GNU C, 128-bit integers and musttail
are required). This initial adapter is execution-qualified on Linux only; a
Windows build is not yet qualified. No Rust or upstream checkout is needed to
build an exported project. Rust is needed by decomp.wtf only during export.

`run.json` contains input identity, registers, a bounded data sample and native
function counts. Missing targets, unsupported instructions/services, or changed
code stop with a failing report. There is no instruction interpreter or runtime
guest-code compilation. The development flags `--tamper-code` and
`--missing-target` exercise those failure reports. An original asset with the
wrong hash is rejected before guest execution. Generated code is editable;
`decomp pc verify .` reports changes against the original export manifest.

Guest pointers use a fixed host mapping. This CPU harness is for trusted local
development programs and is not an isolation boundary for untrusted programs.
Full image text is checked at each translated function entry; self-modifying
code within a function and dynamically loaded modules are not supported.

See `THIRD_PARTY.md`, `sources.json`, and the retained license texts for source
origins. Nothing in this output certifies gameplay or restores original C++.
