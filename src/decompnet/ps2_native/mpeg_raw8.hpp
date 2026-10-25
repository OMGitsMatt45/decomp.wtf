// SPDX-License-Identifier: MIT
// PS2 IPU RAW8: column-major macroblocks, each Y[16][16], Cb[8][8], Cr[8][8].
// The xy API supplies the destination stride in macroblocks, not pixel bytes.
static void decompWriteRaw8(uint8_t *ram,uint32_t destination,const MpegDecodedFrame &frame,
                           uint32_t size,uint32_t height,bool xy) {
    const unsigned w=frame.width,h=frame.height,cw=(w+1)/2,ch=(h+1)/2;
    const unsigned columns=(w+15)/16,rows=(h+15)/16;
    if(!ram||!w||!h||frame.yuv420.size()!=size_t(w)*h+2ull*cw*ch)
        throw std::runtime_error("MPEG RAW8 has no decoded YUV picture");
    const unsigned stride=xy?height:rows;
    const uint64_t capacity=xy?uint64_t(size)*height:size;
    const uint32_t address=destination&0x1fffffffu;
    if(!destination||size>0x100000u||height>0x100000u||
       (xy&&(size<columns||height<rows))||(!xy&&size<uint64_t(columns)*rows)||
       capacity*384>PS2_RAM_SIZE||address>PS2_RAM_SIZE-capacity*384)
        throw std::runtime_error("MPEG RAW8 output buffer is too small or outside guest RAM");
    for(unsigned x=0;x<columns;++x)for(unsigned y=0;y<rows;++y){
        auto *out=ram+address+(uint64_t(x)*stride+y)*384;
        for(unsigned plane=0;plane<3;++plane){
            const unsigned edge=plane?8:16,pw=plane?cw:w,ph=plane?ch:h;
            const size_t base=plane?size_t(w)*h+(plane-1)*size_t(cw)*ch:0;
            for(unsigned py=0;py<edge;++py)for(unsigned px=0;px<edge;++px)
                *out++=frame.yuv420[base+size_t(std::min(y*edge+py,ph-1))*pw+std::min(x*edge+px,pw-1)];
        }
    }
}
