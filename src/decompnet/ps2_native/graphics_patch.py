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
    _sparsify_target_regions(target)
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
    _reuse_draw_state(backend)
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


def _sparsify_target_regions(target):
    """Visit sparse VRAM aliases without scanning every target cell."""
    replace(target, '''    const uint32_t basePage = surface.base >> 5u;
    const uint32_t pageRows = (surface.height + extent.height - 1u) / extent.height;

    for (uint32_t row = 0u; row < pageRows; ++row) {
        for (uint32_t column = 0u; column < pagesPerRow; ++column) {
            const uint32_t page = (basePage + row * pagesPerRow + column) % kGsPageCount;
            if (!pages.test(page))
                continue;
            GsRegion cell{column * extent.width, row * extent.height,
                          (column + 1u) * extent.width, (row + 1u) * extent.height};
            cell.x1 = std::min(cell.x1, surface.width);
            cell.y1 = std::min(cell.y1, surface.height);
            region.merge(cell);
        }
    }''', '''    const uint32_t basePage = (surface.base >> 5u) % kGsPageCount;
    const uint32_t pageRows = (surface.height + extent.height - 1u) / extent.height;
    const uint32_t pageColumns = std::min(pagesPerRow,
        (surface.width + extent.width - 1u) / extent.width);
    const uint32_t visibleCells = pageRows * pageColumns;
    auto mergeCell = [&](uint32_t row, uint32_t column) {
        GsRegion cell{column * extent.width, row * extent.height,
                      (column + 1u) * extent.width, (row + 1u) * extent.height};
        cell.x1 = std::min(cell.x1, surface.width);
        cell.y1 = std::min(cell.y1, surface.height);
        region.merge(cell);
    };

    // Sparse writes are cheaper to visit by VRAM page than by surface cell.
    // Revisit a page at every VRAM wrap if the layout aliases itself.
    if (visibleCells >= 64u && pages.count() <= visibleCells / 8u) {
        const GsPageSet lowWord(~0ull);
        const uint32_t cells = pageRows * pagesPerRow;
        for (uint32_t first = 0u; first < kGsPageCount; first += 64u) {
            for (uint64_t word = ((pages >> first) & lowWord).to_ullong();
                 word != 0u; word &= word - 1u) {
                const uint32_t page = first + static_cast<uint32_t>(std::countr_zero(word));
                const uint32_t relative = (page + kGsPageCount - basePage) % kGsPageCount;
                for (uint32_t cell = relative; cell < cells; cell += kGsPageCount)
                    mergeCell(cell / pagesPerRow, cell % pagesPerRow);
            }
        }
        return region;
    }

    for (uint32_t row = 0u; row < pageRows; ++row) {
        for (uint32_t column = 0u; column < pageColumns; ++column) {
            const uint32_t page = (basePage + row * pagesPerRow + column) % kGsPageCount;
            if (pages.test(page))
                mergeCell(row, column);
        }
    }''')
    replace(target, '''        if (&other != &surface && !other.depth && (other.pages & writtenPages).any())
            other.needsUpload.merge(regionForPages(other, writtenPages));''', '''        if (&other != &surface && !other.depth && (other.pages & writtenPages).any() &&
            !other.needsUpload.contains(other.wholeRegion())) {
            other.needsUpload.merge(regionForPages(other, writtenPages));
        }''')


