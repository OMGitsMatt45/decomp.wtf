// SPDX-License-Identifier: MIT
#include "video.hpp"
#include "anygba/system.hpp"
#include "ppu_shader.hpp"
#include "save/save.h"
#include <SDL3/SDL.h>
#include <SDL3/SDL_opengl.h>
#define SDL_MAIN_HANDLED
#include <SDL3/SDL_main.h>
#include <algorithm>
#include <chrono>
#include <cstring>
#include <fstream>
#include <iostream>
#include <thread>

namespace gba_video {
void Scene::bitmap(std::span<const uint16_t> pixels){
    if(pixels.size()!=240*160)throw std::runtime_error("invalid menu bitmap size");
    rows.fill(0);vram.assign(96*1024/4,0);std::memcpy(vram.data(),pixels.data(),pixels.size_bytes());
    for(unsigned y=0;y<160;++y){auto* row=rows.data()+y*row_words;row[0]=0x0403;row[8]=0x00000100;row[9]=0x01000000;row[769]=y<<8;}
}
void Scene::capture(anygba::System& system,unsigned line) {
    if(line>=160)throw std::runtime_error("invalid GBA scanline");
    if(line==0){vram.clear();generation=~uint64_t{0};}
    const auto& m=system.memory();
    if(system.vram_writes()!=generation) {
        generation=system.vram_writes();vram_offset=uint32_t(vram.size());
        vram.resize(vram.size()+m.vram.size()/4);
        std::memcpy(vram.data()+vram_offset,m.vram.data(),m.vram.size());
    }
    auto* row=rows.data()+line*row_words;
    std::memcpy(row,m.io.data(),1024);std::memcpy(row+256,m.palette.data(),1024);
    std::memcpy(row+512,m.oam.data(),1024);
    const auto references=system.affine_reference();std::memcpy(row+768,references.data(),16);
    row[772]=vram_offset;row[773]=0;
    auto half=[&](unsigned a){return unsigned(m.oam[a])|(unsigned(m.oam[a+1])<<8);};
    const unsigned display=system.io_read16(0);
    if(!(display&0x1000))return;
    constexpr unsigned sizes[3][4][2]={{{8,8},{16,16},{32,32},{64,64}},{{16,8},{32,8},{32,16},{64,32}},{{8,16},{8,32},{16,32},{32,64}}};
    int budget=(display&32)?954:1210;
    for(unsigned n=0;n<128;++n) {
        const unsigned a0=half(n*8),a1=half(n*8+2),shape=a0>>14;
        const bool affine=a0&256;
        if((!affine&&(a0&512))||shape==3||((a0>>10)&3)==3)continue;
        int w=int(sizes[shape][a1>>14][0]),h=int(sizes[shape][a1>>14][1]);
        if(affine&&(a0&512)){w*=2;h*=2;}
        if(int((line-(a0&255))&255)>=h)continue;
        const int cost=affine?10+w*2:w;if(cost>budget)break;budget-=cost;
        int left=int(a1&511);if(left>=240)left-=512;
        if(left+w<=0)continue;
        row[774+row[773]++]=n;
    }
}
namespace {
void check(bool success,const std::string& text){if(!success)throw std::runtime_error(text);}

Graphics load_graphics(const std::filesystem::path& path) {
    if(path.empty())return {};
    std::ifstream file(path,std::ios::binary);
    if(!file)return {};
    char bytes[4]{};
    if(!file.read(bytes,sizeof(bytes)) || bytes[0]<'0' || bytes[0]>'2' || bytes[1]!=' ' ||
       bytes[2]<'0' || bytes[2]>'1' || bytes[3]!='\n' || file.peek()!=std::char_traits<char>::eof()) {
        std::cerr<<"Invalid graphics preferences, using Original settings\n";
        return {};
    }
    return {static_cast<Scaling>(bytes[0]-'0'),static_cast<Colors>(bytes[2]-'0')};
}

std::array<uint8_t,3> display_rgb(uint16_t pixel, Colors colors) {
    const auto expand=[](unsigned value){return (value<<3)|(value>>2);};
    const auto r=expand(pixel&31),g=expand((pixel>>5)&31),b=expand((pixel>>10)&31);
    if(colors==Colors::Soft) {
        // Mild channel mixing with a neutral gray axis. See the PPU shader.
        return {uint8_t((12*r+3*g+b+8)/16),uint8_t((2*r+13*g+b+8)/16),uint8_t((2*r+3*g+11*b+8)/16)};
    }
    return {uint8_t(r),uint8_t(g),uint8_t(b)};
}
#define GL_FUNCTIONS(X) \
 X(const GLubyte*,GetString,(GLenum)) X(GLenum,GetError,()) X(void,GetIntegerv,(GLenum,GLint*)) \
 X(void,Viewport,(GLint,GLint,GLsizei,GLsizei)) X(void,ClearColor,(GLfloat,GLfloat,GLfloat,GLfloat)) \
 X(void,Clear,(GLbitfield)) X(void,Disable,(GLenum)) X(void,PixelStorei,(GLenum,GLint)) \
 X(void,ReadPixels,(GLint,GLint,GLsizei,GLsizei,GLenum,GLenum,void*)) \
 X(GLuint,CreateShader,(GLenum)) X(void,ShaderSource,(GLuint,GLsizei,const GLchar* const*,const GLint*)) \
 X(void,CompileShader,(GLuint)) X(void,GetShaderiv,(GLuint,GLenum,GLint*)) X(void,GetShaderInfoLog,(GLuint,GLsizei,GLsizei*,GLchar*)) X(void,DeleteShader,(GLuint)) \
 X(GLuint,CreateProgram,()) X(void,AttachShader,(GLuint,GLuint)) X(void,LinkProgram,(GLuint)) X(void,GetProgramiv,(GLuint,GLenum,GLint*)) \
 X(void,GetProgramInfoLog,(GLuint,GLsizei,GLsizei*,GLchar*)) X(void,DeleteProgram,(GLuint)) X(void,UseProgram,(GLuint)) \
 X(GLint,GetUniformLocation,(GLuint,const GLchar*)) X(void,Uniform1i,(GLint,GLint)) X(void,Uniform2f,(GLint,GLfloat,GLfloat)) \
 X(void,GenVertexArrays,(GLsizei,GLuint*)) X(void,BindVertexArray,(GLuint)) X(void,DeleteVertexArrays,(GLsizei,const GLuint*)) \
 X(void,GenTextures,(GLsizei,GLuint*)) X(void,BindTexture,(GLenum,GLuint)) X(void,DeleteTextures,(GLsizei,const GLuint*)) \
 X(void,TexParameteri,(GLenum,GLenum,GLint)) X(void,TexImage2D,(GLenum,GLint,GLint,GLsizei,GLsizei,GLint,GLenum,GLenum,const void*)) \
 X(void,GenFramebuffers,(GLsizei,GLuint*)) X(void,DeleteFramebuffers,(GLsizei,const GLuint*)) \
 X(void,BindFramebuffer,(GLenum,GLuint)) X(GLenum,CheckFramebufferStatus,(GLenum)) \
 X(void,FramebufferTexture2D,(GLenum,GLenum,GLenum,GLuint,GLint)) \
 X(void,BlitFramebuffer,(GLint,GLint,GLint,GLint,GLint,GLint,GLint,GLint,GLbitfield,GLenum)) \
 X(void,DrawArrays,(GLenum,GLint,GLsizei))
struct GL {
#define DECLARE(result,name,args) using name##Fn=result(APIENTRY*)args;name##Fn name=nullptr;
    GL_FUNCTIONS(DECLARE)
#undef DECLARE
    GL(){
#define LOAD(result,name,args) name=reinterpret_cast<name##Fn>(SDL_GL_GetProcAddress("gl" #name));check(name!=nullptr,"missing OpenGL function gl" #name);
        GL_FUNCTIONS(LOAD)
#undef LOAD
    }
    GLuint shader(GLenum kind,const char* text) {
        auto id=CreateShader(kind);ShaderSource(id,1,&text,nullptr);CompileShader(id);
        GLint ok=0;GetShaderiv(id,GL_COMPILE_STATUS,&ok);
        if(!ok){char message[4096]{};GetShaderInfoLog(id,sizeof(message),nullptr,message);DeleteShader(id);throw std::runtime_error(message);}
        return id;
    }
    GLuint program() {
        const char* vertex="#version 330 core\nvoid main(){vec2 p=vec2((gl_VertexID<<1)&2,gl_VertexID&2);gl_Position=vec4(p*2.0-1.0,0,1);}";
        GLuint vs=shader(GL_VERTEX_SHADER,vertex),fs=0,id=0;
        try {fs=shader(GL_FRAGMENT_SHADER,gba_ppu_shader);id=CreateProgram();AttachShader(id,vs);AttachShader(id,fs);LinkProgram(id);
            GLint ok=0;GetProgramiv(id,GL_LINK_STATUS,&ok);if(!ok){char text[4096]{};GetProgramInfoLog(id,sizeof(text),nullptr,text);throw std::runtime_error(text);}
        }catch(...){DeleteShader(vs);if(fs)DeleteShader(fs);if(id)DeleteProgram(id);throw;}
        DeleteShader(vs);DeleteShader(fs);return id;
    }
};
}
struct Display::Impl {
    Options options;
    std::unique_ptr<Scene> bitmap_scene;
    SDL_Window* window=nullptr;SDL_GLContext context=nullptr;
    SDL_Renderer* software=nullptr;SDL_Texture* software_texture=nullptr;
    SDL_AudioStream* sound=nullptr;SDL_Gamepad* pad=nullptr;
    std::unique_ptr<GL> gl;
    GLuint program=0,texture=0,array=0,smooth_framebuffer=0,smooth_texture=0;
    Graphics graphics;
    int width=0,height=0;
    std::string renderer_name,device_name;
    std::vector<uint32_t> upload;
    std::vector<uint8_t> pixels;
    std::chrono::steady_clock::time_point deadline=std::chrono::steady_clock::now();
    ~Impl(){
        if(sound)SDL_DestroyAudioStream(sound);
        if(pad)SDL_CloseGamepad(pad);
        close_video();SDL_Quit();
    }
    void close_video(){
        if(context)SDL_GL_MakeCurrent(window,context);
        if(gl){
            if(program)gl->DeleteProgram(program);
            if(texture)gl->DeleteTextures(1,&texture);
            if(array)gl->DeleteVertexArrays(1,&array);
            if(smooth_framebuffer)gl->DeleteFramebuffers(1,&smooth_framebuffer);
            if(smooth_texture)gl->DeleteTextures(1,&smooth_texture);
        }
        gl.reset();program=texture=array=smooth_framebuffer=smooth_texture=0;
        if(context)SDL_GL_DestroyContext(context);context=nullptr;
        if(software_texture)SDL_DestroyTexture(software_texture);software_texture=nullptr;
        if(software)SDL_DestroyRenderer(software);software=nullptr;
        if(window)SDL_DestroyWindow(window);window=nullptr;
    }
    void open_window(bool gpu){
        float x=0,y=0;SDL_GetGlobalMouseState(&x,&y);SDL_Point point{int(x),int(y)};
        auto monitor=SDL_GetDisplayForPoint(&point);if(!monitor)monitor=SDL_GetPrimaryDisplay();
        SDL_Rect bounds{};
        int w=options.width,h=options.height;
        if(!w||!h){check(SDL_GetDisplayUsableBounds(monitor,&bounds),SDL_GetError());w=std::max(240,bounds.w*4/5);h=std::max(160,bounds.h*4/5);}
        SDL_WindowFlags flags=SDL_WINDOW_RESIZABLE|SDL_WINDOW_HIGH_PIXEL_DENSITY;
        if(gpu)flags|=SDL_WINDOW_OPENGL;
        if(options.hidden)flags|=SDL_WINDOW_HIDDEN;
#ifdef _WIN32
        window=SDL_CreateWindow("GBA native PC — F1/Esc: Settings",w,h,flags);
#else
        window=SDL_CreateWindow("GBA native PC",w,h,flags);
#endif
        check(window,SDL_GetError());
        check(SDL_SetWindowPosition(window,SDL_WINDOWPOS_CENTERED_DISPLAY(monitor),SDL_WINDOWPOS_CENTERED_DISPLAY(monitor)),SDL_GetError());
        if(options.fullscreen)check(SDL_SetWindowFullscreen(window,true),SDL_GetError());
    }
    void init(Options value){
        options=std::move(value);
        graphics=load_graphics(options.graphics_path);
        check(options.renderer=="auto"||options.renderer=="opengl"||options.renderer=="software","invalid renderer");
        SDL_SetMainReady();check(SDL_Init(SDL_INIT_VIDEO|SDL_INIT_AUDIO|SDL_INIT_GAMEPAD),SDL_GetError());
        if(options.renderer!="software")try{
            SDL_GL_SetAttribute(SDL_GL_CONTEXT_MAJOR_VERSION,3);SDL_GL_SetAttribute(SDL_GL_CONTEXT_MINOR_VERSION,3);
            SDL_GL_SetAttribute(SDL_GL_CONTEXT_PROFILE_MASK,SDL_GL_CONTEXT_PROFILE_CORE);
            SDL_GL_SetAttribute(SDL_GL_DOUBLEBUFFER,1);SDL_GL_SetAttribute(SDL_GL_MULTISAMPLEBUFFERS,0);
            open_window(true);context=SDL_GL_CreateContext(window);check(context,SDL_GetError());
            gl=std::make_unique<GL>();program=gl->program();
            gl->GenVertexArrays(1,&array);gl->BindVertexArray(array);gl->GenTextures(1,&texture);
            gl->BindTexture(GL_TEXTURE_2D,texture);gl->TexParameteri(GL_TEXTURE_2D,GL_TEXTURE_MIN_FILTER,GL_NEAREST);
            gl->TexParameteri(GL_TEXTURE_2D,GL_TEXTURE_MAG_FILTER,GL_NEAREST);
            gl->GenTextures(1,&smooth_texture);
            gl->BindTexture(GL_TEXTURE_2D,smooth_texture);
            gl->TexImage2D(GL_TEXTURE_2D,0,GL_RGBA8,240,160,0,GL_RGBA,GL_UNSIGNED_BYTE,nullptr);
            gl->GenFramebuffers(1,&smooth_framebuffer);
            gl->BindFramebuffer(GL_FRAMEBUFFER,smooth_framebuffer);
            gl->FramebufferTexture2D(GL_FRAMEBUFFER,GL_COLOR_ATTACHMENT0,GL_TEXTURE_2D,smooth_texture,0);
            check(gl->CheckFramebufferStatus(GL_FRAMEBUFFER)==GL_FRAMEBUFFER_COMPLETE,"cannot create GBA smoothing framebuffer");
            gl->BindFramebuffer(GL_FRAMEBUFFER,0);
            gl->Disable(GL_DITHER);gl->Disable(GL_BLEND);gl->Disable(GL_FRAMEBUFFER_SRGB);
            SDL_GL_SetSwapInterval(0);renderer_name="opengl";
            device_name=reinterpret_cast<const char*>(gl->GetString(GL_RENDERER));
        }catch(const std::exception& e){
            close_video();if(options.renderer=="opengl")throw;
            std::cerr<<"OpenGL unavailable; using software rendering: "<<e.what()<<'\n';
        }
        if(!gl){open_window(false);software=SDL_CreateRenderer(window,"software");check(software,SDL_GetError());
            software_texture=SDL_CreateTexture(software,SDL_PIXELFORMAT_RGBA32,SDL_TEXTUREACCESS_STREAMING,240,160);
            check(software_texture,SDL_GetError());SDL_SetTextureScaleMode(software_texture,SDL_SCALEMODE_NEAREST);
            renderer_name="software";device_name=SDL_GetRendererName(software);}
        SDL_AudioSpec spec{};spec.format=SDL_AUDIO_S16;spec.channels=2;spec.freq=32768;
        sound=SDL_OpenAudioDeviceStream(SDL_AUDIO_DEVICE_DEFAULT_PLAYBACK,&spec,nullptr,nullptr);
        if(sound)SDL_ResumeAudioStreamDevice(sound);else std::cerr<<"Audio device unavailable: "<<SDL_GetError()<<'\n';
        int count=0;auto* ids=SDL_GetGamepads(&count);if(count)pad=SDL_OpenGamepad(ids[0]);SDL_free(ids);
    }
};
Display::Display(Options options):p(std::make_unique<Impl>()){p->init(std::move(options));}
Display::~Display()=default;
bool Display::poll(uint16_t& keys,bool* settings,bool* cheat_button,bool* advanced){
    SDL_Event event;while(SDL_PollEvent(&event)) {
        if(event.type==SDL_EVENT_QUIT||event.type==SDL_EVENT_WINDOW_CLOSE_REQUESTED)return false;
        if(event.type==SDL_EVENT_KEY_DOWN&&!event.key.repeat&&event.key.scancode==SDL_SCANCODE_F11)
            toggle_fullscreen();
        if(advanced&&event.type==SDL_EVENT_KEY_DOWN&&!event.key.repeat&&event.key.scancode==SDL_SCANCODE_F2)*advanced=true;
        if(settings&&event.type==SDL_EVENT_KEY_DOWN&&!event.key.repeat&&
           (event.key.scancode==SDL_SCANCODE_F1||event.key.scancode==SDL_SCANCODE_ESCAPE))*settings=true;
        if(event.type==SDL_EVENT_GAMEPAD_ADDED&&!p->pad)p->pad=SDL_OpenGamepad(event.gdevice.which);
        if(event.type==SDL_EVENT_GAMEPAD_REMOVED&&p->pad&&SDL_GetGamepadID(p->pad)==event.gdevice.which){SDL_CloseGamepad(p->pad);p->pad=nullptr;}
    }
    keys=0;
    if(cheat_button)*cheat_button=SDL_GetKeyboardFocus()==p->window&&SDL_GetKeyboardState(nullptr)[SDL_SCANCODE_F12];
    if(SDL_GetKeyboardFocus()==p->window){const auto* k=SDL_GetKeyboardState(nullptr);
        const SDL_Scancode sc[]={SDL_SCANCODE_X,SDL_SCANCODE_Z,SDL_SCANCODE_BACKSPACE,SDL_SCANCODE_RETURN,
            SDL_SCANCODE_RIGHT,SDL_SCANCODE_LEFT,SDL_SCANCODE_UP,SDL_SCANCODE_DOWN,SDL_SCANCODE_W,SDL_SCANCODE_Q};
        for(int i=0;i<10;++i)if(k[sc[i]])keys|=uint16_t(1u<<i);}
    if(p->pad){const SDL_GamepadButton buttons[]={SDL_GAMEPAD_BUTTON_SOUTH,SDL_GAMEPAD_BUTTON_EAST,SDL_GAMEPAD_BUTTON_BACK,SDL_GAMEPAD_BUTTON_START,
            SDL_GAMEPAD_BUTTON_DPAD_RIGHT,SDL_GAMEPAD_BUTTON_DPAD_LEFT,SDL_GAMEPAD_BUTTON_DPAD_UP,SDL_GAMEPAD_BUTTON_DPAD_DOWN,
            SDL_GAMEPAD_BUTTON_RIGHT_SHOULDER,SDL_GAMEPAD_BUTTON_LEFT_SHOULDER};
        for(int i=0;i<10;++i)if(SDL_GetGamepadButton(p->pad,buttons[i]))keys|=uint16_t(1u<<i);}
    return true;
}
void Display::present(const Scene& scene,std::span<const uint16_t> frame){
    present_frame(scene,frame,true);
}
void Display::present_frame(const Scene& scene,std::span<const uint16_t> frame,bool game_image){
    check(SDL_GetWindowSizeInPixels(p->window,&p->width,&p->height),SDL_GetError());
    if(p->width<=0||p->height<=0)return;
    int w=p->width,h=w*2/3;if(h>p->height){h=p->height;w=h*3/2;}
    w=std::max(w,1);h=std::max(h,1);
    if(p->graphics.scaling==Scaling::Sharp) {
        const int scale=std::min(p->width/240,p->height/160);
        if(scale>0){w=240*scale;h=160*scale;}
    }
    const bool smooth=game_image&&p->graphics.scaling==Scaling::Smooth;
    const auto colors=game_image?p->graphics.colors:Colors::Original;
    if(p->gl){auto& g=*p->gl;
        p->upload.assign(scene.rows.begin(),scene.rows.end());p->upload.insert(p->upload.end(),scene.vram.begin(),scene.vram.end());
        const int rows=int((p->upload.size()+1023)/1024);p->upload.resize(size_t(rows)*1024);
        GLint limit=0;g.GetIntegerv(GL_MAX_TEXTURE_SIZE,&limit);check(rows<=limit&&limit>=1024,"GBA scanline snapshots exceed GPU texture capacity");
        g.BindTexture(GL_TEXTURE_2D,p->texture);g.PixelStorei(GL_UNPACK_ALIGNMENT,1);
        g.TexImage2D(GL_TEXTURE_2D,0,GL_R32UI,1024,rows,0,GL_RED_INTEGER,GL_UNSIGNED_INT,p->upload.data());
        g.Viewport(0,0,p->width,p->height);g.ClearColor(0,0,0,1);g.Clear(GL_COLOR_BUFFER_BIT);
        const int x=(p->width-w)/2,y=(p->height-h)/2;
        if(smooth){
            g.BindFramebuffer(GL_FRAMEBUFFER,p->smooth_framebuffer);
            g.Viewport(0,0,240,160);
        }else g.Viewport(x,y,w,h);
        g.UseProgram(p->program);g.Uniform1i(g.GetUniformLocation(p->program,"memory_image"),0);
        g.Uniform1i(g.GetUniformLocation(p->program,"soft_colors"),colors==Colors::Soft);
        g.Uniform2f(g.GetUniformLocation(p->program,"viewport_size"),float(smooth?240:w),float(smooth?160:h));
        g.Uniform2f(g.GetUniformLocation(p->program,"viewport_origin"),float(smooth?0:x),float(smooth?0:y));
        g.BindVertexArray(p->array);g.DrawArrays(GL_TRIANGLES,0,3);
        if(smooth){
            // Shade each source pixel once, then interpolate the resulting image.
            g.BindFramebuffer(GL_DRAW_FRAMEBUFFER,0);
            g.BlitFramebuffer(0,0,240,160,x,y,x+w,y+h,GL_COLOR_BUFFER_BIT,GL_LINEAR);
            g.BindFramebuffer(GL_READ_FRAMEBUFFER,0);
        }
        if(p->options.readback){p->pixels.resize(size_t(p->width)*p->height*3);std::vector<uint8_t> raw(p->pixels.size());
            g.PixelStorei(GL_PACK_ALIGNMENT,1);g.ReadPixels(0,0,p->width,p->height,GL_RGB,GL_UNSIGNED_BYTE,raw.data());
            for(int row=0;row<p->height;++row)std::memcpy(p->pixels.data()+size_t(row)*p->width*3,raw.data()+size_t(p->height-1-row)*p->width*3,size_t(p->width)*3);}
        check(g.GetError()==GL_NO_ERROR,"OpenGL GBA rendering failed");check(SDL_GL_SwapWindow(p->window),SDL_GetError());
    }else{
        std::vector<uint8_t> rgba(240*160*4);
        for(size_t i=0;i<frame.size();++i){
            const auto rgb=display_rgb(frame[i],colors);
            std::copy(rgb.begin(),rgb.end(),rgba.begin()+i*4);rgba[i*4+3]=255;
        }
        check(SDL_SetTextureScaleMode(p->software_texture,smooth?SDL_SCALEMODE_LINEAR:SDL_SCALEMODE_NEAREST),SDL_GetError());
        check(SDL_UpdateTexture(p->software_texture,nullptr,rgba.data(),240*4),SDL_GetError());
        SDL_SetRenderDrawColor(p->software,0,0,0,255);SDL_RenderClear(p->software);
        SDL_FRect dest{float((p->width-w)/2),float((p->height-h)/2),float(w),float(h)};
        check(SDL_RenderTexture(p->software,p->software_texture,nullptr,&dest),SDL_GetError());
        if(p->options.readback){auto* image=SDL_RenderReadPixels(p->software,nullptr);check(image,SDL_GetError());
            auto* rgb=SDL_ConvertSurface(image,SDL_PIXELFORMAT_RGB24);SDL_DestroySurface(image);check(rgb,SDL_GetError());
            p->pixels.resize(size_t(p->width)*p->height*3);for(int y=0;y<p->height;++y)std::memcpy(p->pixels.data()+size_t(y)*p->width*3,static_cast<uint8_t*>(rgb->pixels)+size_t(y)*rgb->pitch,size_t(p->width)*3);SDL_DestroySurface(rgb);}
        check(SDL_RenderPresent(p->software),SDL_GetError());
    }
}
void Display::present_pixels(std::span<const uint16_t> pixels,bool game_image){
    if(!p->bitmap_scene)p->bitmap_scene=std::make_unique<Scene>();
    p->bitmap_scene->bitmap(pixels);present_frame(*p->bitmap_scene,pixels,game_image);
}
Graphics Display::graphics() const {return p->graphics;}
void Display::set_graphics(Graphics graphics) {
    if(!p->options.graphics_path.empty()) {
        const std::array<uint8_t,4> data{
            uint8_t('0'+static_cast<int>(graphics.scaling)), ' ',
            uint8_t('0'+static_cast<int>(graphics.colors)), '\n'};
        if(auto error=anygba::save::replace_file(p->options.graphics_path,data,false))
            throw std::runtime_error(*error);
    }
    p->graphics=graphics;
}
bool Display::fullscreen() const {return (SDL_GetWindowFlags(p->window)&SDL_WINDOW_FULLSCREEN)!=0;}
void Display::toggle_fullscreen() {check(SDL_SetWindowFullscreen(p->window,!fullscreen()),SDL_GetError());}
void Display::audio(std::span<const int16_t> samples,bool unpaced){
    if(!p->sound||unpaced)return;
    check(SDL_PutAudioStreamData(p->sound,samples.data(),int(samples.size_bytes())),SDL_GetError());
}
void Display::pace(){
    p->deadline+=std::chrono::duration_cast<std::chrono::steady_clock::duration>(std::chrono::duration<double>(1.0/anygba::kFramesPerSecond));
    auto now=std::chrono::steady_clock::now();if(p->deadline<now-std::chrono::milliseconds(250))p->deadline=now;
    std::this_thread::sleep_until(p->deadline);
}
void Display::resize(int width,int height){
    check(width>0&&height>0&&width<=16384&&height<=16384,"invalid window size");
    check(SDL_SetWindowSize(p->window,width,height),SDL_GetError());
    check(SDL_SyncWindow(p->window),SDL_GetError());SDL_PumpEvents();
    if(p->context)check(SDL_GL_MakeCurrent(p->window,p->context),SDL_GetError());
}
std::string Display::renderer()const{return p->renderer_name;}
std::string Display::device()const{return p->device_name;}
bool Display::audio_device()const{return p->sound!=nullptr;}
int Display::width()const{return p->width;}
int Display::height()const{return p->height;}
const std::vector<uint8_t>& Display::pixels()const{return p->pixels;}
void* Display::native_window()const{
#ifdef _WIN32
    return SDL_GetPointerProperty(SDL_GetWindowProperties(p->window),SDL_PROP_WINDOW_WIN32_HWND_POINTER,nullptr);
#else
    return nullptr;
#endif
}
void Display::pause(bool paused){
    if(p->sound){
        if(paused){SDL_PauseAudioStreamDevice(p->sound);SDL_ClearAudioStream(p->sound);}
        else SDL_ResumeAudioStreamDevice(p->sound);
    }
    p->deadline=std::chrono::steady_clock::now();
}
}
