# Original PlayStation source-project fixture

A tiny matching project for decomp.wtf's source-project and collaboration tests.
It uses the original CC0 game sources with the pinned PS1 GCC compiler.

1. Build `projects/demo-psx/build.py` and provide its `DEMOQ_PS1.EXE` as `baserom.exe`.
2. `python configure.py` checks its identity, creates `build/expected/` objects and
   writes `build.ninja` and `objdiff.json`.
3. `ninja` builds the partial source in `src/`; objdiff measures function matches.

The tests set the expected input hash for their freshly built fixture. Reference
objects are compiled from `tools/reference/` rather than extracted from retail
media. Some functions match, one is wrong and the rest await source.
This fixture qualifies source-project tools; it is not a native PC game backend.
