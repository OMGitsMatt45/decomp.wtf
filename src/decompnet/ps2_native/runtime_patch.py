"""Reviewed integration patches applied only to copied, pinned runtime source."""
from pathlib import Path

from ..pc import PCError


def replace(path, old, new):
    text = path.read_text(encoding='utf-8')
    if text.count(old) != 1: raise PCError('pinned PS2 integration site differs: ' + path.name)
    path.write_text(text.replace(old, new), encoding='utf-8')


def patch_irx_loader(root):
    source=Path(root)/'thirdparty/PS2Recomp/ps2xIOP/src/lle/irx.cpp'
    replace(source,'''        uint16_t type = 0, phentsize = 0, phnum = 0, shentsize = 0, shnum = 0;''',
        '''        out = IrxImage{};
        error.clear();
        uint16_t machine = 0;
        uint16_t type = 0, phentsize = 0, phnum = 0, shentsize = 0, shnum = 0;''')
    replace(source,'''        if (file.size() < 0x34u || std::memcmp(file.data(), "\\x7F" "ELF", 4) != 0 ||''',
        '''        if (file.size() < 0x34u || std::memcmp(file.data(), "\\x7F" "ELF", 4) != 0 ||
            file[4] != 1u || file[5] != 1u || file[6] != 1u ||
            !readAt(file, 0x12, machine) || machine != 8u ||''')
    replace(source,'''        uint32_t loadOffset = 0, loadFileSize = 0, loadMemorySize = 0;''',
        '''        if (phnum == 0u || phentsize < 32u ||
            uint64_t(phoff) + uint64_t(phentsize) * phnum > file.size() ||
            (shnum && (shentsize < 40u || uint64_t(shoff) + uint64_t(shentsize) * shnum > file.size())))
        {
            error = "truncated IRX header tables";
            return false;
        }
        uint32_t loadOffset = 0, loadFileSize = 0, loadMemorySize = 0;''')
    replace(source,'''                uint32_t fields[6];''',
        '''                if (fileSize < 26u || offset > file.size() || fileSize > file.size() - offset)
                {
                    error = "truncated IRX module metadata";
                    return false;
                }
                uint32_t fields[6]{};''')
    replace(source,'''                        break;
                readAt(file, offset + 24u, out.version);''',
        '''                    {
                        error = "truncated IRX module metadata";
                        return false;
                    }
                readAt(file, offset + 24u, out.version);''')
    replace(source,'''        out.image.assign(file.begin() + loadOffset, file.begin() + loadOffset + loadFileSize);''',
        '''        if (out.entry >= loadFileSize || (out.entry & 3u) ||
            uint64_t(out.textSize) + out.dataSize > loadFileSize)
        {
            error = "IRX entry or section sizes exceed its image";
            return false;
        }
        out.image.assign(file.begin() + loadOffset, file.begin() + loadOffset + loadFileSize);''')
    replace(source,'''            for (uint32_t entry = 0; entry + 8u <= size; entry += 8u)''',
        '''            if (size % 8u || offset > file.size() || size > file.size() - offset)
            {
                error = "truncated IRX relocation table";
                return false;
            }
            for (uint32_t entry = 0; entry + 8u <= size; entry += 8u)''')


def patch_emitter(root):
    root = Path(root)
    translator = root / 'thirdparty/PS2Recomp/ps2xRecomp/src/lib/vu_translator.cpp'
    old = '            const uint8_t special1_func = static_cast<uint8_t>(inst.function & 0x3F);'
    new = '''            const uint8_t upper_op = static_cast<uint8_t>(inst.function & 0x3F);
            const uint8_t upper_special = static_cast<uint8_t>((inst.raw & 3u) | ((inst.raw >> 4u) & 0x7cu));
            if (upper_op < 0x30u || (upper_op >= 0x3cu && upper_special < 0x2fu && upper_special != 0x2bu))
                return fmt::format("decomp_ps2::vu_upper<0x{:08X}u>(*ctx);", inst.raw);
''' + old
    replace(translator, old, new)


def install_vu_header(generated):
    generated = Path(generated)
    target = generated / 'decomp_vu0.hpp'
    if target.exists(): raise PCError('VU integration output exists; preserve existing source')
    target.write_bytes(Path(__file__).with_name('vu0.hpp').read_bytes())
    for path in generated.glob('*.cpp'):
        text = path.read_text(encoding='utf-8')
        if 'decomp_ps2::vu_upper<' in text:
            path.write_text('#include "decomp_vu0.hpp"\n' + text, encoding='utf-8')


