# N64 C++ implementation

`n64.cpp` implements ROM normalization, header validation, compiler heuristics,
code-segment placement, Yaz0 and compressed-code discovery in C++17. Python keeps
the application API, text decoding, SHA-1, and orchestration. Rabbitizer supplies
generic instruction validation; Python's zlib supplies generic raw deflate through
a callback. The N64 analysis algorithms have no Python runtime fallback.

The app ships an x86-64 Windows DLL and Linux shared library; users need no C++
compiler. Windows links its C++ runtime statically. The Linux release library uses
GCC 10 / glibc 2.31 build headers and requires glibc 2.18 or newer. Source builds:

```sh
python tools/build_n64_native.py
python -m pytest tests/test_n64_native.py tests/test_n64code.py tests/test_overlays.py
```

The `--cxx` and `--sysroot` options select a release compiler and compatibility
sysroot. CI builds the source on Windows and Linux and checks the isolated Windows
installation loads the DLL. The C ABI owns result buffers until `n64_free`;
exceptions become an error string at the boundary. The old Python implementations
are test fixtures used for differential validation.

The separate Windows KMC GCC/binutils suite is a GNU C++98 source port of the
period compiler, retaining its target algorithms and both C and period C++ frontends. Its 195 project
translation units, corresponding GPL source, build inventory and recipe accompany
the compiler archive. See `tools/windows/build_kmc_cpp.py` and
`tools/windows/port_kmc_cpp.py`. Build-time configuration and generators use C;
every shipped project runtime object is built from C++. System MinGW runtime
libraries retain their upstream implementation languages. N64 KMC and IDO 5.3/7.1 game output default
to C++ through their original frontends. IDO uses each version's SGI/EDG frontend and unchanged
backend; the classic 5.3 cfront driver remains unsupported. See [IDO C++ support](../../docs/ido-cpp.md).
