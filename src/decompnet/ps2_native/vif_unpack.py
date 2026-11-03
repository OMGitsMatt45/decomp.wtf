"""Specialize contiguous, unmasked V2/V3 byte and halfword unpacking."""
from pathlib import Path


HELPERS = '''namespace
{
    // V2 and V3 update only their defined lanes in the normal unmasked path.
    // Load each packed vector before the writes and preserve the other lanes.
    template <size_t Components, class Component>
    void copyPartialVif1(uint8_t *memory, const uint8_t *source, uint32_t address, uint32_t count)
    {
        static_assert(Components == 2u || Components == 3u);
        for (uint32_t index = 0; index < count; ++index)
        {
            Component packed[Components];
            uint32_t expanded[Components];
            std::memcpy(packed, source, sizeof(packed));
            for (size_t lane = 0; lane < Components; ++lane)
                expanded[lane] = static_cast<uint32_t>(packed[lane]);
            std::memcpy(memory + address*16u, expanded, sizeof(expanded));
            source += sizeof(packed);
            address = (address + 1u) & 0x3FFu;
        }
    }

    template <size_t Components, class Signed, class Unsigned>
    void copyPartialVif1Width(uint8_t *memory, const uint8_t *source, uint32_t address, uint32_t count, bool zeroExtend)
    {
        if (zeroExtend)
            copyPartialVif1<Components, Unsigned>(memory, source, address, count);
        else
            copyPartialVif1<Components, Signed>(memory, source, address, count);
    }
}

'''


def patch(root):
    file = Path(root)/'thirdparty/PS2Recomp/ps2xRuntime/src/lib/ps2_vif1_interpreter.cpp'
    source = file.read_text()
    anchor = 'enum VIFCmd : uint8_t'
    if source.count(anchor) != 1:
        raise RuntimeError('Pinned VIF1 source changed')
    source = source.replace(anchor, HELPERS+anchor)
    first = source.index('void PS2Memory::processVIF1Data(')
    prefix, source = source[:first], source[first:]
    anchor = '''            if (m_vu1Data && totalBytes > 0 && pos + totalBytes <= sizeBytes)
            {
                const uint8_t *srcBase = data + pos;
'''
    if source.count(anchor) != 1:
        raise RuntimeError('Pinned VIF1 partial write loop changed')
    source = source.replace(anchor, '''            if (m_vu1Data && totalBytes > 0 && pos <= sizeBytes && totalBytes <= sizeBytes - pos)
            {
                const uint8_t *srcBase = data + pos;
                const uint32_t unpackMode = vif1_regs.mode & 3u;
                if (!maskEnable && cl == wl && (unpackMode == 0u || unpackMode == 3u) &&
                    (vn == 1u || vn == 2u) && (vl == 1u || vl == 2u))
                {
                    if (vn == 1u && vl == 1u)
                        copyPartialVif1Width<2u, int16_t, uint16_t>(m_vu1Data, srcBase, vuAddr, writeVectorCount, zeroExtend);
                    else if (vn == 1u)
                        copyPartialVif1Width<2u, int8_t, uint8_t>(m_vu1Data, srcBase, vuAddr, writeVectorCount, zeroExtend);
                    else if (vl == 1u)
                        copyPartialVif1Width<3u, int16_t, uint16_t>(m_vu1Data, srcBase, vuAddr, writeVectorCount, zeroExtend);
                    else
                        copyPartialVif1Width<3u, int8_t, uint8_t>(m_vu1Data, srcBase, vuAddr, writeVectorCount, zeroExtend);
                    pos += totalBytes;
                    continue;
                }
''')
    file.write_text(prefix+source)
