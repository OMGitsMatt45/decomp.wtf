# Original RTC fixture

CC0-1.0. ARM9 remains idle; ARM7 bit-bangs the RTC date/time read command
through GPIO at 0x04000138, then stores all seven returned bytes as words in
shared RAM. No SDK, BIOS or retail game code is included.

Regenerate the committed bytes with GNU Arm tools:
`python -m tools.make_nds_static_fixture --fixture nds-rtc`.
Tests use the committed bytes and need no Arm assembler.
