// SPDX-License-Identifier: MIT. Original decomp.wtf SDL/OpenGL presentation.
#include "video.hpp"
#include <dsr/gpu2d.h>
#include "texture_rgba.h"
#include <SDL_opengl.h>
#include <SDL_opengl_glext.h>
#include <algorithm>
#include <cmath>
#include <cstring>
#include <iostream>
#include <map>
#include <stdexcept>

namespace video {
Scene Scene::capture(dsr::Machine& machine) {
    Scene scene;
    auto& gpu=machine.gpu3d();
    const auto geometry=gpu.geometry_view();const auto raster=gpu.raster_view();
    scene.generation=geometry.generation;scene.swap_mode=geometry.swap_mode;
    scene.vertices.assign(geometry.vertices,geometry.vertices+geometry.vertex_count);
    scene.polygons.assign(geometry.polygons,geometry.polygons+geometry.polygon_count);
    const auto order=gpu.draw_order_view();
    scene.order.assign(order.opaque,order.opaque+order.opaque_count);
    scene.order.insert(scene.order.end(),order.translucent,order.translucent+order.translucent_count);
    scene.control=raster.disp3d;scene.clear_color=raster.clear_color;
    scene.clear_depth=raster.clear_depth;scene.alpha_ref=raster.alpha_reference;
    if(raster.opaque_only_mask)std::copy_n(raster.opaque_only_mask,scene.safe.size(),scene.safe.begin());
    for(unsigned i=0;i<32;++i)scene.toon[i]=raster.toon_table[i*2]|(uint32_t(raster.toon_table[i*2+1])<<8);
    // These effects need additional GPU passes. Preserve the complete native
    // frame, including its UI, when they are active instead of dropping them.
    scene.supported=!(raster.disp3d&((1u<<5)|(1u<<7)|(1u<<14))) && !geometry.vertex_overflow && !geometry.polygon_overflow;
    dsr::gpu3d_detail::TextureSource source;
    source.context=&machine.gpu2d();
    source.texture_lookup=[](const void* p,int slot){return static_cast<const dsr::Gpu2D*>(p)->texture_slot(slot);};
    source.palette_lookup=[](const void* p,int slot){return static_cast<const dsr::Gpu2D*>(p)->texpal_slot(slot);};
    source.texture_read=[](const void* p,uint32_t a){return static_cast<const dsr::Gpu2D*>(p)->texture_byte(a);};
    source.palette_read=[](const void* p,uint32_t a){return static_cast<const dsr::Gpu2D*>(p)->texpal_byte(a);};
    std::map<std::pair<uint32_t,uint32_t>,bool> decoded;
    size_t texture_bytes=0;
    for(const auto& polygon:scene.polygons) {
        if(((polygon.attr>>4)&3)==3 || (polygon.attr&(1u<<14)))scene.supported=false;
        if(!(scene.control&1) || !((polygon.texture>>26)&7))continue;
        if(!decoded.emplace(std::pair{polygon.texture,polygon.palette},true).second)continue;
        texture_bytes+=size_t(8u<<((polygon.texture>>20)&7))*(8u<<((polygon.texture>>23)&7))*4;
        if(texture_bytes>64*1024*1024){scene.supported=false;break;}
        Texture texture;texture.param=polygon.texture;texture.palette=polygon.palette;
        dsr::gpu3d_detail::decode_texture_rgba8(source,texture.param,texture.palette,texture.rgba,texture.width,texture.height);
        scene.textures.push_back(std::move(texture));
    }
    return scene;
}

namespace {
void check(bool ok,const std::string& message){if(!ok)throw std::runtime_error(message);}
// Resolve every GL symbol through SDL, including the GL 1.x entry points.
// Windows' opengl32 exports only 1.1; no platform GL SDK/download is required.
#define GL_FUNCTIONS(X) \
 X(const GLubyte*,GetString,(GLenum)) X(GLenum,GetError,()) \
 X(void,Viewport,(GLint,GLint,GLsizei,GLsizei)) X(void,ClearColor,(GLfloat,GLfloat,GLfloat,GLfloat)) \
 X(void,ClearDepth,(GLdouble)) X(void,Clear,(GLbitfield)) X(void,Enable,(GLenum)) X(void,Disable,(GLenum)) \
 X(void,DepthFunc,(GLenum)) X(void,DepthMask,(GLboolean)) X(void,BlendFunc,(GLenum,GLenum)) \
 X(void,Scissor,(GLint,GLint,GLsizei,GLsizei)) \
 X(void,CullFace,(GLenum)) X(void,PolygonMode,(GLenum,GLenum)) X(void,PixelStorei,(GLenum,GLint)) \
 X(void,ReadPixels,(GLint,GLint,GLsizei,GLsizei,GLenum,GLenum,void*)) \
 X(GLuint,CreateShader,(GLenum)) X(void,ShaderSource,(GLuint,GLsizei,const GLchar* const*,const GLint*)) \
 X(void,CompileShader,(GLuint)) X(void,GetShaderiv,(GLuint,GLenum,GLint*)) \
 X(void,GetShaderInfoLog,(GLuint,GLsizei,GLsizei*,GLchar*)) X(void,DeleteShader,(GLuint)) \
 X(GLuint,CreateProgram,()) X(void,AttachShader,(GLuint,GLuint)) X(void,LinkProgram,(GLuint)) \
 X(void,GetProgramiv,(GLuint,GLenum,GLint*)) X(void,GetProgramInfoLog,(GLuint,GLsizei,GLsizei*,GLchar*)) \
 X(void,DeleteProgram,(GLuint)) X(void,UseProgram,(GLuint)) X(GLint,GetUniformLocation,(GLuint,const GLchar*)) \
 X(void,Uniform1i,(GLint,GLint)) X(void,Uniform1f,(GLint,GLfloat)) X(void,Uniform2f,(GLint,GLfloat,GLfloat)) \
 X(void,Uniform3fv,(GLint,GLsizei,const GLfloat*)) \
 X(void,GenVertexArrays,(GLsizei,GLuint*)) X(void,BindVertexArray,(GLuint)) X(void,DeleteVertexArrays,(GLsizei,const GLuint*)) \
 X(void,GenBuffers,(GLsizei,GLuint*)) X(void,BindBuffer,(GLenum,GLuint)) \
 X(void,BufferData,(GLenum,GLsizeiptr,const void*,GLenum)) X(void,DeleteBuffers,(GLsizei,const GLuint*)) \
 X(void,EnableVertexAttribArray,(GLuint)) X(void,VertexAttribPointer,(GLuint,GLint,GLenum,GLboolean,GLsizei,const void*)) \
 X(void,DrawArrays,(GLenum,GLint,GLsizei)) X(void,ActiveTexture,(GLenum)) \
 X(void,GenTextures,(GLsizei,GLuint*)) X(void,BindTexture,(GLenum,GLuint)) X(void,DeleteTextures,(GLsizei,const GLuint*)) \
 X(void,TexParameteri,(GLenum,GLenum,GLint)) X(void,TexImage2D,(GLenum,GLint,GLint,GLsizei,GLsizei,GLint,GLenum,GLenum,const void*))
struct GL {
#define DECLARE(result,name,args) using name##Fn=result(APIENTRY*)args;name##Fn name=nullptr;
    GL_FUNCTIONS(DECLARE)
#undef DECLARE
    GL(){
#define LOAD(result,name,args) name=reinterpret_cast<name##Fn>(SDL_GL_GetProcAddress("gl" #name));check(name!=nullptr,"OpenGL entry point unavailable: gl" #name);
        GL_FUNCTIONS(LOAD)
#undef LOAD
    }
    GLuint program(const char* vertex,const char* fragment) {
        auto compile=[&](GLenum kind,const char* source){
            const auto shader=CreateShader(kind);ShaderSource(shader,1,&source,nullptr);CompileShader(shader);
            GLint ok=0;GetShaderiv(shader,GL_COMPILE_STATUS,&ok);
            if(!ok){char log[4096]{};GetShaderInfoLog(shader,sizeof(log),nullptr,log);DeleteShader(shader);throw std::runtime_error(std::string("OpenGL shader: ")+log);}
            return shader;
        };
        const auto vs=compile(GL_VERTEX_SHADER,vertex);GLuint fs=0,result=0;
        try {
            fs=compile(GL_FRAGMENT_SHADER,fragment);result=CreateProgram();AttachShader(result,vs);AttachShader(result,fs);LinkProgram(result);
            GLint ok=0;GetProgramiv(result,GL_LINK_STATUS,&ok);
            if(!ok){char log[4096]{};GetProgramInfoLog(result,sizeof(log),nullptr,log);throw std::runtime_error(std::string("OpenGL link: ")+log);}
        } catch(...) {DeleteShader(vs);if(fs)DeleteShader(fs);if(result)DeleteProgram(result);throw;}
        DeleteShader(vs);DeleteShader(fs);return result;
    }
};
const char* scene_vertex=R"GLSL(#version 330 core
layout(location=0) in vec4 clip;
layout(location=1) in vec2 uv;
layout(location=2) in vec3 color;
uniform vec2 scale_xy,offset_xy;
out vec2 texcoord;out vec3 vertex_color;
void main(){gl_Position=vec4(clip.xy*scale_xy+clip.w*offset_xy,clip.zw);texcoord=uv;vertex_color=color;}
)GLSL";
const char* scene_fragment=R"GLSL(#version 330 core
in vec2 texcoord;in vec3 vertex_color;
out vec4 pixel;
uniform sampler2D image,mask_image;
uniform bool textured,masked,highlight,wbuffer;
uniform int mode,alpha,alpha_ref;
uniform vec2 mask_origin,mask_size;
uniform vec3 toon[32];
void main(){
 if(masked){vec2 p=(gl_FragCoord.xy-mask_origin)/mask_size;if(any(lessThan(p,vec2(0)))||any(greaterThanEqual(p,vec2(1))))discard;
   if(texture(mask_image,vec2(p.x,1-p.y)).r<0.5)discard;}
 vec3 v=floor(clamp(vertex_color,0,63)+0.5),t=vec3(63);float ta=31;
 if(textured){vec4 sample_color=texture(image,texcoord/vec2(textureSize(image,0)));t=floor(sample_color.rgb*63+0.5);ta=floor(sample_color.a*31+0.5);}
 vec3 shade=v;float a=float(alpha==0?31:alpha);
 if(mode==2)shade=highlight?vec3(v.r):toon[int(v.r)/2];
 if(mode==1 && textured)shade=ta==0?v:(ta==31?t:floor((t*ta+v*(31-ta))/32));
 else {shade=floor(((t+1)*(shade+1)-1)/64);if(mode==2&&highlight)shade=min(vec3(63),shade+toon[int(v.r)/2]);
   if(textured){float t6=ta==0?0:ta*2+1,a6=a==0?0:a*2+1;a=floor(floor(((t6+1)*(a6+1)-1)/64)/2);}}
 if(a==0 || a<float(alpha_ref))discard;
 pixel=vec4(floor(shade/2)/31,a/31);
 gl_FragDepth=wbuffer?clamp((1/gl_FragCoord.w)/4096,0,1):gl_FragCoord.z;
}
)GLSL";
const char* flat_vertex=R"GLSL(#version 330 core
layout(location=0) in vec4 vertex;out vec2 uv;
void main(){gl_Position=vec4(vertex.xy,0,1);uv=vertex.zw;}
)GLSL";
const char* flat_fragment=R"GLSL(#version 330 core
in vec2 uv;out vec4 pixel;uniform sampler2D image;
void main(){pixel=texture(image,uv);}
)GLSL";
struct Rect {float x=0,y=0,w=0,h=0;}; // Bottom-left drawable coordinates.
Rect fit(float width,float height,float aspect) {
    const float w=std::min(width,height*aspect),h=w/aspect;
    return {(width-w)/2,(height-h)/2,w,h};
}
}

