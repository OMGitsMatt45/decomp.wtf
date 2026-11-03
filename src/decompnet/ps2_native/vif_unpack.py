"""Specialize unmasked VIF1 byte and halfword unpacking."""
from pathlib import Path


HELPERS = '''namespace
{
    template <size_t Components, class Component>
    void copyVif1Vectors(uint8_t *memory, const uint8_t *source, uint32_t address,
                         uint32_t count, uint32_t stride)
    {
        constexpr size_t Dest = Components == 1u ? 4u : Components;
        for (uint32_t index = 0; index < count; ++index)
        {
            Component packed[Components];
            uint32_t expanded[Dest];
            std::memcpy(packed, source, sizeof(packed));
            for (size_t lane = 0; lane < Dest; ++lane)
                expanded[lane] = static_cast<uint32_t>(packed[Components == 1u ? 0u : lane]);
            std::memcpy(memory + address*16u, expanded, sizeof(expanded));
            source += sizeof(packed);
            address = (address + stride) & 0x3FFu;
        }
    }

    template <class Component>
    void dispatchVif1Vectors(uint8_t *memory, const uint8_t *source, uint32_t address,
                             uint32_t count, uint32_t stride, uint32_t vn)
    {
        switch (vn)
        {
        case 0u: copyVif1Vectors<1u, Component>(memory, source, address, count, stride); break;
        case 1u: copyVif1Vectors<2u, Component>(memory, source, address, count, stride); break;
        case 2u: copyVif1Vectors<3u, Component>(memory, source, address, count, stride); break;
        case 3u: copyVif1Vectors<4u, Component>(memory, source, address, count, stride); break;
        }
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
                if (!maskEnable && (cl == wl || wl == 1u) && (unpackMode == 0u || unpackMode == 3u) &&
                    (vl == 1u || vl == 2u))
                {
                    const uint32_t stride = cl == wl ? 1u : cl;
                    if (vl == 1u && zeroExtend)
                        dispatchVif1Vectors<uint16_t>(m_vu1Data, srcBase, vuAddr, writeVectorCount, stride, vn);
                    else if (vl == 1u)
                        dispatchVif1Vectors<int16_t>(m_vu1Data, srcBase, vuAddr, writeVectorCount, stride, vn);
                    else if (zeroExtend)
                        dispatchVif1Vectors<uint8_t>(m_vu1Data, srcBase, vuAddr, writeVectorCount, stride, vn);
                    else
                        dispatchVif1Vectors<int8_t>(m_vu1Data, srcBase, vuAddr, writeVectorCount, stride, vn);
                    pos += totalBytes;
                    continue;
                }
''')
    file.write_text(prefix+source)
