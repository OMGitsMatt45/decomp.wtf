"""Reuse storage after a graphics DMA snapshot has been consumed."""
from pathlib import Path

from .runtime_patch import replace


def patch(root, *, retain_large_vif1=False):
    source = Path(root)/'thirdparty/PS2Recomp/ps2xRuntime/src/lib/ps2_memory.cpp'
    replace(source, '''namespace
{
    inline void inRange''', '''namespace
{
    // The graphics DMA parser still copies all guest data before submission.
    // Keep one consumed allocation per submitting thread and DMA channel.
    using DmaChain = std::vector<uint8_t>;
    constexpr size_t kRetainedChainCapacity = 1024u * 1024u;
    constexpr size_t retainedChainCapacity(uint32_t channel)
    {
        return channel == 0x10009000u ? kRetainedChainCapacity * VIF1_CAPACITY_FACTOR : kRetainedChainCapacity;
    }

    DmaChain &dmaChainScratch(uint32_t channel)
    {
        thread_local std::array<DmaChain, 3> chains;
        return chains[(channel - 0x10008000u) >> 12u];
    }

    template<typename Transfers>
    void recycleDmaChains(Transfers &transfers, uint32_t channel)
    {
        if (transfers.empty())
            return;
        DmaChain &scratch = dmaChainScratch(channel);
        for (auto &transfer : transfers)
        {
            auto &chain = transfer.chainData;
            if (chain.capacity() > scratch.capacity() && chain.capacity() <= retainedChainCapacity(channel))
            {
                chain.clear();
                scratch.swap(chain);
            }
        }
    }

    inline void inRange'''.replace('VIF1_CAPACITY_FACTOR','8u' if retain_large_vif1 else '1u'))
    replace(source, '''                    std::vector<uint8_t> chainBuf;

                    auto appendData''', '''                    std::vector<uint8_t> chainBuf;
                    chainBuf.swap(dmaChainScratch(channelBase));

                    auto appendData''')
    replace(source, '''                    // else if (channelBase == 0x10009000u)
                    // {

                    // }''', '''                    else if (chainBuf.capacity() <= retainedChainCapacity(channelBase))
                    {
                        dmaChainScratch(channelBase).swap(chainBuf);
                    }''')
    for name, address in [('Gif', 'A'), ('Vif0', '8'), ('Vif1', '9')]:
        clear = f'    m_pending{name}Transfers.clear();'
        replace(source, clear, f'    recycleDmaChains(m_pending{name}Transfers, 0x1000{address}000u);\n'+clear)
