# Working in a source project

Follow the project's source tree, headers, build system and conventions. Its
pinned compiler builds each file and objdiff compares the result with the original
object. Use the configured language and flags.

1. Claim a function and read its assembly, current diff, source file and notes.
2. Read surrounding source and headers with `read_file` and `search_code`. Reuse
   existing struct definitions, declarations, macros and helpers.
3. Submit one complete definition with `compile_and_diff`. It replaces the
   function or assembly placeholder. Failed edits are rolled back.
4. For shared types, globals and helpers, use `edit_file`. Existing matches are
   checked again and changes that break them are rolled back.
5. Use `file_status` to inspect remaining function/data differences and link
   errors. Match source order, data placement, literal pooling and definitions.

Generated DS projects track ARM9, ARM7 and overlays separately. Preserve each
unit's processor, address mode and ownership. `configure_arm7_unit` assigns
reviewed initialized-data/BSS ranges or selects C/C++ without changing code bounds.
The full ROM check and existing matches must still pass.

Read the project's AGENTS.md or CONTRIBUTING.md when present. Keep its naming,
types and source conventions. Do not edit targets, original binaries, generated
assembly or build configuration to make a match pass. Submit plausible C/C++
without inline assembly, assembly functions or assembly includes.

Console matching and linked-source reconstruction are separate from native PC
output. A PC project needs its own adapter, runtime, host build and execution
qualification. Completing console matches does not establish those results.
