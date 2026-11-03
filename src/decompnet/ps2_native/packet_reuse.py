"""Retain bounded GIF packet storage and amortize GS queue growth."""
from pathlib import Path
from .runtime_patch import replace

def patch(root):
    folder=Path(root)/'thirdparty/PS2Recomp/ps2xRuntime/src/lib/gs'
    gif=folder/'ps2_gif_arbiter.cpp'
    replace(gif,'#include <cstring>\n','''#include <cstring>

namespace {
constexpr size_t kRetainedPacketBytes = 64u * 1024u;
// A packet still owns its snapshot while queued. Only drained storage is
// reusable, with one bounded buffer per submitting thread.
std::vector<uint8_t> &packetBuffer() {
    static thread_local std::vector<uint8_t> buffer;
    return buffer;
}
}
''')
    replace(gif,'''    pkt.data.resize(sizeBytes);
    std::memcpy(pkt.data.data(), data, sizeBytes);''','''    auto &buffer = packetBuffer();
    if (buffer.capacity() >= sizeBytes)
        pkt.data.swap(buffer);
    pkt.data.assign(data, data + sizeBytes);''')
    replace(gif,'''    if (!m_processFn)
        return;

    std::stable_sort''','''    if (!m_processFn || m_queue.empty())
        return;

    if (m_queue.size() > 1u)
        std::stable_sort''')
    replace(gif,'    m_queue.clear();','''    auto &buffer = packetBuffer();
    for (auto &pkt : m_queue) {
        if (pkt.data.capacity() <= kRetainedPacketBytes && pkt.data.capacity() > buffer.capacity()) {
            pkt.data.clear();
            pkt.data.swap(buffer);
        }
    }
    m_queue.clear();''')
    worker=folder/'gs_threaded_backend.cpp'
    replace(worker,'#include <exception>\n','#include <exception>\n#include <iterator>\n')
    for indent in ('        ','            '):
        old='\n'+indent+'pending.reserve(pending.size() + staged.size());\n'+indent+'for (auto &command : staged)\n'+indent+'    pending.push_back(std::move(command));'
        new='\n'+indent+'// Range insertion grows capacity geometrically rather than\n'+indent+'// reallocating and copying the backlog for each staged batch.\n'+indent+'pending.insert(pending.end(), std::make_move_iterator(staged.begin()),\n'+indent+'               std::make_move_iterator(staged.end()));'
        replace(worker,old,new)
