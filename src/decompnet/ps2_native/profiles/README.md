# Optional PS2 code maps

These are data profiles for the shared PS2 exporter. They contain addresses,
function names, code/data boundaries, hashes and explicit SDK bindings. They
contain no original instructions, assets, BIOS or generated retail C++.
Selection requires the complete owner input SHA-256; other revisions require a
separate reviewed profile. The runtime/core contains no title address hooks.

`dqviii-usa.json.gz` derives from the GPL-3.0 analysis maps in
[DQ8-Recompiled](https://github.com/Sinan-Karakaya/DQ8-Recompiled/tree/f6dfd968001b492415969bb70bd5aad3bfa79abd/config/SLUS_212.07).
The profile retains the original ELF entry, excludes embedded vector/data bytes
while preserving late EE initializers, and marks all 237 SDK bindings explicitly.
It contains 10,881 resident entries and 1,539 entries across six MWo3 modules.
Constructor code after a module's primary text is explicitly typed; intermediate
mutable data remains data. The complete original input hash is in index.json.
The profile is GPL-3.0; see GPL-3.0.txt. The application integration remains MIT.

To inspect the full JSON without any game input:

```sh
python -c "import gzip; print(gzip.open('dqviii-usa.json.gz','rt').read())"
```

A map qualifies translation structure, not gameplay. Retail boot, I/O, rendering,
audio and save evidence must be reported separately, including any remaining
unsupported services. Full playthrough acceptance belongs to the owner.