def _reuse_draw_state(backend):
    """Retain identical SDL draw bindings within one render pass."""
    replace(backend, '''        GsSurface *activeDepth = nullptr;
        GsPageSet drawnPages;

        auto endPass = [&]() {
            if (pass) {
                SDL_EndGPURenderPass(pass);
                pass = nullptr;
            }
        };''', '''        GsSurface *activeDepth = nullptr;
        GsPageSet drawnPages;
        const DrawBatch *boundBatch = nullptr;
        SDL_GPUTexture *boundTexture = nullptr;

        auto endPass = [&]() {
            if (pass) {
                SDL_EndGPURenderPass(pass);
                pass = nullptr;
                boundBatch = nullptr;
                boundTexture = nullptr;
            }
        };''')
    replace(backend, '''            SDL_GPUGraphicsPipeline *pipeline = device.pipeline(batch.pipeline, error);
            if (!pipeline) {
                endPass();
                return setError(std::move(error));
            }
            SDL_BindGPUGraphicsPipeline(pass, pipeline);
            SDL_SetGPUScissor(pass, &batch.scissor);
            if (batch.usesBlendConstant) {
                const SDL_FColor constant{batch.blendConstant, batch.blendConstant,
                                          batch.blendConstant, batch.blendConstant};
                SDL_SetGPUBlendConstants(pass, constant);
            }

            const SDL_GPUTextureSamplerBinding textureBinding{
                sampledTexture ? sampledTexture : dummyTexture, device.sampler()};
            SDL_BindGPUFragmentSamplers(pass, 0u, &textureBinding, 1u);

            SDL_PushGPUVertexUniformData(commands, 0u, &batch.vertexUniforms,
                                         sizeof(batch.vertexUniforms));
            SDL_PushGPUFragmentUniformData(commands, 0u, &batch.fragmentUniforms,
                                           sizeof(batch.fragmentUniforms));
            SDL_DrawGPUPrimitives(pass, batch.vertexCount, 1u, batch.firstVertex, 0u);
            ++stats.drawCalls;''', '''            // SDL invalidates graphics descriptors on a pipeline bind. Reapply
            // all inputs on a bind, and reuse unchanged inputs within the pass.
            const bool bindPipeline = !boundBatch || !(batch.pipeline == boundBatch->pipeline);
            if (bindPipeline) {
                SDL_GPUGraphicsPipeline *pipeline = device.pipeline(batch.pipeline, error);
                if (!pipeline) {
                    endPass();
                    return setError(std::move(error));
                }
                SDL_BindGPUGraphicsPipeline(pass, pipeline);
            }
            if (bindPipeline || batch.scissor.x != boundBatch->scissor.x ||
                batch.scissor.y != boundBatch->scissor.y ||
                batch.scissor.w != boundBatch->scissor.w ||
                batch.scissor.h != boundBatch->scissor.h) {
                SDL_SetGPUScissor(pass, &batch.scissor);
            }
            if (batch.usesBlendConstant &&
                (bindPipeline || !boundBatch->usesBlendConstant ||
                 batch.blendConstant != boundBatch->blendConstant)) {
                const SDL_FColor constant{batch.blendConstant, batch.blendConstant,
                                          batch.blendConstant, batch.blendConstant};
                SDL_SetGPUBlendConstants(pass, constant);
            }

            SDL_GPUTexture *texture = sampledTexture ? sampledTexture : dummyTexture;
            if (bindPipeline || texture != boundTexture) {
                const SDL_GPUTextureSamplerBinding textureBinding{texture, device.sampler()};
                SDL_BindGPUFragmentSamplers(pass, 0u, &textureBinding, 1u);
                boundTexture = texture;
            }
            if (bindPipeline || std::memcmp(&batch.vertexUniforms, &boundBatch->vertexUniforms,
                                            sizeof(batch.vertexUniforms)) != 0) {
                SDL_PushGPUVertexUniformData(commands, 0u, &batch.vertexUniforms,
                                             sizeof(batch.vertexUniforms));
            }
            if (bindPipeline || std::memcmp(&batch.fragmentUniforms, &boundBatch->fragmentUniforms,
                                            sizeof(batch.fragmentUniforms)) != 0) {
                SDL_PushGPUFragmentUniformData(commands, 0u, &batch.fragmentUniforms,
                                               sizeof(batch.fragmentUniforms));
            }
            SDL_DrawGPUPrimitives(pass, batch.vertexCount, 1u, batch.firstVertex, 0u);
            boundBatch = &batch;
            ++stats.drawCalls;''')