struct Display::Impl {
    Options options;
    SDL_Window* window=nullptr;SDL_GLContext context=nullptr;
    SDL_Renderer* software=nullptr;SDL_Texture* software_texture=nullptr;
    std::unique_ptr<GL> gl;
    GLuint scene_program=0,flat_program=0,vao=0,vbo=0,screen_texture=0,mask_texture=0;
    std::map<std::pair<uint32_t,uint32_t>,GLuint> textures;
    std::string renderer_name="software",device_name;
    Scene unified_scene;
    std::array<uint32_t,256*192> unified_ui{};
    bool have_bottom=false,unified_active=false,unified_on_top=false,secondary_visible=true;
    Rect touch_rect;
    int width=0,height=0,display_index=0;
    uint64_t draws=0;
    std::vector<uint32_t> last_pixels;

    explicit Impl(Options value):options(std::move(value)) {
        try {
        check(options.renderer=="auto"||options.renderer=="opengl"||options.renderer=="software","renderer must be auto, opengl or software");
        check(options.screen_mode=="dual"||options.screen_mode=="unified","screen mode must be dual or unified");
        check(options.renderer!="software"||options.screen_mode!="unified","the unified camera requires OpenGL rendering");
        SDL_Point pointer{};SDL_GetGlobalMouseState(&pointer.x,&pointer.y);
        display_index=std::max(0,SDL_GetPointDisplayIndex(&pointer));
        if(options.width<=0||options.height<=0) {
            SDL_Rect usable{};
            if(SDL_GetDisplayUsableBounds(display_index,&usable)!=0)
                check(SDL_GetDisplayBounds(display_index,&usable)==0,SDL_GetError());
            options.width=std::max(1,usable.w*4/5);options.height=std::max(1,usable.h*4/5);
        }
        if(options.renderer!="software") {
            try {create_gl();}
            catch(const std::exception& error) {
                cleanup();
                if(options.renderer=="opengl"||options.screen_mode=="unified")throw;
                std::cerr<<"OpenGL unavailable; using software screens: "<<error.what()<<'\n';
            }
        }
        if(!window) {
            window=SDL_CreateWindow("DS PC project — software",SDL_WINDOWPOS_CENTERED_DISPLAY(display_index),SDL_WINDOWPOS_CENTERED_DISPLAY(display_index),
                options.width,options.height,SDL_WINDOW_RESIZABLE|SDL_WINDOW_ALLOW_HIGHDPI);
            if(window)software=SDL_CreateRenderer(window,-1,SDL_RENDERER_SOFTWARE);
            if(software)software_texture=SDL_CreateTexture(software,SDL_PIXELFORMAT_ARGB8888,SDL_TEXTUREACCESS_STREAMING,256,384);
            check(software_texture,SDL_GetError());SDL_RenderSetLogicalSize(software,256,384);
        }
        if(options.fullscreen)check(SDL_SetWindowFullscreen(window,SDL_WINDOW_FULLSCREEN_DESKTOP)==0,SDL_GetError());
        } catch(...) {cleanup();throw;}
    }
    ~Impl(){cleanup();}
    void cleanup() {
        if(context)SDL_GL_MakeCurrent(window,context);
        if(gl) {
            clear_textures();
            if(scene_program)gl->DeleteProgram(scene_program);if(flat_program)gl->DeleteProgram(flat_program);
            if(vbo)gl->DeleteBuffers(1,&vbo);if(vao)gl->DeleteVertexArrays(1,&vao);
            if(screen_texture)gl->DeleteTextures(1,&screen_texture);if(mask_texture)gl->DeleteTextures(1,&mask_texture);
        }
        scene_program=flat_program=vao=vbo=screen_texture=mask_texture=0;gl.reset();
        if(software_texture)SDL_DestroyTexture(software_texture);software_texture=nullptr;
        if(software)SDL_DestroyRenderer(software);software=nullptr;
        if(context)SDL_GL_DeleteContext(context);context=nullptr;
        if(window)SDL_DestroyWindow(window);window=nullptr;
    }
    void create_gl() {
        SDL_GL_SetAttribute(SDL_GL_CONTEXT_MAJOR_VERSION,3);SDL_GL_SetAttribute(SDL_GL_CONTEXT_MINOR_VERSION,3);
        SDL_GL_SetAttribute(SDL_GL_CONTEXT_PROFILE_MASK,SDL_GL_CONTEXT_PROFILE_CORE);
        SDL_GL_SetAttribute(SDL_GL_DOUBLEBUFFER,1);SDL_GL_SetAttribute(SDL_GL_DEPTH_SIZE,24);
        window=SDL_CreateWindow("DS PC project — OpenGL",SDL_WINDOWPOS_CENTERED_DISPLAY(display_index),SDL_WINDOWPOS_CENTERED_DISPLAY(display_index),
            options.width,options.height,SDL_WINDOW_OPENGL|SDL_WINDOW_RESIZABLE|SDL_WINDOW_ALLOW_HIGHDPI);
        check(window,SDL_GetError());context=SDL_GL_CreateContext(window);check(context,SDL_GetError());
        gl=std::make_unique<GL>();
        device_name=reinterpret_cast<const char*>(gl->GetString(GL_RENDERER));
        scene_program=gl->program(scene_vertex,scene_fragment);flat_program=gl->program(flat_vertex,flat_fragment);
        gl->GenVertexArrays(1,&vao);gl->BindVertexArray(vao);gl->GenBuffers(1,&vbo);
        gl->GenTextures(1,&screen_texture);gl->GenTextures(1,&mask_texture);
        SDL_GL_SetSwapInterval(1);renderer_name="opengl";
    }
    void clear_textures(){for(auto [key,value]:textures)gl->DeleteTextures(1,&value);textures.clear();}
    void upload(GLuint texture,int w,int h,const void* data,GLenum format=GL_RGBA) {
        gl->BindTexture(GL_TEXTURE_2D,texture);
        gl->TexParameteri(GL_TEXTURE_2D,GL_TEXTURE_MIN_FILTER,GL_NEAREST);gl->TexParameteri(GL_TEXTURE_2D,GL_TEXTURE_MAG_FILTER,GL_NEAREST);
        gl->TexParameteri(GL_TEXTURE_2D,GL_TEXTURE_WRAP_S,GL_CLAMP_TO_EDGE);gl->TexParameteri(GL_TEXTURE_2D,GL_TEXTURE_WRAP_T,GL_CLAMP_TO_EDGE);
        gl->PixelStorei(GL_UNPACK_ALIGNMENT,1);
        gl->TexImage2D(GL_TEXTURE_2D,0,format==GL_RED?GL_R8:GL_RGBA8,w,h,0,format,GL_UNSIGNED_BYTE,data);
    }
    GLint uniform(GLuint program,const char* name){return gl->GetUniformLocation(program,name);}
    void flat(const uint32_t* pixels,int w,int h,Rect rect) {
        gl->UseProgram(flat_program);gl->ActiveTexture(GL_TEXTURE0);upload(screen_texture,w,h,pixels,GL_BGRA);
        gl->Uniform1i(uniform(flat_program,"image"),0);
        const float x0=2*rect.x/width-1,x1=2*(rect.x+rect.w)/width-1;
        const float y0=2*rect.y/height-1,y1=2*(rect.y+rect.h)/height-1;
        const float vertices[]={x0,y0,0,1,x1,y0,1,1,x0,y1,0,0,x0,y1,0,0,x1,y0,1,1,x1,y1,1,0};
        gl->Disable(GL_DEPTH_TEST);gl->Disable(GL_CULL_FACE);gl->DepthMask(GL_FALSE);
        gl->Enable(GL_BLEND);gl->BlendFunc(GL_SRC_ALPHA,GL_ONE_MINUS_SRC_ALPHA);
        gl->BindBuffer(GL_ARRAY_BUFFER,vbo);gl->BufferData(GL_ARRAY_BUFFER,sizeof(vertices),vertices,GL_STREAM_DRAW);
        gl->EnableVertexAttribArray(0);gl->VertexAttribPointer(0,4,GL_FLOAT,GL_FALSE,4*sizeof(float),nullptr);
        gl->DrawArrays(GL_TRIANGLES,0,6);
    }
    void geometry(const Scene& scene,Rect original,const uint8_t* mask) {
        clear_textures();
        gl->ActiveTexture(GL_TEXTURE0);
        for(const auto& texture:scene.textures) {
            GLuint name;gl->GenTextures(1,&name);upload(name,texture.width,texture.height,texture.rgba.data());
            const auto wrap=[&](unsigned axis){return !(texture.param&(1u<<(16+axis)))?GL_CLAMP_TO_EDGE:
                (texture.param&(1u<<(18+axis)))?GL_MIRRORED_REPEAT:GL_REPEAT;};
            gl->TexParameteri(GL_TEXTURE_2D,GL_TEXTURE_WRAP_S,wrap(0));gl->TexParameteri(GL_TEXTURE_2D,GL_TEXTURE_WRAP_T,wrap(1));
            textures[{texture.param,texture.palette}]=name;
        }
        gl->UseProgram(scene_program);gl->Uniform1i(uniform(scene_program,"image"),0);
        gl->Uniform1i(uniform(scene_program,"masked"),mask!=nullptr);
        gl->Uniform2f(uniform(scene_program,"mask_origin"),original.x,original.y);
        gl->Uniform2f(uniform(scene_program,"mask_size"),original.w,original.h);
        if(mask){gl->ActiveTexture(GL_TEXTURE1);upload(mask_texture,256,192,mask,GL_RED);gl->Uniform1i(uniform(scene_program,"mask_image"),1);gl->ActiveTexture(GL_TEXTURE0);}
        gl->Uniform1i(uniform(scene_program,"highlight"),(scene.control&2)!=0);
        gl->Uniform1i(uniform(scene_program,"wbuffer"),(scene.swap_mode&2)!=0);
        gl->Uniform1i(uniform(scene_program,"alpha_ref"),(scene.control&4)?int(scene.alpha_ref):0);
        std::array<float,96> toon{};
        for(unsigned i=0;i<32;++i)for(unsigned c=0;c<3;++c){const auto value=(scene.toon[i]>>(c*5))&31;toon[i*3+c]=float(value?value*2+1:0);}
        gl->Uniform3fv(uniform(scene_program,"toon"),32,toon.data());
        gl->DepthMask(GL_TRUE);gl->ClearDepth(double(((scene.clear_depth&0x7fff)<<9)|0x1ff)/0xffffff);
        gl->Clear(GL_DEPTH_BUFFER_BIT);gl->Enable(GL_DEPTH_TEST);gl->DepthFunc(GL_LESS);
        if(scene.control&8)gl->Enable(GL_BLEND);else gl->Disable(GL_BLEND);
        gl->BlendFunc(GL_SRC_ALPHA,GL_ONE_MINUS_SRC_ALPHA);
        for(const auto index:scene.order) {
            if(index>=scene.polygons.size())continue;
            const auto& polygon=scene.polygons[index];
            if(polygon.count<3||polygon.count>4)continue;
            const unsigned faces=(polygon.attr>>6)&3;if(!faces)continue;
            if(faces==3)gl->Disable(GL_CULL_FACE);else{gl->Enable(GL_CULL_FACE);gl->CullFace(faces==1?GL_FRONT:GL_BACK);}
            const unsigned alpha=(polygon.attr>>16)&31;
            const unsigned format=(polygon.texture>>26)&7,mode=(polygon.attr>>4)&3;
            const bool partial=(alpha!=0&&alpha!=31)||((format==1||format==6)&&mode!=1&&mode!=3);
            gl->DepthMask(!partial||(polygon.attr&(1u<<11))?GL_TRUE:GL_FALSE);
            gl->PolygonMode(GL_FRONT_AND_BACK,alpha?GL_FILL:GL_LINE);
            gl->Uniform1i(uniform(scene_program,"mode"),(polygon.attr>>4)&3);gl->Uniform1i(uniform(scene_program,"alpha"),alpha);
            auto texture=textures.find({polygon.texture,polygon.palette});
            gl->Uniform1i(uniform(scene_program,"textured"),texture!=textures.end());
            gl->BindTexture(GL_TEXTURE_2D,texture==textures.end()?0:texture->second);
            const unsigned x=polygon.viewport&255,y=(polygon.viewport>>8)&255;
            const unsigned w=uint8_t((polygon.viewport>>16)-x)+1,h=uint8_t((polygon.viewport>>24)-y)+1;
            const int base_y=y>191?int(y)-255:int(y);
            const float rw=original.w*w/256,rh=original.h*h/192;
            const float rx=original.x+original.w*x/256,ry=original.y+original.h*(192-base_y-int(h))/192;
            if(mask) {
                const int left=std::max(0,int(std::ceil(rx))),bottom=std::max(0,int(std::ceil(ry)));
                const int right=std::min(width,int(std::ceil(rx+rw))),top=std::min(height,int(std::ceil(ry+rh)));
                gl->Enable(GL_SCISSOR_TEST);gl->Scissor(left,bottom,std::max(0,right-left),std::max(0,top-bottom));
            }
            gl->Uniform2f(uniform(scene_program,"scale_xy"),rw/width,rh/height);
            gl->Uniform2f(uniform(scene_program,"offset_xy"),(2*rx+rw)/width-1,(2*ry+rh)/height-1);
            std::array<dsr::Gpu3DVertex,6> vertices{};const unsigned indices[]={0,1,2,0,2,3};
            const unsigned count=alpha?(polygon.count==4?6:3):polygon.count;bool valid=true;
            for(unsigned i=0;i<count;++i){const auto v=polygon.index[alpha?indices[i]:i];if(v>=scene.vertices.size()){valid=false;break;}vertices[i]=scene.vertices[v];}
            if(!valid)continue;
            gl->BindBuffer(GL_ARRAY_BUFFER,vbo);gl->BufferData(GL_ARRAY_BUFFER,count*sizeof(vertices[0]),vertices.data(),GL_STREAM_DRAW);
            for(unsigned i=0;i<3;++i)gl->EnableVertexAttribArray(i);
            gl->VertexAttribPointer(0,4,GL_FLOAT,GL_FALSE,sizeof(vertices[0]),reinterpret_cast<void*>(offsetof(dsr::Gpu3DVertex,clip)));
            gl->VertexAttribPointer(1,2,GL_FLOAT,GL_FALSE,sizeof(vertices[0]),reinterpret_cast<void*>(offsetof(dsr::Gpu3DVertex,u)));
            gl->VertexAttribPointer(2,3,GL_FLOAT,GL_FALSE,sizeof(vertices[0]),reinterpret_cast<void*>(offsetof(dsr::Gpu3DVertex,color)));
            gl->DrawArrays(alpha?GL_TRIANGLES:GL_LINE_LOOP,0,count);++draws;
        }
        gl->PolygonMode(GL_FRONT_AND_BACK,GL_FILL);gl->DepthMask(GL_TRUE);gl->Disable(GL_CULL_FACE);gl->Disable(GL_SCISSOR_TEST);
    }
    void present(const Frame& frame) {
        check(frame.top&&frame.bottom,"missing DS video frames");
        if(!gl) {
            SDL_Rect top{0,0,256,192},bottom{0,192,256,192};
            check(SDL_UpdateTexture(software_texture,&top,frame.top,256*4)==0,SDL_GetError());
            check(SDL_UpdateTexture(software_texture,&bottom,frame.bottom,256*4)==0,SDL_GetError());
            SDL_RenderClear(software);SDL_RenderCopy(software,software_texture,nullptr,nullptr);
            SDL_GetRendererOutputSize(software,&width,&height);
            if(options.readback) {
                last_pixels.resize(size_t(width)*height);
                check(SDL_RenderReadPixels(software,nullptr,SDL_PIXELFORMAT_ARGB8888,last_pixels.data(),width*4)==0,SDL_GetError());
            }
            SDL_RenderPresent(software);return;
        }
        SDL_GL_GetDrawableSize(window,&width,&height);if(width<=0||height<=0)return;
        const bool has_3d=frame.scene&&frame.scene->supported&&!frame.scene->order.empty()&&frame.three_d&&
            std::any_of(frame.three_d,frame.three_d+256*192,[](uint8_t x){return x!=0;});
        unified_active=options.screen_mode=="unified"&&has_3d;
        gl->Viewport(0,0,width,height);gl->DepthMask(GL_TRUE);gl->ClearDepth(1);gl->ClearColor(0,0,0,1);gl->Clear(GL_COLOR_BUFFER_BIT|GL_DEPTH_BUFFER_BIT);
        if(unified_active) {
            // Prefer one bottom camera for alternating-camera games. Retain its
            // last completed scene during the other camera's frame; no guessed
            // camera offsets or invented 60 Hz game updates are applied.
            if(!frame.on_top||!have_bottom) {
                unified_scene=*frame.scene;unified_on_top=frame.on_top;
                const auto* native=frame.on_top?frame.top:frame.bottom;
                for(unsigned i=0;i<unified_ui.size();++i)unified_ui[i]=
                    frame.three_d[i]&&frame.scene->safe[i]?0:native[i];
                if(!frame.on_top)have_bottom=true;
            }
            const auto clear=unified_scene.clear_color;
            gl->ClearColor(float(clear&31)/31,float((clear>>5)&31)/31,float((clear>>10)&31)/31,1);gl->Clear(GL_COLOR_BUFFER_BIT);
            const float h=float(height)/2,w=h*256/192;
            const Rect original{(width-w)/2,unified_on_top?h:0,w,h};
            geometry(unified_scene,original,nullptr);flat(unified_ui.data(),256,192,original);
            touch_rect=unified_on_top?Rect{}:original;
            // Generic output cannot identify every game's secondary-screen UI.
            // Keep it accessible in an inset; F7 can hide it after title review.
            if(secondary_visible) {
                const float sh=height/4.0F,sw=sh*256/192;
                const Rect secondary{width-sw-16,height-sh-16,sw,sh};
                flat(unified_on_top?frame.bottom:frame.top,256,192,secondary);
                if(unified_on_top)touch_rect=secondary;
            }
        } else {
            // Leaving a scene (a menu, unsupported effect or 2D game) discards
            // its retained camera; never display stale scenery over that UI.
            have_bottom=false;
            const auto total=fit(float(width),float(height),256.0F/384);
            Rect bottom{total.x,total.y,total.w,total.h/2},top{total.x,total.y+total.h/2,total.w,total.h/2};
            flat(frame.top,256,192,top);flat(frame.bottom,256,192,bottom);touch_rect=bottom;
            if(has_3d) {
                std::array<uint8_t,256*192> mask{};
                for(unsigned i=0;i<mask.size();++i)mask[i]=frame.three_d[i]&&frame.scene->safe[i]?255:0;
                geometry(*frame.scene,frame.on_top?top:bottom,mask.data());
            }
        }
        check(gl->GetError()==GL_NO_ERROR,"OpenGL presentation failed");
        if(options.readback) {
            last_pixels.resize(size_t(width)*height);
            gl->ReadPixels(0,0,width,height,GL_BGRA,GL_UNSIGNED_BYTE,last_pixels.data());
            for(int y=0;y<height/2;++y)std::swap_ranges(last_pixels.begin()+size_t(y)*width,last_pixels.begin()+size_t(y+1)*width,last_pixels.begin()+size_t(height-y-1)*width);
        }
        SDL_GL_SwapWindow(window);
    }
};