def patch_filesystem(root):
    root = Path(root)
    source = root / 'thirdparty/PS2Recomp/ps2xRuntime/src/lib/Kernel/Syscalls/FileIO.cpp'
    text = source.read_text(encoding='utf-8')
    changes = {
        'bool read = (ps2Flags & PS2_FIO_O_RDONLY) || (ps2Flags & PS2_FIO_O_RDWR);':
            'const int access = ps2Flags & PS2_FIO_O_RDWR;\n        bool read = access == PS2_FIO_O_RDONLY || access == PS2_FIO_O_RDWR;',
        'bool write = (ps2Flags & PS2_FIO_O_WRONLY) || (ps2Flags & PS2_FIO_O_RDWR);':
            'bool write = access == PS2_FIO_O_WRONLY || access == PS2_FIO_O_RDWR;',
        'FILE *fp = ::fopen(hostPath.c_str(), mode);':'FILE *fp = decomp_ps2::disc::open(hostPath.c_str(), mode, ps2Path);',
        '::fclose(fp)':'decomp_ps2::disc::close(fp)',
        'bytesRead = fread(hostBuf, 1, size, fp);':'bytesRead = decomp_ps2::disc::read(hostBuf, 1, size, fp);',
        '::fseek(fp, static_cast<long>(offset), hostWhence)':'decomp_ps2::disc::seek(fp, offset, hostWhence)',
        'long newPos = ::ftell(fp);':'int64_t newPos = decomp_ps2::disc::tell(fp);',
    }
    for old,new in changes.items():
        if text.count(old) != (2 if old == '::fclose(fp)' else 1):
            raise PCError('pinned PS2 filesystem integration differs: ' + old)
        text = text.replace(old,new)
    header = source.parent / 'decomp_disc_files.hpp'
    if header.exists(): raise PCError('PS2 filesystem integration exists; preserve existing source')
    header.write_bytes(Path(__file__).with_name('disc_files.hpp').read_bytes())
    source.write_text('#include "decomp_disc_files.hpp"\n' + text, encoding='utf-8')
    replace(source,'''        setReturnS32(ctx, -1);
    }

    void fioRemove''','''        const uint32_t physical=statBufAddr & 0x1fffffffu;
        if (physical > PS2_RAM_SIZE-40u) {setReturnS32(ctx,-1);return;}
        std::error_code ec;
        uint64_t size=0;uint32_t mode=PS2_FIO_S_IFREG;
        const auto status=std::filesystem::status(hostPath,ec);
        if (!ec && std::filesystem::exists(status)) {
            if (std::filesystem::is_directory(status)) mode=PS2_FIO_S_IFDIR;
            else {size=std::filesystem::file_size(hostPath,ec);if(ec){setReturnS32(ctx,-1);return;}}
        } else {
            decomp_ps2::disc::Entry original;
            if (!decomp_ps2::disc::disc_path(ps2Path) || !decomp_ps2::disc::lookup(ps2Path,original)) {setReturnS32(ctx,-1);return;}
            size=original.size;
        }
        std::memset(ps2StatBuf,0,40);
        const uint32_t low=static_cast<uint32_t>(size),high=static_cast<uint32_t>(size>>32);
        std::memcpy(ps2StatBuf,&mode,4);std::memcpy(ps2StatBuf+8,&low,4);std::memcpy(ps2StatBuf+36,&high,4);
        setReturnS32(ctx,0);
    }

    void fioRemove''')


def patch_disc_services(root):
    support=Path(root)/'thirdparty/PS2Recomp/ps2xRuntime/src/lib/Kernel/Stubs/Helpers/Support.h'
    replace(support,'#include <cctype>', '#include <cctype>\n#include "../../Syscalls/decomp_disc_files.hpp"')
    replace(support,'''    bool registerCdFile(const std::string &ps2Path, CdFileEntry &entryOut)
    {''','''    bool registerCdFile(const std::string &ps2Path, CdFileEntry &entryOut)
    {
        decomp_ps2::disc::Entry original;
        if (decomp_ps2::disc::lookup(ps2Path, original)) {
            if (original.lba > UINT32_MAX || original.size > UINT32_MAX) {g_lastCdError=-1;return false;}
            entryOut = { {}, static_cast<uint32_t>(original.size), static_cast<uint32_t>(original.lba),
                static_cast<uint32_t>((original.size + 2047u) / 2048u) };
            g_lastCdError=0;return true;
        }''')
    replace(support,'''    bool readCdSectors(uint32_t lbn, uint32_t sectors, uint8_t *dst, size_t byteCount)
    {''','''    bool readCdSectors(uint32_t lbn, uint32_t sectors, uint8_t *dst, size_t byteCount)
    {
        if (decomp_ps2::disc::mounted()) {
            const bool ok=decomp_ps2::disc::read_sectors(lbn,sectors,dst,byteCount);
            g_lastCdError=ok?0:-1;return ok;
        }''')


