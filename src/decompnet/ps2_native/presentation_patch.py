"""Capture a PS2 picture's authored aspect before asynchronous preparation."""
from pathlib import Path

from .runtime_patch import replace


def patch(root):
    root = Path(root)
    runtime = root / 'thirdparty/PS2Recomp/ps2xRuntime'
    headers = runtime / 'include/runtime/gs'
    sources = runtime / 'src/lib/gs'
    graphics = root / 'src/gfx/backends/sdlgpu'

    types = headers / 'gs_types.h'
    replace(types, 'struct GSPresentationRequest\n', '''enum class GSPresentationAspect : int8_t
{
    Unknown = -1,
    Standard = 0,
    Widescreen = 1,
};

struct GSPresentationRequest
''')
    replace(types, '''    bool hasPreferredSource = false;
};

enum class GSPresentationMode''', '''    bool hasPreferredSource = false;
    // Authored display aspect at the presentation producer's boundary.
    GSPresentationAspect pictureAspect = GSPresentationAspect::Unknown;
};

enum class GSPresentationMode''')
    replace(headers / 'gs_backend.h', 'class GSRasterBackend\n', '''// Optional source queried before preparing a picture on any worker.
class GSPresentationAspectSource
{
public:
    virtual ~GSPresentationAspectSource() = default;
    virtual GSPresentationAspect capturePresentationAspect() const = 0;
};

class GSRasterBackend
''')
    replace(sources / 'gs_frontend.cpp', '    request.hasPreferredSource = m_hasPreferredDisplaySource;\n',
            '''    request.hasPreferredSource = m_hasPreferredDisplaySource;
    if (const auto *aspectSource = dynamic_cast<const GSPresentationAspectSource *>(m_backend.get()))
        request.pictureAspect = aspectSource->capturePresentationAspect();
''')
    worker = headers / 'gs_threaded_backend.h'
    replace(worker, 'class GSThreadedBackend final : public GSRasterBackend\n',
            'class GSThreadedBackend final : public GSRasterBackend, public GSPresentationAspectSource\n')
    replace(worker, '    bool SupportsPreparedPresentation() const override;\n',
            '''    bool SupportsPreparedPresentation() const override;
    GSPresentationAspect capturePresentationAspect() const override;
''')
    replace(sources / 'gs_threaded_backend.cpp', 'bool GSThreadedBackend::SupportsPreparedPresentation() const\n',
            '''GSPresentationAspect GSThreadedBackend::capturePresentationAspect() const
{
    const auto *source = dynamic_cast<const GSPresentationAspectSource *>(m_impl->backend.get());
    return source ? source->capturePresentationAspect() : GSPresentationAspect::Unknown;
}

bool GSThreadedBackend::SupportsPreparedPresentation() const
''')
    sdl_header = graphics / 'sdlgpu_backend.h'
    replace(sdl_header, 'class SdlGpuBackend final : public GSRasterBackend {\n',
            'class SdlGpuBackend final : public GSRasterBackend, public GSPresentationAspectSource {\n')
    replace(sdl_header, '''    // The game's Screen Size option for SdlGpuAspect::Auto, read on the
    // presenting thread: 1 for 16:9, 0 for 4:3, -1 unknown.
''', '''    // Captured on the GS producer for SdlGpuAspect::Auto, before preparing
    // its picture. Returns 1 for 16:9, 0 for 4:3, -1 if unknown.
''')
    replace(sdl_header, '    int gameWidescreen() const;\n',
            '''    int gameWidescreen() const;
    GSPresentationAspect capturePresentationAspect() const override;
''')
    sdl = graphics / 'sdlgpu_backend.cpp'
    replace(sdl, '''        SDL_GPUFence *prepared = nullptr, *displayed = nullptr;
        bool leased = false;
    };''', '''        SDL_GPUFence *prepared = nullptr, *displayed = nullptr;
        bool leased = false;
        GSPresentationAspect pictureAspect = GSPresentationAspect::Unknown;
    };''')
    replace(sdl, '                                     swapchainHeight, gameWidescreen());',
            '                                     swapchainHeight, static_cast<int>(slot->pictureAspect));')
    replace(sdl, '    prepared->haveFrame = stage.haveFrame;\n',
            '''    prepared->haveFrame = stage.haveFrame;
    if (stage.haveFrame)
        slot.pictureAspect = request.pictureAspect;
''')
    replace(sdl, '''int SdlGpuBackend::gameWidescreen() const {
    return m_impl->gameWidescreen();
}
''', '''int SdlGpuBackend::gameWidescreen() const {
    return m_impl->gameWidescreen();
}

GSPresentationAspect SdlGpuBackend::capturePresentationAspect() const {
    switch (gameWidescreen()) {
    case 0: return GSPresentationAspect::Standard;
    case 1: return GSPresentationAspect::Widescreen;
    default: return GSPresentationAspect::Unknown;
    }
}
''')
