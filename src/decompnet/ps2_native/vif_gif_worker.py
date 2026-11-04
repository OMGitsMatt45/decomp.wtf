"""Install the opt-in, strictly ordered VIF1 GIF frontend worker."""

from pathlib import Path
import re

from .runtime_patch import replace


HEADER = "runtime/gs/decomp_vif_gif_worker.hpp"
NS = "decomp_ps2::vif_gif"


def include(path, anchor):
    replace(path, anchor, f'{anchor}\n#include "{HEADER}"')


def patch_arbiter(headers, sources):
    header = headers / "gs/ps2_gif_arbiter.h"
    replace(header, "#include <functional>", "#include <functional>\n#include <mutex>")
    replace(header, "enum class GifPathId", "class GS;\n\nenum class GifPathId")
    replace(header, "    void submit(GifPathId", """    void bindRuntimeGs(GS &gs);
    std::mutex *vifGifWorkerBoundary() const;
    bool tryQueueVifGif(const uint8_t *data, uint32_t sizeBytes);

    void submit(GifPathId""")
    replace(header, "    ProcessPacketFn m_processFn;", """    struct RuntimeGsSink
    {
        GS *gs;
        void operator()(const uint8_t *data, uint32_t size) const;
    };
    ProcessPacketFn m_processFn;""")

    source = sources / "gs/ps2_gif_arbiter.cpp"
    replace(source, '#include "runtime/gs/ps2_gif_arbiter.h"', '''#include "runtime/gs/ps2_gif_arbiter.h"
#include "runtime/gs/gs_frontend.h"
#include "runtime/gs/gs_threaded_backend.h"''')
    include(source, '#include "runtime/gs/gs_threaded_backend.h"')
    replace(source, "void GifArbiter::drain()\n{", f"""void GifArbiter::RuntimeGsSink::operator()(const uint8_t *data, uint32_t size) const
{{
    gs->processGIFPacket(data, size);
}}

void GifArbiter::bindRuntimeGs(GS &gs)
{{
    m_processFn = RuntimeGsSink{{&gs}};
}}

std::mutex *GifArbiter::vifGifWorkerBoundary() const
{{
    const auto *sink = m_processFn.target<RuntimeGsSink>();
    if (!sink || !sink->gs->m_vifGifWorkerEnabled.load(std::memory_order_relaxed))
        return nullptr;
    std::lock_guard lock(sink->gs->m_stateMutex);
    return dynamic_cast<GSThreadedBackend *>(sink->gs->m_backend.get()) ?
        &sink->gs->m_vifGifWorkerBoundary : nullptr;
}}

namespace {{
void processWorkerGif(void *target, const uint8_t *data, uint32_t size)
{{
    static_cast<GS *>(target)->processGIFPacket(data, size);
}}
}}

bool GifArbiter::tryQueueVifGif(const uint8_t *data, uint32_t sizeBytes)
{{
    auto *scope = {NS}::activeScope;
    if (!scope || !scope->owns(this) || !m_queue.empty())
        return false;
    const auto *sink = m_processFn.target<RuntimeGsSink>();
    if (!sink || !scope->matches(this, &sink->gs->m_vifGifWorkerBoundary))
        return false;
    if ({NS}::overlaps(data, sizeBytes, sink->gs, sizeof(GS)))
    {{
        scope->fence();
        return false;
    }}
    return scope->trySubmit(sink->gs, processWorkerGif, data, sizeBytes);
}}

void GifArbiter::drain()
{{""")
    replace(source, "    for (size_t i = 0; i < m_queue.size(); ++i)", f"""    auto *scope = {NS}::activeScope;
    if (scope && !scope->owns(this))
        scope = nullptr;
    const auto *sink = scope ? m_processFn.target<RuntimeGsSink>() : nullptr;
    for (size_t i = 0; i < m_queue.size(); ++i)""")
    replace(source, "            m_processFn(pkt.data.data(), static_cast<uint32_t>(pkt.data.size()));", """            const auto size = static_cast<uint32_t>(pkt.data.size());
            if (scope)
            {
                if (pkt.pathId != GifPathId::Path3 && sink &&
                    scope->matches(this, &sink->gs->m_vifGifWorkerBoundary) &&
                    scope->trySubmit(sink->gs, processWorkerGif, pkt.data.data(), size))
                    continue;
                scope->fence();
            }
            m_processFn(pkt.data.data(), size);""")


def patch_frontend(headers, sources):
    header = headers / "gs/gs_frontend.h"
    replace(header, "#include <mutex>", "#include <atomic>\n#include <mutex>")
    replace(header, "    void setRasterBackend(std::unique_ptr<GSRasterBackend> backend);", """    void setRasterBackend(std::unique_ptr<GSRasterBackend> backend);
    // Set before starting guest execution. Requires a threaded raster backend.
    void enableVifGifWorker() { m_vifGifWorkerEnabled.store(true, std::memory_order_relaxed); }""")
    replace(header, "    mutable std::recursive_mutex m_stateMutex;", """    friend class GifArbiter;
    std::mutex m_vifGifWorkerBoundary;
    std::atomic<bool> m_vifGifWorkerEnabled{false};
    mutable std::recursive_mutex m_stateMutex;""")
    source = sources / "gs/gs_frontend.cpp"
    include(source, '#include "runtime/gs/gs_frontend.h"')
    for signature in (
        "void GS::latchHostPresentationFrame()",
        "void GS::setRasterBackend(std::unique_ptr<GSRasterBackend> backend)",
        "void GS::reset()",
    ):
        opening = signature + "\n{"
        replace(source, opening, opening + f"""
    auto vifBoundary = {NS}::lockPresentation(
        m_vifGifWorkerBoundary, m_vifGifWorkerEnabled.load(std::memory_order_relaxed));""")
    replace(source, """    if (ticket)
        frame = m_backend->DisplayPreparedPresentation(ticket);""", """    if (ticket)
    {
        // The snapshot is ordered behind earlier draws. Do not hold the VIF
        // boundary while the host waits for it to become visible.
        if (vifBoundary.owns_lock())
            vifBoundary.unlock();
        frame = m_backend->DisplayPreparedPresentation(ticket);
    }""")


