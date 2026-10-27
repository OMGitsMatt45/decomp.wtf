"""Original VIF uploads and raw vector-program byte discovery."""
import struct

from decompnet.ps2_native.vu_discovery import Catalog,mpg,raw


def pairs(count=4):
    return b''.join(struct.pack('<II',0x8000033c,0x2ff|(0x40000000 if n==count-2 else 0)) for n in range(count))


def upload(count=4,destination=0):
    return struct.pack('<I',0x4a000000|((count&255)<<16)|destination)+pairs(count)


def test_complete_mpg_uploads_and_raw_end_delay_pairs():
    data=upload();records=list(mpg(data))
    assert len(records)==1 and len(records[0]['words'])==4 and records[0]['offset']==0
    assert len(list(raw(pairs())))==1
    assert not list(raw(pairs()[:-8]))
    assert not list(raw(bytes(128)))
    assert not list(mpg(data[:-1]))
    assert not list(mpg(upload(destination=2048)))
    bad=bytearray(data);struct.pack_into('<I',bad,8,0x060002ff)
    assert not list(mpg(bad))
    # A zero NUM is 256 pairs, not an empty upload.
    assert len(list(mpg(upload(256)))[0]['words'])==256
    assert not list(mpg(struct.pack('<I',0x4a000000)+pairs()))


def test_streaming_upload_scan_handles_chunk_boundaries_and_deduplicates():
    data=b'\xff'*4092+upload(256)+b'\xff'*8192
    catalog=Catalog();catalog.scan_stream('original.bin',lambda start,size:data[start:start+size],len(data),chunk=4096)
    assert len(catalog.records)==1 and catalog.records[0]['offset']==4092
    assert len(catalog.words)==2
    catalog.scan('original.bin',data)
    assert len(catalog.records)==1
