#version 330 core
// Raw scanline hardware state -> GPU pixels. No CPU framebuffer is sampled.
uniform usampler2D memory_image;
uniform vec2 viewport_size;
uniform vec2 viewport_origin;
out vec4 output_color;
const int ROW_WORDS=902;
const int META_WORDS=160*ROW_WORDS;
int row;
uint raw(int index) { return texelFetch(memory_image,ivec2(index&1023,index>>10),0).r; }
int byte_at(int address) { return int((raw(address>>2)>>uint((address&3)*8))&255u); }
int half_at(int address) { return byte_at(address)|(byte_at(address+1)<<8); }
int reg(int address) { return half_at(row*ROW_WORDS*4+address); }
int signed_reg(int address) { return (reg(address)<<16)>>16; }
int pal(int index) { return half_at(row*ROW_WORDS*4+1024+index*2)&32767; }
int oam(int address) { return half_at(row*ROW_WORDS*4+2048+address); }
int signed_oam(int address) { return (oam(address)<<16)>>16; }
int vr(int address) { return byte_at((META_WORDS+int(raw(row*ROW_WORDS+772)))*4+address); }
int vh(int address) { return vr(address)|(vr(address+1)<<8); }
int reference(int index) { return int(raw(row*ROW_WORDS+768+index)); }
const int TRANSPARENT=32768;

int text_bg(int bg,int x,int y) {
    int cnt=reg(8+bg*2), width=(cnt&16384)!=0?512:256, height=(cnt&32768)!=0?512:256;
    if((cnt&64)!=0) { x-=x%((reg(76)&15)+1); y-=y%(((reg(76)>>4)&15)+1); }
    int px=(x+(reg(16+4*bg)&511))&(width-1), py=(y+(reg(18+4*bg)&511))&(height-1);
    int entry_addr=((cnt>>8)&31)*2048+((px>>8)+(py>>8)*(width>>8))*2048+((py&255)>>3)*64+((px&255)>>3)*2;
    if(entry_addr>=65536)return TRANSPARENT;
    int entry=vh(entry_addr), tx=px&7, ty=py&7;
    if((entry&1024)!=0)tx=7-tx;
    if((entry&2048)!=0)ty=7-ty;
    int char_base=((cnt>>2)&3)*16384, tile=entry&1023, address, index;
    if((cnt&128)!=0) {
        address=char_base+tile*64+ty*8+tx;
        if(address>=65536)return TRANSPARENT;
        index=vr(address);return index==0?TRANSPARENT:pal(index);
    }
    address=char_base+tile*32+ty*4+tx/2;
    if(address>=65536)return TRANSPARENT;
    index=(vr(address)>>((tx&1)*4))&15;
    return index==0?TRANSPARENT:pal((entry>>12)*16+index);
}

ivec2 affine_xy(int bg,int x,int y) {
    int i=bg-2, cnt=reg(8+bg*2), params=32+16*i;
    int x0=reference(i*2), y0=reference(i*2+1);
    if((cnt&64)!=0) {
        int back=y%(((reg(76)>>4)&15)+1);
        x0-=back*signed_reg(params+2);y0-=back*signed_reg(params+6);
        x-=x%((reg(76)&15)+1);
    }
    return ivec2((x0+signed_reg(params)*x)>>8,(y0+signed_reg(params+4)*x)>>8);
}
int affine_bg(int bg,int x,int y) {
    int cnt=reg(8+2*bg), size=128<<((cnt>>14)&3);
    ivec2 p=affine_xy(bg,x,y);
    if((cnt&8192)!=0)p&=ivec2(size-1);
    else if(p.x<0||p.y<0||p.x>=size||p.y>=size)return TRANSPARENT;
    int map=((cnt>>8)&31)*2048+(p.y>>3)*(size>>3)+(p.x>>3);
    if(map>=65536)return TRANSPARENT;
    int address=((cnt>>2)&3)*16384+vr(map)*64+(p.y&7)*8+(p.x&7);
    if(address>=65536)return TRANSPARENT;
    int index=vr(address);return index==0?TRANSPARENT:pal(index);
}
int bitmap_bg(int mode,int x,int y) {
    ivec2 p=affine_xy(2,x,y);
    int width=mode==5?160:240, height=mode==5?128:160;
    if(p.x<0||p.y<0||p.x>=width||p.y>=height)return TRANSPARENT;
    int page=(mode!=3&&(reg(0)&16)!=0)?40960:0, pixel=p.y*width+p.x;
    if(mode==4) { int index=vr(page+pixel);return index==0?TRANSPARENT:pal(index); }
    return vh(page+pixel*2)&32767;
}

