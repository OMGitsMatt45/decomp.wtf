"""DS Protect bootstrap signatures; a hit is evidence, not verified decryption.

Signature data from ds-rom 0.8.0 (MIT, copyright 2025 Aetias), which credits
Mow/taxicat1's dsprot and dsdetect. License: licenses/ds-rom.txt.
https://github.com/AetiasHax/ds-rom/blob/v0.8.0/src/crypto/dsprot.rs

MIT License

Copyright (c) 2025 Aetias

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.

"""

import struct

SIGNATURES = {
    '1.00': struct.pack("<6I", 0xe3527270, 0xbafe77fc, 0xe59e0989, 0xe1c2f9af, 0xea018a51, 0xeb004ae2),
    '1.05': struct.pack("<6I", 0xbafe0f18, 0xe59caf7a, 0xe2861884, 0xe1c5da54, 0xea018a6b, 0xeb0070c2),
    '1.06': struct.pack("<6I", 0xbafe9b10, 0xe59cfa77, 0xe2862a71, 0xe1c54e3d, 0xea01879d, 0xeb005fdf),
    '1.08': struct.pack("<6I", 0xbafe4040, 0xe59c2300, 0xe2852226, 0xe1c5cbe8, 0xea01612f, 0xeb004979),
    '1.10': struct.pack("<6I", 0xbafe29a2, 0xe59cc95b, 0xe285d70a, 0xe1c5442c, 0xea01fd7e, 0xeb001cfc),
    '1.20': struct.pack("<6I", 0xe3580f00, 0xbafe7df8, 0xe284dff9, 0xe1c2059d, 0xea014de4, 0xeb002f0c),
    '1.22': struct.pack("<6I", 0xe3581567, 0xbafee339, 0xe284dad2, 0xe1c27622, 0xea017231, 0xeb0037ee),
    '1.23': struct.pack("<6I", 0xebaa0113, 0xe4064ec7, 0xef013596, 0xe5212f83, 0xe7ee335b, 0xe83b197c),
    '1.23z': struct.pack("<6I", 0xebaa0114, 0x40064eb7, 0x5f013696, 0xe5211f83, 0xe7ef335b, 0xe84b197c),
    '1.25': struct.pack("<6I", 0xebb6df66, 0xe42f6211, 0xef56b5aa, 0xe5b903fd, 0xe7d29154, 0xe859697c),
    '1.26': struct.pack("<6I", 0xeb8fbc31, 0xe4ec10cf, 0xef73e592, 0xe59a0b7e, 0xe78cb309, 0xe87f3ed1),
    '1.27': struct.pack("<6I", 0xe8dffe17, 0xe43df0de, 0x2ae8335c, 0x0ac09826, 0xe7a838dc, 0xe891a6fc),
    '1.28': struct.pack("<6I", 0xe2ed720b, 0xef69d1b1, 0x2ec32a41, 0x1aa3e665, 0xe9e1c153, 0xe49e8d9c),
    '2.00': struct.pack("<6I", 0x0819ff33, 0xe4a1ef1c, 0x5a85a2b3, 0xea0d2a0f, 0xe0d6bd78, 0xe29d9377),
    '2.00 Instant': struct.pack("<6I", 0x0849ea8b, 0xe33b6243, 0x53b2d501, 0xe6847168, 0xebd886d7, 0xee3c09c0),
    '2.01': struct.pack("<6I", 0x08d5310e, 0xe41bdb46, 0x5a3d9627, 0xeaf8fc79, 0xe016c9e7, 0xe2eb8130),
    '2.01 Instant': struct.pack("<6I", 0x08637dd1, 0xe3618cb3, 0x5356f520, 0xe6b110ca, 0xeb4c1e5c, 0xeed91028),
    '2.03': struct.pack("<6I", 0x08b76046, 0xe4177f2f, 0x5ab21c99, 0xea2af4b1, 0xe0fe885a, 0xe202fc9e),
    '2.03 Instant': struct.pack("<6I", 0x08b76046, 0xe4177f2f, 0x5ab21c99, 0xea2af4b1, 0xe0fe885a, 0xe2029efc),
    '2.05': struct.pack("<6I", 0x08a27510, 0xe47ab3c3, 0x5a289302, 0xeaa6cac8, 0xe00d75d5, 0xe2d2fe01),
    '2.05 Instant': struct.pack("<6I", 0x08a27510, 0xe47ab3c3, 0x5a289302, 0xeaa6cac8, 0xe00d75d5, 0xe2d2fe00),
}


def detect(code: bytes, address: int = 0) -> list[dict]:
    """Report every word-aligned signature occurrence in an already decoded module."""
    found = []
    for version, signature in SIGNATURES.items():
        at = code.find(signature)
        while at >= 0:
            if (address + at) % 4 == 0:
                found.append({"version": version, "offset": at, "address": address + at})
            at = code.find(signature, at + 1)
    return sorted(found, key=lambda item: (item["offset"], item["version"]))