def patch_host(root):
    root=Path(root)
    header=root/'thirdparty/PS2Recomp/ps2xRuntime/include/ps2_runtime.h'
    replace(header,'    void run();', '''    void run();
    std::atomic<uint64_t> decompMissingFunctions{0};
    std::atomic<uint64_t> decompExecutionFailures{0};''')
    replace(header,'        // Initialize VU0 registers',
        '        vu0_vf[0] = _mm_set_ps(1.0f,0.0f,0.0f,0.0f);\n        // Initialize VU0 registers')
    source=root/'thirdparty/PS2Recomp/ps2xRuntime/src/lib/ps2_runtime.cpp'
    (source.parent/'decomp_cdvd_rpc.hpp').write_bytes(Path(__file__).with_name('cdvd_rpc.hpp').read_bytes())
    replace(source,'#include "ps2_runtime.h"','#include "ps2_runtime.h"\n#include "decomp_cdvd_rpc.hpp"')
    replace(source,'''    auto scope = m_iopHost->enterCall(ctx, rdram);
    request.callToken = scope.token();''','''    if (const auto response=decomp_ps2::cdvd_scmd(rdram,request)) return *response;
    auto scope = m_iopHost->enterCall(ctx, rdram);
    request.callToken = scope.token();''')
    replace(source,'    const bool firstReport = !m_missingFunctionReported.exchange(true, std::memory_order_acq_rel);',
        '    ++decompMissingFunctions;\n    const bool firstReport = !m_missingFunctionReported.exchange(true, std::memory_order_acq_rel);')
    replace(source,'            std::cerr << "Error during program execution: " << e.what() << std::endl;',
        '            ++decompExecutionFailures;\n            std::cerr << "Error during program execution: " << e.what() << std::endl;')
    replace(source,'            std::cerr << "Error during program execution: unknown exception" << std::endl;',
        '            ++decompExecutionFailures;\n            std::cerr << "Error during program execution: unknown exception" << std::endl;')
    replace(source,'        runtime.requestStop();\n        return false;',
        '        ++runtime.decompExecutionFailures;\n        runtime.requestStop();\n        return false;')
    cpu=root/'thirdparty/PS2Recomp/ps2xRuntime/src/lib/gs/gs_cpu_backend.cpp'
    replace(cpu,'    const uint32_t ztestMethod = static_cast<uint32_t>((ctx.test >> 17) & 3u);',
        '    const bool depthEnabled = ((ctx.test >> 16) & 1u) != 0u;\n    const uint32_t ztestMethod = depthEnabled ? static_cast<uint32_t>((ctx.test >> 17) & 3u) : 1u;')
    replace(cpu,'    if (writeMask.writeDepth && !ctx.zbuf.zmask)',
        '    if (depthEnabled && writeMask.writeDepth && !ctx.zbuf.zmask)')
    replace(root/'thirdparty/PS2Recomp/ps2xRuntime/src/lib/Kernel/Stubs/CD.cpp',
        '// SCECdPS2DVD\n        setReturnS32(ctx, 0x14);',
        '// Selected owner medium, including raw CD images.\n        setReturnS32(ctx, decomp_ps2::disc::medium());')
    # The shared renderer is source-shipped without another project's branding.
    cmake=root/'src/gfx/CMakeLists.txt'
    replace(cmake,'''    include("${DQ8_GFX_ROOT}/cmake/Dq8Icon.cmake")
    dq8_embed_window_icon(dq8_gfx_sdlgpu)''','    # The exported game supplies its own branding.')
    (root/'src/gfx/backends/sdlgpu/sdlgpu_window_icon.cpp').write_text(
        '#include "gfx/backends/sdlgpu/sdlgpu_window.h"\nnamespace dq8::gfx { void setWindowIcon(SDL_Window *) {} }\n',encoding='utf-8')
    backend=root/'src/gfx/backends/sdlgpu/sdlgpu_backend.cpp'
    replace(root/'src/gfx/backends/sdlgpu/sdlgpu_backend.h','struct SdlGpuStats {',
        'struct SdlGpuStats {\n    uint32_t sourceWidth=0,sourceHeight=0;')
    replace(backend,'        m_impl->finishPresentation(stage);',
        '        m_impl->finishPresentation(stage);\n        m_impl->stats.sourceWidth=stage.frame.width / std::max(1u,m_impl->scale);\n        m_impl->stats.sourceHeight=stage.frame.height / std::max(1u,m_impl->scale);')
    # SDL tracks image layouts while recording commands. Presentation and
    # guest draws share the same device/texture caches; serialize their command
    # recording, including capture/readback, rather than racing both producers.
    replace(backend,'    const auto *prepared = dynamic_cast<const Impl::PreparedFrame *>(ticket.get());',
        '    std::lock_guard displayLock(m_impl->mutex);\n    const auto *prepared = dynamic_cast<const Impl::PreparedFrame *>(ticket.get());')
    replace(backend,'m_impl->scale = std::clamp<uint32_t>(scale, 1u, 8u);',
        'm_impl->scale = std::clamp<uint32_t>(scale, 1u, 16u);')
    replace(backend,'m_impl->requestedScale.store(std::clamp<uint32_t>(scale, 1u, 8u), std::memory_order_release);',
        'm_impl->requestedScale.store(std::clamp<uint32_t>(scale, 1u, 16u), std::memory_order_release);')
    replace(root/'src/gfx/backends/sdlgpu/sdlgpu_targets.cpp',
        'const uint32_t clamped = std::clamp<uint32_t>(scale, 1u, 8u);',
        'const uint32_t clamped = std::clamp<uint32_t>(scale, 1u, 16u);')
