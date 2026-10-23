"""Independent ipl3checksum 1.3.1 vectors for every supported CIC family."""

import hashlib
import struct

import pytest

from decompnet.rom.n64_crc import calculate, identify, update


@pytest.mark.parametrize("cic,expected", [
    (6101, (4174269916, 1546506052)), (6102, (4174269916, 1546506052)),
    (6103, (2744411993, 1480661832)), (6105, (3744134198, 4251448369)),
    (6106, (68161438, 2964711484)),
])
def test_crc_matches_independent_reference(cic, expected):
    # Generated original bytes; expected values were obtained using
    # Decompollaborate/ipl3checksum's released 1.3.1 Rust implementation.
    image = bytes((i * 13 + (i >> 8) * 7) & 255 for i in range(0x200000))
    assert hashlib.sha256(image).hexdigest() == "4766e938affa3f45c02bfc1d178361a4439fa9657c2f49f1a7120bdedd6a18cd"
    assert calculate(image, cic) == expected
    rebuilt = update(image, cic)
    assert struct.unpack_from(">2I", rebuilt, 0x10) == expected
    assert rebuilt[:0x10] == image[:0x10] and rebuilt[0x18:] == image[0x18:]
    assert identify(rebuilt) == (6102 if cic == 6101 else cic)


def test_unknown_and_short_cartridges_need_review():
    with pytest.raises(ValueError, match="unverified"):
        identify(bytes(0x200000))
    with pytest.raises(ValueError, match="full 1 MiB"):
        calculate(bytes(0x1000), 6102)
    with pytest.raises(ValueError, match="full 1 MiB"):
        identify(bytes(16))