// Return the best OBJ pixel plus priority, semitransparency and OBJ-window mask.
ivec4 sprite(int x,int y) {
    int display=reg(0), mosaic=reg(76), color=TRANSPARENT, priority=4, semi=0, window=0;
    const ivec2 sizes[12]=ivec2[12](ivec2(8,8),ivec2(16,16),ivec2(32,32),ivec2(64,64),
        ivec2(16,8),ivec2(32,8),ivec2(32,16),ivec2(64,32),
        ivec2(8,16),ivec2(8,32),ivec2(16,32),ivec2(32,64));
    int count=int(raw(row*ROW_WORDS+773));
    for(int i=0;i<count;++i) {
        int n=int(raw(row*ROW_WORDS+774+i)), a0=oam(n*8), a1=oam(n*8+2), a2=oam(n*8+4);
        bool affine=(a0&256)!=0, doubled=affine&&(a0&512)!=0;
        ivec2 size=sizes[(a0>>14)*4+(a1>>14)], bounds=doubled?size*2:size;
        int top=a0&255, dy=(y-top)&255, left=a1&511;
        if(left>=240)left-=512;
        int local=x-left;if(local<0||local>=bounds.x)continue;
        if((display&7)>=3&&(a2&1023)<512)continue;
        if((a0&4096)!=0) {
            local=max(0,x-x%(((mosaic>>8)&15)+1)-left);
            dy=((y-y%(((mosaic>>12)&15)+1))-top)&255;
            if(dy>=bounds.y)dy=0;
        }
        int tx,ty;
        if(affine) {
            int group=((a1>>9)&31)*32,lx=local-bounds.x/2,ly=dy-bounds.y/2;
            tx=((signed_oam(group+6)*lx+signed_oam(group+14)*ly)>>8)+size.x/2;
            ty=((signed_oam(group+22)*lx+signed_oam(group+30)*ly)>>8)+size.y/2;
            if(tx<0||ty<0||tx>=size.x||ty>=size.y)continue;
        } else { tx=(a1&4096)!=0?size.x-1-local:local;ty=(a1&8192)!=0?size.y-1-dy:dy; }
        bool color256=(a0&8192)!=0, one_d=(display&64)!=0;
        int row_tiles=one_d?(size.x/8)*(color256?2:1):32, tile=a2&1023,index;
        if(color256) {
            int base=one_d?tile:(tile&~1), t=base+(ty>>3)*row_tiles+(tx>>3)*2;
            index=vr(65536+((t*32+(ty&7)*8+(tx&7))&32767));
        } else {
            int t=tile+(ty>>3)*row_tiles+(tx>>3);
            index=(vr(65536+((t*32+(ty&7)*4+(tx&7)/2)&32767))>>((tx&1)*4))&15;
            if(index!=0)index+=(a2>>12)*16;
        }
        if(index==0)continue;
        int obj_mode=(a0>>10)&3;
        if(obj_mode==2) { window=1;continue; }
        int p=(a2>>10)&3;
        if(p<priority) { color=pal(256+index);priority=p;semi=obj_mode==1?1:0; }
    }
    return ivec4(color,priority,semi,window);
}
bool span_contains(int value,int p,int limit) {
    int lo=value>>8, hi=value&255;
    if(hi>limit||lo>hi)hi=limit;
    return p>=lo&&p<hi;
}
int blend(int a,int b,int eva,int evb) {
    int result=0;for(int s=0;s<15;s+=5)result|=min(31,((((a>>s)&31)*eva+((b>>s)&31)*evb)>>4))<<s;
    return result;
}
int pixel(int x,int y) {
    int display=reg(0),mode=display&7;
    if((display&128)!=0)return 32767;
    int backgrounds[4]=int[4](TRANSPARENT,TRANSPARENT,TRANSPARENT,TRANSPARENT);
    for(int bg=0;bg<4;++bg)if((display&(256<<bg))!=0) {
        if(mode==0||(mode==1&&bg<2))backgrounds[bg]=text_bg(bg,x,y);
        else if((mode==1&&bg==2)||(mode==2&&bg>=2))backgrounds[bg]=affine_bg(bg,x,y);
        else if(mode>=3&&mode<=5&&bg==2)backgrounds[bg]=bitmap_bg(mode,x,y);
    }
    ivec4 obj=ivec4(TRANSPARENT,4,0,0);
    if((display&4096)!=0)obj=sprite(x,y);
    int enable=63;
    if((display&57344)!=0) {
        if((display&8192)!=0&&span_contains(reg(68),y,160)&&span_contains(reg(64),x,240))enable=reg(72)&63;
        else if((display&16384)!=0&&span_contains(reg(70),y,160)&&span_contains(reg(66),x,240))enable=(reg(72)>>8)&63;
        else if((display&32768)!=0&&obj.w!=0)enable=(reg(74)>>8)&63;
        else enable=reg(74)&63;
    }
    int layers[2]=int[2](5,5), colors[2]=int[2](pal(0),pal(0)), found=0;
    for(int p=0;p<4&&found<2;++p) {
        if((enable&16)!=0&&obj.x!=TRANSPARENT&&obj.y==p) { layers[found]=4;colors[found]=obj.x;++found; }
        for(int bg=0;bg<4&&found<2;++bg)if((reg(8+bg*2)&3)==p&&(enable&(1<<bg))!=0&&backgrounds[bg]!=TRANSPARENT) {
            layers[found]=bg;colors[found]=backgrounds[bg];++found;
        }
    }
    int result=colors[0], bld=reg(80), effect=(bld>>6)&3;
    if((enable&32)!=0) {
        bool second=((bld>>(8+layers[1]))&1)!=0;
        if((layers[0]==4&&obj.z!=0&&second)||(effect==1&&((bld>>layers[0])&1)!=0&&second))
            result=blend(colors[0],colors[1],min(reg(82)&31,16),min((reg(82)>>8)&31,16));
        else if(((bld>>layers[0])&1)!=0&&(effect==2||effect==3)) {
            int evy=min(reg(84)&31,16);result=0;
            for(int s=0;s<15;s+=5) { int c=(colors[0]>>s)&31;result|=(effect==2?c+(((31-c)*evy)>>4):c-((c*evy)>>4))<<s; }
        }
    }
    return result;
}
void main() {
    ivec2 f=ivec2(gl_FragCoord.xy-viewport_origin), size=ivec2(viewport_size);
    // Integer pixel centers keep odd-size scaling exact at source-pixel boundaries.
    ivec2 p=ivec2((2*f.x+1)*240/(2*size.x),(2*(size.y-1-f.y)+1)*160/(2*size.y));
    row=clamp(p.y,0,159);p.x=clamp(p.x,0,239);
    int color=pixel(p.x,p.y);
    if((reg(0)&128)==0&&(reg(2)&1)!=0)color=(color&~992)|(pixel(p.x^1,p.y)&992);
    ivec3 rgb=ivec3(color&31,(color>>5)&31,(color>>10)&31);
    rgb=(rgb<<3)|(rgb>>2);
    output_color=vec4(vec3(rgb)/255.0,1.0);
}