def patch_runtime(sources):
    source = sources / "ps2_runtime.cpp"
    include(source, '#include "ps2_runtime.h"')
    replace(source, """    m_gifArbiter.setProcessPacketFn([this](const uint8_t *data, uint32_t size)
                                    { m_gs.processGIFPacket(data, size); });""",
            "    m_gifArbiter.bindRuntimeGs(m_gs);")
    for name, args in (
        ("Mscal", "uint32_t startPC, uint32_t top, uint32_t itop"),
        ("Mscnt", "uint32_t top, uint32_t itop"),
    ):
        opening = f"m_memory.setVu1{name}Callback([this]({args})"
        text = source.read_text(encoding="utf-8")
        start = text.index(opening)
        end = text.index(" });", start) + len(" });")
        callback = text[start:end]
        body = re.sub(r"\bm_\w+\b", r"rt->\g<0>", callback[len(opening):-len(" });")])
        body = body.replace("{\n", "{\n                                     auto *rt = static_cast<PS2Runtime *>(owner);\n", 1)
        replace(source, callback, f"""m_memory.setVu1{name}Callback({NS}::Runtime{name}{{&m_memory, this,
                                 [](void *owner, {args}){body} }}}});""")
    replace(source, '        ThreadNaming::SetCurrentThreadName("GameThread");', f"""        ThreadNaming::SetCurrentThreadName("GameThread");
        {NS}::ThreadSession vifGifWorker(&m_memory, &m_gifArbiter, m_gifArbiter.vifGifWorkerBoundary());""")


def patch_memory(sources):
    memory = sources / "ps2_memory.cpp"
    include(memory, '#include "runtime/ps2_memory.h"')
    submit = """void PS2Memory::submitGifPacket(GifPathId pathId, const uint8_t *data, uint32_t sizeBytes, bool drainImmediately, bool path2DirectHl)
{"""
    replace(memory, submit + """
    if (!data || sizeBytes < 16)
        return;

    if (pathId == GifPathId::Path3)""", submit + f"""
    if (!data || sizeBytes < 16)
        return;

    if (auto *scope = {NS}::activeScope; scope && scope->owns(m_gifArbiter))
    {{
        if (pathId == GifPathId::Path3 || {NS}::overlaps(data, sizeBytes, m_gsVRAM, PS2_GS_VRAM_SIZE) ||
            {NS}::overlaps(data, sizeBytes, &gs_regs, sizeof(gs_regs)))
            scope->fence();
        else if (drainImmediately && m_gifArbiter->tryQueueVifGif(data, sizeBytes))
            return;
    }}

    if (pathId == GifPathId::Path3)""")

    vif = sources / "ps2_vif1_interpreter.cpp"
    include(vif, '#include <cstring>')
    replace(vif, """void PS2Memory::processVIF1Data(const uint8_t *data, uint32_t sizeBytes)
{
    if (sizeBytes == 0u)
        return;""", f"""void PS2Memory::processVIF1Data(const uint8_t *data, uint32_t sizeBytes)
{{
    if (sizeBytes == 0u)
        return;
    const bool compatible = {NS}::currentSession &&
        {NS}::isRuntimeVuCallback<{NS}::RuntimeMscal>(m_vu1MscalCallback, this) &&
        {NS}::isRuntimeVuCallback<{NS}::RuntimeMscnt>(m_vu1MscntCallback, this) &&
        !{NS}::overlaps(data, sizeBytes, m_gsVRAM, PS2_GS_VRAM_SIZE) &&
        !{NS}::overlaps(data, sizeBytes, &gs_regs, sizeof(gs_regs));
    {NS}::Scope gifWorker(this, m_gifArbiter, compatible,
        [](const void *arbiter, const std::mutex *boundary) {{
            return static_cast<const GifArbiter *>(arbiter)->vifGifWorkerBoundary() == boundary;
        }});""")
    replace(vif, """        // Track most-recent command for VIFn_CODE emulation.""", """        // Preserve all native VIF synchronization and interrupt boundaries.
        if (irq || opcode == VIF_MSKPATH3 || opcode == VIF_FLUSHE ||
            opcode == VIF_FLUSH || opcode == VIF_FLUSHA || opcode == VIF_MSCALF)
            gifWorker.fence();

        // Track most-recent command for VIFn_CODE emulation.""")
    text = vif.read_text(encoding="utf-8").rstrip()
    if not text.endswith("    }\n}"):
        raise ValueError("pinned VIF1 interpreter is no longer the final function")
    vif.write_text(text[:-2] + "\n    gifWorker.finish();\n}\n", encoding="utf-8")


def patch(root):
    runtime = Path(root) / "thirdparty/PS2Recomp/ps2xRuntime"
    headers = runtime / "include/runtime"
    sources = runtime / "src/lib"
    (runtime / "include" / HEADER).write_bytes(Path(__file__).with_suffix(".hpp").read_bytes())
    patch_arbiter(headers, sources)
    patch_frontend(headers, sources)
    patch_runtime(sources)
    patch_memory(sources)
