"""Remove inherited title-global writes from the shared MPEG service."""
from pathlib import Path
from .runtime_patch import replace
from ..pc import PCError


def install(root):
    source=Path(root)/'thirdparty/PS2Recomp/ps2xRuntime/src/lib/Kernel/Stubs/MPEG.cpp'
    (source.parent/'decomp_mpeg_raw8.hpp').write_bytes(Path(__file__).with_name('mpeg_raw8.hpp').read_bytes())
    replace(source,'            std::vector<uint8_t> rgba;','            std::vector<uint8_t> rgba;\n            std::vector<uint8_t> yuv420;')
    replace(source,'                frames.push_back(std::move(decoded));',
        '''                const unsigned cw=(width+1)/2,ch=(height+1)/2;
                decoded.yuv420.resize(size_t(width)*height+2ull*cw*ch);
                uint8_t *planes[]={decoded.yuv420.data(),decoded.yuv420.data()+size_t(width)*height,
                    decoded.yuv420.data()+size_t(width)*height+size_t(cw)*ch,nullptr};
                int strides[]={width,int(cw),int(cw),0};
                if (srcFormat==AV_PIX_FMT_YUV420P) {
                    for (unsigned p=0;p<3;++p)for (unsigned y=0;y<(p?ch:unsigned(height));++y)
                        std::memcpy(planes[p]+y*strides[p],m_frame->data[p]+ptrdiff_t(y)*m_frame->linesize[p],p?cw:unsigned(width));
                } else {
                    SwsContext *raw=sws_getContext(width,height,srcFormat,width,height,AV_PIX_FMT_YUV420P,SWS_POINT,nullptr,nullptr,nullptr);
                    if (!raw) return false;
                    const int rows=sws_scale(raw,m_frame->data,m_frame->linesize,0,height,planes,strides);
                    sws_freeContext(raw);
                    if (rows!=height) return false;
                }
                frames.push_back(std::move(decoded));''')
    replace(source,'            MpegFfmpegDecoder &operator=(const MpegFfmpegDecoder &) = delete;',
        '''            MpegFfmpegDecoder &operator=(const MpegFfmpegDecoder &) = delete;
            void clearReferences() {
                if (m_codecCtx) avcodec_flush_buffers(m_codecCtx);
                m_drained=false;
            }''')
    replace(source,'            void reset() {}','            void reset() {}\n            void clearReferences() {}')
    replace(source,'''        (void)ctx;
        (void)runtime;
        static const uint32_t kRefGlobalAddrs[] = {
            0x171800u, 0x17180Cu, 0x171818u, 0x171804u, 0x171810u, 0x17181Cu};
        for (uint32_t addr : kRefGlobalAddrs)
        {
            uint8_t *p = getMemPtr(rdram, addr);
            if (!p)
                continue;
            uint32_t ptr = *reinterpret_cast<uint32_t *>(p);
            if (ptr != 0u)
            {
                uint8_t *q = getMemPtr(rdram, ptr + 0x28u);
                if (q)
                    *reinterpret_cast<uint32_t *>(q) = 0u;
            }
        }''','''        (void)rdram;
        (void)runtime;
        std::lock_guard<std::mutex> lock(g_mpeg_stub_mutex);
        auto &playback=getPlaybackState(getRegU32(ctx,4));
        if (playback.decoder) playback.decoder->clearReferences();''')
    replace(source,'''        mpegGuestWrite32(rdram, uVar3 + 0x1C, 0x1209F8u);
        mpegGuestWrite32(rdram, uVar3 + 0x24, 0x120A08u);''',
        '''        // The host decoder owns these helpers; no guest title addresses.
        mpegGuestWrite32(rdram, uVar3 + 0x1C, 0u);
        mpegGuestWrite32(rdram, uVar3 + 0x24, 0u);''')
    replace(source,'''        mpegGuestWrite32(rdram, 0x1717BCu, param_1);

        static const uint32_t s_refValues[] = {
            0x171A50u, 0x171C58u, 0x171CC0u, 0x171D28u, 0x171D90u,
            0x171AB8u, 0x171B20u, 0x171B88u, 0x171BF0u};
        for (unsigned i = 0; i < 9u; ++i)
            mpegGuestWrite32(rdram, 0x171800u + i * 4u, s_refValues[i]);
''','')
    replace(source,'        mpegGuestWrite32(rdram, 0x171904u, 0u);','')
    old='            const uint32_t macroblockColumns = outWidth / 16u;'
    new='''            const uint32_t macroblockColumns = outWidth / 16u;
            const uint64_t bytes=uint64_t(outWidth)*outHeight*4u;
            const uint32_t physical=destAddr&0x1fffffffu;
            if (bytes>PS2_RAM_SIZE || physical>PS2_RAM_SIZE-bytes)
                throw std::runtime_error("MPEG RGBA output exceeds guest RAM");'''
    text=source.read_text(encoding='utf-8')
    if text.count(old)!=2:raise PCError('pinned MPEG image writer layout differs')
    source.write_text(text.replace(old,new),encoding='utf-8')
    replace(source,'    void sceMpegGetPicture(uint8_t *rdram, R5900Context *ctx, PS2Runtime *runtime)\n',
        '    #include "decomp_mpeg_raw8.hpp"\n    static void decompMpegPicture(uint8_t *rdram, R5900Context *ctx, PS2Runtime *runtime, unsigned mode)\n')
    # Resume the same output format after an asynchronous decoder/VSync wait.
    text=source.read_text(encoding='utf-8')
    start=text.index('    static void decompMpegPicture(');end=text.index('    void sceMpegGetPictureRAW8(',start)
    body=text[start:end].replace('[rdram, runtime](R5900Context &resumeContext)',
        '[rdram, runtime, mode](R5900Context &resumeContext)').replace('sceMpegGetPicture(rdram, &resumeContext, runtime);',
        'decompMpegPicture(rdram, &resumeContext, runtime, mode);')
    text=text[:start]+body+text[end:];source.write_text(text,encoding='utf-8')
    replace(source,'                *reinterpret_cast<uint32_t *>(inner + 0xb0) = 1;',
        '                *reinterpret_cast<uint32_t *>(inner + 0xb0) = mode==0?1u:0u;')
    replace(source,'                *reinterpret_cast<uint32_t *>(inner + 0xdc) = 0;',
        '                *reinterpret_cast<uint32_t *>(inner + 0xdc) = mode==2?getRegU32(ctx,6)*16u:0u;')
    replace(source,'                *reinterpret_cast<uint32_t *>(inner + 0xe0) = 0;',
        '                *reinterpret_cast<uint32_t *>(inner + 0xe0) = mode==2?getRegU32(ctx,7)*16u:0u;')
    replace(source,'                *reinterpret_cast<uint32_t *>(inner + 0xe4) = getRegU32(ctx, 6);',
        '                *reinterpret_cast<uint32_t *>(inner + 0xe4) = mode==2?getRegU32(ctx,6)*getRegU32(ctx,7):getRegU32(ctx,6);')
    replace(source,'            writeDecodedFrameToGuest(rdram, imageAddr, frame);',
        '''            if (mode==0) writeDecodedFrameToGuest(rdram,imageAddr,frame);
            else decompWriteRaw8(rdram,imageAddr,frame,getRegU32(ctx,6),getRegU32(ctx,7),mode==2);''')
    replace(source,'        else if (frameCount == 0u)','        else if (frameCount == 0u && mode==0)')
    replace(source,'''    void sceMpegGetPictureRAW8(uint8_t *rdram, R5900Context *ctx, PS2Runtime *runtime)
    {
        TODO_NAMED("sceMpegGetPictureRAW8", rdram, ctx, runtime);
    }''','''    void sceMpegGetPicture(uint8_t *rdram,R5900Context *ctx,PS2Runtime *runtime) {
        decompMpegPicture(rdram,ctx,runtime,0);
    }
    void sceMpegGetPictureRAW8(uint8_t *rdram,R5900Context *ctx,PS2Runtime *runtime) {
        decompMpegPicture(rdram,ctx,runtime,1);
    }''')
    replace(source,'''    void sceMpegGetPictureRAW8xy(uint8_t *rdram, R5900Context *ctx, PS2Runtime *runtime)
    {
        TODO_NAMED("sceMpegGetPictureRAW8xy", rdram, ctx, runtime);
    }''','''    void sceMpegGetPictureRAW8xy(uint8_t *rdram,R5900Context *ctx,PS2Runtime *runtime) {
        decompMpegPicture(rdram,ctx,runtime,2);
    }''')