Display::Display(Options options):impl_(std::make_unique<Impl>(std::move(options))){}
Display::~Display()=default;
void Display::present(const Frame& frame){impl_->present(frame);}
void Display::key(const SDL_KeyboardEvent& event) {
    if(event.repeat||event.type!=SDL_KEYDOWN)return;
    if(event.keysym.scancode==SDL_SCANCODE_F11) {
        const bool full=(SDL_GetWindowFlags(impl_->window)&SDL_WINDOW_FULLSCREEN_DESKTOP)!=0;
        check(SDL_SetWindowFullscreen(impl_->window,full?0:SDL_WINDOW_FULLSCREEN_DESKTOP)==0,SDL_GetError());
    }
    if(event.keysym.scancode==SDL_SCANCODE_F6&&impl_->gl)impl_->options.screen_mode=impl_->options.screen_mode=="dual"?"unified":"dual";
    if(event.keysym.scancode==SDL_SCANCODE_F7)impl_->secondary_visible=!impl_->secondary_visible;
}
bool Display::touch(int x,int y,int& ds_x,int& ds_y) const {
    if(impl_->software) {
        float lx,ly;SDL_RenderWindowToLogical(impl_->software,x,y,&lx,&ly);
        if(lx<0||lx>=256||ly<192||ly>=384)return false;
        ds_x=int(lx);ds_y=int(ly)-192;return true;
    }
    int ww,wh;SDL_GetWindowSize(impl_->window,&ww,&wh);if(ww<=0||wh<=0)return false;
    const float px=float(x)*impl_->width/ww,py=impl_->height-float(y)*impl_->height/wh;
    const auto r=impl_->touch_rect;
    if(r.w<=0||r.h<=0||px<r.x||px>=r.x+r.w||py<=r.y||py>r.y+r.h)return false;
    ds_x=std::clamp(int((px-r.x)*256/r.w),0,255);ds_y=std::clamp(int((r.y+r.h-py)*192/r.h),0,191);return true;
}
std::vector<uint32_t> Display::read_pixels() const{return impl_->last_pixels;}
int Display::width() const{return impl_->width;}
int Display::height() const{return impl_->height;}
const std::string& Display::renderer() const{return impl_->renderer_name;}
const std::string& Display::device() const{return impl_->device_name;}
bool Display::unified() const{return impl_->unified_active;}
uint64_t Display::polygons_drawn() const{return impl_->draws;}
}
