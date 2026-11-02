"""Reuse bounded SDL GPU staging storage without changing GS ownership rules."""
from pathlib import Path
from .runtime_patch import replace


def patch(root, *, owned_rows=True):
    folder=Path(root)/'src/gfx/backends/sdlgpu'
    header=folder/'sdlgpu_targets.h'
    replace(header,'    SDL_GPUTransferBuffer *m_upload = nullptr;', '''    SDL_GPUTransferBuffer *downloadBuffer(uint32_t bytes, std::string &error);
    SDL_GPUTexture *nativeTexture(SDL_GPUTexture *&texture, uint32_t &width,
                                  uint32_t &height, uint32_t requiredWidth,
                                  uint32_t requiredHeight, std::string &error);
    SDL_GPUTransferBuffer *m_download = nullptr;
    uint32_t m_downloadCapacity = 0u;
    SDL_GPUTexture *m_resolveNative = nullptr, *m_refreshNative = nullptr;
    uint32_t m_resolveWidth = 0u, m_resolveHeight = 0u;
    uint32_t m_refreshWidth = 0u, m_refreshHeight = 0u;
    SDL_GPUTransferBuffer *m_upload = nullptr;''')
    target=folder/'sdlgpu_targets.cpp'
    replace(target,'    m_uploadCapacity = 0u;\n}', '''    m_uploadCapacity = 0u;
    if (m_device.valid()) {
        if (m_download) SDL_ReleaseGPUTransferBuffer(m_device.handle(), m_download);
        if (m_resolveNative) SDL_ReleaseGPUTexture(m_device.handle(), m_resolveNative);
        if (m_refreshNative) SDL_ReleaseGPUTexture(m_device.handle(), m_refreshNative);
    }
    m_download = nullptr; m_downloadCapacity = 0u;
    m_resolveNative = m_refreshNative = nullptr;
    m_resolveWidth = m_resolveHeight = m_refreshWidth = m_refreshHeight = 0u;
}

SDL_GPUTransferBuffer *GsTargetCache::downloadBuffer(uint32_t bytes, std::string &error) {
    // Resolve calls wait for their fence and unmap before this storage is reused.
    if (m_download && m_downloadCapacity >= bytes) return m_download;
    if (m_download) SDL_ReleaseGPUTransferBuffer(m_device.handle(), m_download);
    SDL_GPUTransferBufferCreateInfo info{};
    info.usage = SDL_GPU_TRANSFERBUFFERUSAGE_DOWNLOAD;
    info.size = (bytes + 65535u) & ~65535u;
    m_download = SDL_CreateGPUTransferBuffer(m_device.handle(), &info);
    m_downloadCapacity = m_download ? info.size : 0u;
    if (!m_download) error = std::string("SDL_CreateGPUTransferBuffer(resolve cache): ") + SDL_GetError();
    return m_download;
}

SDL_GPUTexture *GsTargetCache::nativeTexture(SDL_GPUTexture *&texture, uint32_t &width,
        uint32_t &height, uint32_t requiredWidth, uint32_t requiredHeight, std::string &error) {
    // One growable texture per direction. GPU copies/blits retain queue order;
    // only the requested rectangle participates, including when capacity is larger.
    if (texture && width >= requiredWidth && height >= requiredHeight) return texture;
    if (texture) SDL_ReleaseGPUTexture(m_device.handle(), texture);
    width = std::max(width, requiredWidth); height = std::max(height, requiredHeight);
    SDL_GPUTextureCreateInfo info{};
    info.type = SDL_GPU_TEXTURETYPE_2D;
    info.format = SDL_GPU_TEXTUREFORMAT_R8G8B8A8_UNORM;
    info.width = width; info.height = height;
    info.layer_count_or_depth = 1u; info.num_levels = 1u;
    info.sample_count = SDL_GPU_SAMPLECOUNT_1;
    info.usage = SDL_GPU_TEXTUREUSAGE_COLOR_TARGET | SDL_GPU_TEXTUREUSAGE_SAMPLER;
    texture = SDL_CreateGPUTexture(m_device.handle(), &info);
    if (!texture) error = std::string("SDL_CreateGPUTexture(native staging cache): ") + SDL_GetError();
    return texture;
}''')
    text=target.read_text()
    # Batch and individual resolves are synchronous, and share one download buffer.
    start=text.index('    SDL_GPUTransferBufferCreateInfo info{};',text.index('bool GsTargetCache::resolveSurfaces'))
    end=text.index('    SDL_GPUCommandBuffer *commands',start)
    text=text[:start]+'''    SDL_GPUTransferBuffer *download = downloadBuffer(static_cast<uint32_t>(bytes), error);
    if (!download) return false;
'''+text[end:]
    start=text.index('    if (surface.scale != 1u) {',text.index('bool GsTargetCache::downloadScaled'))
    end=text.index('    SDL_GPUCommandBuffer *commands',start)
    text=text[:start]+'''    if (surface.scale != 1u) {
        staging = nativeTexture(m_resolveNative, m_resolveWidth, m_resolveHeight, width, height, error);
        if (!staging) return false;
        native = staging; sourceX = sourceY = 0u;
    }
    SDL_GPUTransferBuffer *download = downloadBuffer(static_cast<uint32_t>(bytes), error);
    if (!download) return false;

'''+text[end:]
    start=text.index('    if (surface.scale != 1u) {',text.index('bool GsTargetCache::uploadNative'))
    end=text.index('    if (!m_upload ||',start)
    text=text[:start]+'''    if (surface.scale != 1u) {
        native = nativeTexture(m_refreshNative, m_refreshWidth, m_refreshHeight, width, height, error);
        if (!native) return false;
    }

'''+text[end:]
    # Drop only the per-call cleanup: reset() owns the cached allocations.
    for name,next_name in [('resolveSurfaces','resolveSurface'),('downloadScaled','applyCpuPatches'),('uploadNative',None)]:
        start=text.index('bool GsTargetCache::'+name+'(')
        end=text.index('bool GsTargetCache::'+next_name+'(',start) if next_name else len(text)
        body=text[start:end].replace('            release();\n','').replace('        release();\n','').replace('    release();\n','')
        text=text[:start]+body+text[end:]
    target.write_text(text)
    if owned_rows:
        (Path(root)/'src/gfx/gs/decomp_owned_write.hpp').write_bytes(Path(__file__).with_name('gs_owned_write.hpp').read_bytes())
        replace(target,'#include "gfx/backends/sdlgpu/sdlgpu_targets.h"',
            '#include "gfx/backends/sdlgpu/sdlgpu_targets.h"\n#include "gfx/gs/decomp_owned_write.hpp"')
        replace(target,'''    } else {
        for (uint32_t y = region.y0; y < region.y1; ++y) {
            const uint8_t *row =''', '''    } else if (surface.psm == GS_PSM_CT32) {
        decomp_ps2::graphics::writeOwnedCt32(m_vram.data(), surface.base, surface.bufferWidth,
            region.x0, region.y0, region.x1, region.y1, surface.ownedPages, pixels);
    } else {
        for (uint32_t y = region.y0; y < region.y1; ++y) {
            const uint8_t *row =''')

    backend=folder/'sdlgpu_backend.cpp'
    replace(backend,'    SDL_GPUTexture *dummyTexture = nullptr;', '''    SDL_GPUTransferBuffer *feedbackUpload = nullptr;
    uint32_t feedbackUploadCapacity = 0u;
    SDL_GPUTexture *dummyTexture = nullptr;''')
    text=backend.read_text();start=text.index('        const auto releaseUpload =',text.index('SDL_GPUTexture *snapshotFeedback('))
    end=text.index('            uint32_t offset = 0u;',start)
    text=text[:start]+'''        SDL_GPUTransferBuffer *upload = nullptr;
        if (uploadBytes != 0u) {
            if (!targets->resolve(tailPages, error)) return nullptr;
            if (!feedbackUpload || feedbackUploadCapacity < uploadBytes) {
                if (feedbackUpload) SDL_ReleaseGPUTransferBuffer(device.handle(), feedbackUpload);
                SDL_GPUTransferBufferCreateInfo info{};
                info.usage = SDL_GPU_TRANSFERBUFFERUSAGE_UPLOAD;
                info.size = (uploadBytes + 65535u) & ~65535u;
                feedbackUpload = SDL_CreateGPUTransferBuffer(device.handle(), &info);
                feedbackUploadCapacity = feedbackUpload ? info.size : 0u;
            }
            upload = feedbackUpload;
            if (!upload) {
                error = std::string("SDL_CreateGPUTransferBuffer(feedback tail): ") + SDL_GetError();
                return nullptr;
            }
            // Cycle only storage still referenced by queued copies.
            auto *mapped = static_cast<uint8_t *>(SDL_MapGPUTransferBuffer(device.handle(), upload, true));
            if (!mapped) {
                error = std::string("SDL_MapGPUTransferBuffer(feedback tail): ") + SDL_GetError();
                return nullptr;
            }
'''+text[end:]
    start=text.index('    SDL_GPUTexture *snapshotFeedback(');end=text.index('    void submit(',start)
    text=text[:start]+text[start:end].replace('upload.get()','upload')+text[end:]
    backend.write_text(text)
    replace(backend,'        if (m_impl->dummyTexture)\n', '''        if (m_impl->feedbackUpload)
            SDL_ReleaseGPUTransferBuffer(m_impl->device.handle(), m_impl->feedbackUpload);
        if (m_impl->dummyTexture)
''')
