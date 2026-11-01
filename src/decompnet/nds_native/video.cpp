// SPDX-License-Identifier: MIT. Original decomp.wtf SDL/OpenGL presentation.
#include "video.hpp"
#include "dynamic_layout.hpp"
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

#ifdef _WIN32
// Laptop drivers inspect these executable exports before creating a GL
// context. Request the discrete GPU without changing global driver settings.
extern "C" {
__declspec(dllexport) unsigned long NvOptimusEnablement=1;
__declspec(dllexport) int AmdPowerXpressRequestHighPerformance=1;
}
#endif

namespace video {
Scene Scene::capture(dsr::Machine& machine) {
    Scene scene;
    auto& gpu=machine.gpu3d();
    scene.widescreen=gpu.host_widescreen_aspect()>0;
    const auto geometry=scene.widescreen?gpu.widescreen_geometry_view():gpu.geometry_view();const auto raster=gpu.raster_view();
    scene.generation=geometry.generation;scene.serial=gpu.render_serial();scene.swap_mode=geometry.swap_mode;
    scene.vertices.assign(geometry.vertices,geometry.vertices+geometry.vertex_count);
    scene.polygons.assign(geometry.polygons,geometry.polygons+geometry.polygon_count);
    if(!scene.widescreen) {
        const auto order=gpu.draw_order_view();
        scene.order.assign(order.opaque,order.opaque+order.opaque_count);
        scene.order.insert(scene.order.end(),order.translucent,order.translucent+order.translucent_count);
    } else {
        std::vector<uint16_t> opaque,partial;
        for(size_t i=0;i<scene.polygons.size();++i) {
            const auto& p=scene.polygons[i];const unsigned alpha=(p.attr>>16)&31,format=(p.texture>>26)&7,mode=(p.attr>>4)&3;
            ((alpha!=0&&alpha!=31)||((format==1||format==6)&&mode!=1&&mode!=3)?partial:opaque).push_back(uint16_t(i));
        }
        auto range=[&](uint16_t i){float low=1e30f,high=-1e30f;const auto& p=scene.polygons[i];
            for(unsigned n=0;n<p.count;++n){const auto& v=scene.vertices[p.index[n]];const float w=v.clip[3]!=0?v.clip[3]:.00000001f;
                const float y=1-(v.clip[1]+w)/(2*w);low=std::min(low,y);high=std::max(high,y);}
            return std::pair{high,low};};
        auto before=[&](uint16_t a,uint16_t b){return range(a)<range(b);};
        std::stable_sort(opaque.begin(),opaque.end(),before);
        if(!(scene.swap_mode&1))std::stable_sort(partial.begin(),partial.end(),before);
        scene.order=std::move(opaque);scene.order.insert(scene.order.end(),partial.begin(),partial.end());
    }
    scene.control=raster.disp3d;scene.clear_color=raster.clear_color;
    scene.clear_depth=raster.clear_depth;scene.alpha_ref=raster.alpha_reference;
    scene.fog_color=raster.fog_color;scene.fog_offset=raster.fog_offset;
    for(unsigned i=0;i<32;++i)scene.toon[i]=raster.toon_table[i*2]|(uint32_t(raster.toon_table[i*2+1])<<8);
    for(unsigned i=0;i<8;++i)scene.edge[i]=raster.edge_table[i*2]|(uint32_t(raster.edge_table[i*2+1])<<8);
    std::copy_n(raster.fog_density,32,scene.fog_density.begin());
    // Clear-image bitmaps require their own captured source. All geometry
    // effects (including fog, edge marking and shadows) are rendered below.
    scene.supported=!(raster.disp3d&(1u<<14)) && !geometry.vertex_overflow && !geometry.polygon_overflow;
    scene.safe.fill(1);
    dsr::gpu3d_detail::TextureSource source;
    source.context=&machine.gpu2d();
    source.texture_lookup=[](const void* p,int slot){return static_cast<const dsr::Gpu2D*>(p)->texture_slot(slot);};
    source.palette_lookup=[](const void* p,int slot){return static_cast<const dsr::Gpu2D*>(p)->texpal_slot(slot);};
    source.texture_read=[](const void* p,uint32_t a){return static_cast<const dsr::Gpu2D*>(p)->texture_byte(a);};
    source.palette_read=[](const void* p,uint32_t a){return static_cast<const dsr::Gpu2D*>(p)->texpal_byte(a);};
    std::map<std::pair<uint32_t,uint32_t>,bool> decoded;
    size_t texture_bytes=0;
    for(const auto& polygon:scene.polygons) {
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
 X(void,GenFramebuffers,(GLsizei,GLuint*)) X(void,BindFramebuffer,(GLenum,GLuint)) \
 X(void,DeleteFramebuffers,(GLsizei,const GLuint*)) X(void,FramebufferTexture2D,(GLenum,GLenum,GLenum,GLuint,GLint)) \
 X(GLenum,CheckFramebufferStatus,(GLenum)) X(void,GenRenderbuffers,(GLsizei,GLuint*)) \
 X(void,BindRenderbuffer,(GLenum,GLuint)) X(void,RenderbufferStorage,(GLenum,GLenum,GLsizei,GLsizei)) \
 X(void,FramebufferRenderbuffer,(GLenum,GLenum,GLenum,GLuint)) X(void,DeleteRenderbuffers,(GLsizei,const GLuint*)) \
 X(const GLubyte*,GetString,(GLenum)) X(void,GetIntegerv,(GLenum,GLint*)) X(GLenum,GetError,()) \
 X(void,Viewport,(GLint,GLint,GLsizei,GLsizei)) X(void,ClearColor,(GLfloat,GLfloat,GLfloat,GLfloat)) \
 X(void,ClearDepth,(GLdouble)) X(void,Clear,(GLbitfield)) X(void,Enable,(GLenum)) X(void,Disable,(GLenum)) \
 X(void,DepthFunc,(GLenum)) X(void,DepthMask,(GLboolean)) X(void,BlendFunc,(GLenum,GLenum)) \
 X(void,DrawBuffers,(GLsizei,const GLenum*)) X(void,ReadBuffer,(GLenum)) X(void,ClearBufferfv,(GLenum,GLint,const GLfloat*)) \
 X(void,CopyTexSubImage2D,(GLenum,GLint,GLint,GLint,GLint,GLint,GLsizei,GLsizei)) \
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
 X(void,Uniform1iv,(GLint,GLsizei,const GLint*)) X(void,Uniform4f,(GLint,GLfloat,GLfloat,GLfloat,GLfloat)) \
 X(void,Uniform3fv,(GLint,GLsizei,const GLfloat*)) \
 X(void,GenVertexArrays,(GLsizei,GLuint*)) X(void,BindVertexArray,(GLuint)) X(void,DeleteVertexArrays,(GLsizei,const GLuint*)) \
 X(void,GenBuffers,(GLsizei,GLuint*)) X(void,BindBuffer,(GLenum,GLuint)) \
 X(void,BufferData,(GLenum,GLsizeiptr,const void*,GLenum)) X(void,DeleteBuffers,(GLsizei,const GLuint*)) \
 X(void,EnableVertexAttribArray,(GLuint)) X(void,VertexAttribPointer,(GLuint,GLint,GLenum,GLboolean,GLsizei,const void*)) \
 X(void,DrawArrays,(GLenum,GLint,GLsizei)) X(void,ActiveTexture,(GLenum)) \
 X(void,GenTextures,(GLsizei,GLuint*)) X(void,BindTexture,(GLenum,GLuint)) X(void,DeleteTextures,(GLsizei,const GLuint*)) \
 X(void,GenerateMipmap,(GLenum)) \
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
layout(location=0) out vec4 pixel;
layout(location=1) out vec2 packed_state;
uniform sampler2D image,previous_color,previous_state;
uniform bool textured,highlight,wbuffer,read_previous,depth_equal,blend_enabled,fog_enabled,partial_polygon,depth_write;
uniform int mode,alpha,alpha_ref,polygon_id;
uniform vec3 toon[32];
vec4 decode(vec4 s){int p=int(s.y+0.5);return vec4(s.x,float(p&63),float(((p>>6)&127)-1),float(p>>13));}
vec2 encode(vec4 s){return vec2(s.x,float(int(s.y+0.5)|((int(s.z)+1)<<6)|(int(s.w+0.5)<<13)));}
void main(){
 // State stores depth, opaque ID, last translucent ID and four raster flags.
 // Copies cover only this polygon's clipped bounds; no attached image is sampled.
 float depth=wbuffer?clamp((1/gl_FragCoord.w)/4096,0,1):floor(gl_FragCoord.z*4194303.0)*4/16777215.0;
 vec4 old=vec4(0),dst=vec4(0);int flags=0;
 if(read_previous){ivec2 at=ivec2(gl_FragCoord.xy);old=decode(texelFetch(previous_state,at,0));dst=texelFetch(previous_color,at,0);flags=int(old.w+0.5);
   bool failed=depth_equal?abs(depth-old.x)>255.0/16777215.0:depth>=old.x;
   if(!depth_equal && depth==old.x && gl_FrontFacing && (flags&4)!=0 && dst.a==1)failed=false;
   if(mode==3 && polygon_id==0){if(!failed)discard;pixel=dst;old.w=float(flags|8);packed_state=encode(old);gl_FragDepth=old.x;return;}
   if(failed)discard;
   if(mode==3){if((flags&8)==0 || int(old.y+0.5)==polygon_id)discard;flags&=~8;}
 }
 vec3 v=floor(clamp(vertex_color,0,63)+0.5),t=vec3(63);float ta=31;
 if(textured){vec4 sample_color=texture(image,texcoord/vec2(textureSize(image,0)));t=floor(sample_color.rgb*63+0.5);ta=floor(sample_color.a*31+0.5);}
 vec3 shade=v;float a=float(alpha==0?31:alpha);
 if(mode==2)shade=highlight?vec3(v.r):toon[int(v.r)/2];
 if(mode==1 && textured)shade=ta==0?v:(ta==31?t:floor((t*ta+v*(31-ta))/32));
 else {shade=floor(((t+1)*(shade+1)-1)/64);if(mode==2&&highlight)shade=min(vec3(63),shade+toon[int(v.r)/2]);
   if(textured){float t6=ta==0?0:ta*2+1,a6=a==0?0:a*2+1;a=floor(floor(((t6+1)*(a6+1)-1)/64)/2);}}
 if(a==0 || a<=float(alpha_ref))discard;
 bool partial=a<31;
 if(read_previous && partial && int(old.z+0.5)==polygon_id)discard;
 vec3 rgb=shade/63;
 if(read_previous && partial && blend_enabled && dst.a>0)rgb=(rgb*(a+1)+dst.rgb*(31-a))/32;
 float out_alpha=(read_previous && partial && blend_enabled && dst.a>0)?max(a/31,dst.a):a/31;
 pixel=vec4(rgb,out_alpha);
 bool fog=fog_enabled && (!partial || (flags&1)!=0);
 int updated=(fog?1:0)|(partial_polygon?2:0)|(gl_FrontFacing?0:4)|(flags&8);
 vec4 state=vec4((!partial||depth_write)?depth:old.x,partial?old.y:float(polygon_id),partial?float(polygon_id):(read_previous?old.z:-1),float(updated));
 packed_state=encode(state);gl_FragDepth=state.x;
}
)GLSL";
// Edge marking and fog operate on the completed 3D framebuffer. Applying fog
// separately to every translucent layer makes clouds opaque and over-fogs sky.
const char* effects_fragment=R"GLSL(#version 330 core
in vec2 uv;out vec4 pixel;
uniform sampler2D image,states;
uniform bool edges,fog,alpha_fog,edge_blend;
uniform int fog_shift,fog_offset,density[32],edge_step;
uniform vec4 fog_color;
uniform vec3 edge[8];
vec4 decode(vec4 s){int p=int(s.y+0.5);return vec4(s.x,float(p&63),float(((p>>6)&127)-1),float(p>>13));}
void main(){
 ivec2 size=textureSize(image,0),at=clamp(ivec2(uv*vec2(size)),ivec2(0),size-1);
 vec4 c=texelFetch(image,at,0),s=decode(texelFetch(states,at,0));int flags=int(s.w+0.5);
 if(edges && (flags&2)==0){
  ivec2 steps[4]=ivec2[4](ivec2(1,0),ivec2(0,-1),ivec2(-1,0),ivec2(0,1));
  for(int i=0;i<4;i++){ivec2 p=clamp(at+steps[i]*edge_step,ivec2(0),size-1);vec4 n=decode(texelFetch(states,p,0));
   if(s.y!=n.y && s.x>=n.x){vec3 e=edge[int(n.y+0.5)/8];c.rgb=(edge_blend&&c.a>0)?mix(c.rgb,e,17.0/32.0):e;c.a=max(c.a,edge_blend?16.0/31.0:1);break;}}
 }
 if(fog && (flags&1)!=0){
  int step=1024>>fog_shift,depth=int(s.x*16777215.0+0.5)>>9,relative=max(0,depth-fog_offset),d;
  if(step==0)d=density[depth<=fog_offset?0:31];
  else if(relative<=step)d=density[0];
  else if(relative>=step*32)d=density[31];
  else {int segment=relative/step,fraction=relative-segment*step;d=(density[segment-1]*(step-fraction)+density[segment]*fraction)/step;}
  float weight=float(d==127?128:d)/128;
  if(!alpha_fog)c.rgb=mix(c.rgb,fog_color.rgb,weight);c.a=mix(c.a,fog_color.a,weight);
 }
 pixel=c;
}
)GLSL";
const char* flat_vertex=R"GLSL(#version 330 core
layout(location=0) in vec4 vertex;out vec2 uv;
void main(){gl_Position=vec4(vertex.xy,0,1);uv=vertex.zw;}
)GLSL";
const char* flat_fragment=R"GLSL(#version 330 core
in vec2 uv;out vec4 pixel;uniform sampler2D image;
uniform int brightness;uniform bool premultiplied;
void main(){pixel=texture(image,uv);float f=float(brightness&31)/16;
 if((brightness>>5)==1)pixel.rgb=mix(pixel.rgb,vec3(premultiplied?pixel.a:1),f);
 if((brightness>>5)==2)pixel.rgb*=1-f;}
)GLSL";
// A captured bitmap may be scrolled or rotated. Reconstruct subpixel source
// coordinates only from neighbours carrying the same raster identity; coverage
// remains nearest-neighbour so an original UI pixel is never overwritten.
const char* captured_fragment=R"GLSL(#version 330 core
in vec2 uv;out vec4 pixel;
uniform sampler2D image,origins;
uniform bool opaque_output;
vec4 origin(ivec2 p){return texelFetch(origins,clamp(p,ivec2(0),ivec2(255,191)),0);}
vec2 derivative(ivec2 p,ivec2 step,vec4 center){
 vec4 a=origin(p-step),b=origin(p+step);vec2 d=vec2(0);float n=0;
 if(all(greaterThanEqual(p-step,ivec2(0)))&&a.w>0.5&&all(lessThan(abs(a.xy-center.xy),vec2(0.04)))){d+=center.xy-a.xy;n++;}
 if(all(lessThan(p+step,ivec2(256,192)))&&b.w>0.5&&all(lessThan(abs(b.xy-center.xy),vec2(0.04)))){d+=b.xy-center.xy;n++;}
 return n>0?d/n:vec2(0);
}
void main(){
 vec2 p=uv*vec2(256,192);ivec2 at=clamp(ivec2(floor(p)),ivec2(0),ivec2(255,191));vec4 center=origin(at);
 if(center.z<0.5)discard;
 vec2 local=fract(p)-vec2(0.5);
 vec2 source=center.xy+local.x*derivative(at,ivec2(1,0),center)+local.y*derivative(at,ivec2(0,1),center);
 pixel=texture(image,vec2(source.x,1-source.y));
 // A native opaque edge can cover a texel that the finer silhouette leaves
 // transparent. Its underlying 2D layer is unknown; preserve that native texel.
 if(opaque_output){if(pixel.a<30.5/31.0)discard;pixel.a=1;}
}
)GLSL";
struct Rect {float x=0,y=0,w=0,h=0;}; // Bottom-left drawable coordinates.
Rect fit(float width,float height,float aspect) {
    const float w=std::min(width,height*aspect),h=w/aspect;
    return {(width-w)/2,(height-h)/2,w,h};
}
using layout_detail::Box;
Box polygon_box(const Scene& scene,const dsr::Gpu3DPolygon& p) {
    if(p.count<3||p.count>4)return {};
    float left=256,top=192,right=0,bottom=0;
    const unsigned vx=p.viewport&255,vy=(p.viewport>>8)&255;
    const float vw=uint8_t((p.viewport>>16)-vx)+1,vh=uint8_t((p.viewport>>24)-vy)+1;
    const int base_y=vy>191?int(vy)-255:int(vy);
    for(unsigned i=0;i<p.count;++i){if(p.index[i]>=scene.vertices.size())return {};const auto& v=scene.vertices[p.index[i]];
        if(v.clip[3]<=0)return {};const float x=vx+(v.clip[0]/v.clip[3]+1)*vw/2,y=base_y+(1-v.clip[1]/v.clip[3])*vh/2;
        left=std::min(left,x);right=std::max(right,x);top=std::min(top,y);bottom=std::max(bottom,y);}
    const int x=int(std::floor(std::clamp(left,0.f,256.f))),y=int(std::floor(std::clamp(top,0.f,192.f)));
    return {x,y,int(std::ceil(std::clamp(right,float(x),256.f)))-x,int(std::ceil(std::clamp(bottom,float(y),192.f)))-y};
}
bool world_polygon(const dsr::Gpu3DPolygon& p){return p.perspective&&p.viewport==0xbfff0000;}
bool background_polygon(const Scene& scene,const dsr::Gpu3DPolygon& p) {
    if(p.perspective||p.count<3||p.count>4||p.viewport!=0xbfff0000)return false;const auto b=polygon_box(scene,p);
    if(b.w>=254&&b.h>=190)return true;
    // A sky can be several full-width gradient strips rather than one quad.
    // Submitted projection and far depth distinguish these from dialogue frames.
    return b.w>=254&&std::all_of(p.index.begin(),p.index.begin()+p.count,[&](unsigned i){
        if(i>=scene.vertices.size())return false;const auto& v=scene.vertices[i];return v.clip[3]>0&&v.clip[2]/v.clip[3]>=.99f;});
}
}

struct Display::Impl {
    Options options;
    SDL_Window* window=nullptr;SDL_GLContext context=nullptr;
    SDL_Renderer* software=nullptr;SDL_Texture* software_texture=nullptr;
    std::unique_ptr<GL> gl;
    GLuint scene_program=0,effects_program=0,flat_program=0,captured_program=0,vao=0,vbo=0,screen_texture=0,mask_texture=0,origin_texture=0;
    struct CapturedTarget {GLuint fbo=0,color=0,state=0,depth=0,effects_fbo=0,result=0,previous_color=0,previous_state=0;int w=0,h=0;};
    std::map<std::pair<uint64_t,unsigned>,CapturedTarget> captured_targets;
    std::vector<CapturedTarget> spare_targets;
    std::map<std::pair<uint32_t,uint32_t>,GLuint> textures;
    std::string renderer_name="software",device_name;
    Rect touch_rect;
    struct Touch {Rect destination;Box source;bool enabled;};
    std::vector<Touch> touch_regions;
    std::string layout_name="dual";
    int width=0,height=0,display_index=0;
    int scale=0;
    int maximum_scale=12;
    int maximum_texture_size=0;
    CapturedTarget* active_target=nullptr;
    uint64_t draws=0,captured_pixel_count=0;
    std::vector<uint32_t> last_pixels;

    explicit Impl(Options value):options(std::move(value)) {
        try {
        check(options.renderer=="auto"||options.renderer=="opengl"||options.renderer=="software","renderer must be auto, opengl or software");
        SDL_Point pointer{};SDL_GetGlobalMouseState(&pointer.x,&pointer.y);
        display_index=std::max(0,SDL_GetPointDisplayIndex(&pointer));
        if(options.width<=0||options.height<=0) {
            SDL_Rect usable{};
            if(SDL_GetDisplayUsableBounds(display_index,&usable)!=0)
                check(SDL_GetDisplayBounds(display_index,&usable)==0,SDL_GetError());
            options.width=std::max(1,usable.w*4/5);options.height=std::max(1,usable.h*4/5);
            if(options.dynamic_widescreen) {
                const int unit=std::max(1,std::min(options.width/16,options.height/9));
                options.width=unit*16;options.height=unit*9;
            }
        }
        if(options.renderer!="software") {
            try {create_gl();}
            catch(const std::exception& error) {
                cleanup();
                if(options.renderer=="opengl")throw;
                device_name.clear();
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
            for(auto& [serial,target]:captured_targets)delete_target(target);captured_targets.clear();
            for(auto& target:spare_targets)delete_target(target);spare_targets.clear();
            if(captured_program)gl->DeleteProgram(captured_program);if(origin_texture)gl->DeleteTextures(1,&origin_texture);
            if(scene_program)gl->DeleteProgram(scene_program);if(effects_program)gl->DeleteProgram(effects_program);if(flat_program)gl->DeleteProgram(flat_program);
            if(vbo)gl->DeleteBuffers(1,&vbo);if(vao)gl->DeleteVertexArrays(1,&vao);
            if(screen_texture)gl->DeleteTextures(1,&screen_texture);if(mask_texture)gl->DeleteTextures(1,&mask_texture);
        }
        scene_program=effects_program=flat_program=captured_program=vao=vbo=screen_texture=mask_texture=origin_texture=0;gl.reset();
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
        GLint maximum_texture=0;gl->GetIntegerv(GL_MAX_TEXTURE_SIZE,&maximum_texture);maximum_texture_size=maximum_texture;maximum_scale=std::clamp(maximum_texture/256,1,12);
        scene_program=gl->program(scene_vertex,scene_fragment);effects_program=gl->program(flat_vertex,effects_fragment);
        flat_program=gl->program(flat_vertex,flat_fragment);captured_program=gl->program(flat_vertex,captured_fragment);
        gl->GenVertexArrays(1,&vao);gl->BindVertexArray(vao);gl->GenBuffers(1,&vbo);
        gl->GenTextures(1,&screen_texture);gl->GenTextures(1,&mask_texture);gl->GenTextures(1,&origin_texture);
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
        gl->Uniform1i(uniform(flat_program,"brightness"),0);gl->Uniform1i(uniform(flat_program,"premultiplied"),false);
        const float x0=2*rect.x/width-1,x1=2*(rect.x+rect.w)/width-1;
        const float y0=2*rect.y/height-1,y1=2*(rect.y+rect.h)/height-1;
        const float vertices[]={x0,y0,0,1,x1,y0,1,1,x0,y1,0,0,x0,y1,0,0,x1,y0,1,1,x1,y1,1,0};
        gl->Disable(GL_DEPTH_TEST);gl->Disable(GL_CULL_FACE);gl->DepthMask(GL_FALSE);
        gl->Enable(GL_BLEND);gl->BlendFunc(GL_SRC_ALPHA,GL_ONE_MINUS_SRC_ALPHA);
        gl->BindBuffer(GL_ARRAY_BUFFER,vbo);gl->BufferData(GL_ARRAY_BUFFER,sizeof(vertices),vertices,GL_STREAM_DRAW);
        gl->EnableVertexAttribArray(0);gl->VertexAttribPointer(0,4,GL_FLOAT,GL_FALSE,4*sizeof(float),nullptr);
        gl->DrawArrays(GL_TRIANGLES,0,6);
    }
    void geometry(const Scene& scene,Rect original,unsigned layer=0,float aspect=4.f/3) {
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
        gl->Uniform1i(uniform(scene_program,"previous_color"),1);gl->Uniform1i(uniform(scene_program,"previous_state"),2);
        gl->Uniform1i(uniform(scene_program,"highlight"),(scene.control&2)!=0);
        gl->Uniform1i(uniform(scene_program,"wbuffer"),(scene.swap_mode&2)!=0);
        gl->Uniform1i(uniform(scene_program,"alpha_ref"),(scene.control&4)?int(scene.alpha_ref):0);
        std::array<float,96> toon{};
        for(unsigned i=0;i<32;++i)for(unsigned c=0;c<3;++c){const auto value=(scene.toon[i]>>(c*5))&31;toon[i*3+c]=float(value?value*2+1:0);}
        gl->Uniform3fv(uniform(scene_program,"toon"),32,toon.data());
        gl->DepthMask(GL_TRUE);gl->Enable(GL_DEPTH_TEST);gl->Disable(GL_BLEND);
        gl->Uniform1i(uniform(scene_program,"blend_enabled"),(scene.control&8)!=0);
        for(const auto index:scene.order) {
            if(index>=scene.polygons.size())continue;
            const auto& polygon=scene.polygons[index];
            const bool world=world_polygon(polygon),background=background_polygon(scene,polygon);
            if(layer==1&&!world&&!background)continue;
            if(layer==2&&(world||background))continue;
            if(polygon.count<3||polygon.count>4)continue;
            const unsigned faces=(polygon.attr>>6)&3;if(!faces)continue;
            if(faces==3)gl->Disable(GL_CULL_FACE);else{gl->Enable(GL_CULL_FACE);gl->CullFace(faces==1?GL_FRONT:GL_BACK);}
            const unsigned alpha=(polygon.attr>>16)&31;
            const unsigned format=(polygon.texture>>26)&7,mode=(polygon.attr>>4)&3;
            auto texture=textures.find({polygon.texture,polygon.palette});
            const bool textured=(scene.control&1)&&format&&texture!=textures.end();
            const bool partial=(alpha!=0&&alpha!=31)||(textured&&(format==1||format==6)&&mode!=1&&mode!=3);
            const bool feedback=partial||mode==3||(polygon.attr&(1u<<14));
            gl->DepthFunc(feedback?GL_ALWAYS:GL_LESS);
            gl->Uniform1i(uniform(scene_program,"read_previous"),feedback);
            gl->Uniform1i(uniform(scene_program,"depth_equal"),(polygon.attr&(1u<<14))!=0);
            gl->Uniform1i(uniform(scene_program,"depth_write"),(polygon.attr&(1u<<11))!=0);
            gl->Uniform1i(uniform(scene_program,"partial_polygon"),partial);
            gl->Uniform1i(uniform(scene_program,"fog_enabled"),(polygon.attr&(1u<<15))!=0);
            gl->Uniform1i(uniform(scene_program,"polygon_id"),(polygon.attr>>24)&63);
            gl->PolygonMode(GL_FRONT_AND_BACK,alpha?GL_FILL:GL_LINE);
            gl->Uniform1i(uniform(scene_program,"mode"),(polygon.attr>>4)&3);gl->Uniform1i(uniform(scene_program,"alpha"),alpha);
            gl->Uniform1i(uniform(scene_program,"textured"),textured);
            gl->ActiveTexture(GL_TEXTURE0);gl->BindTexture(GL_TEXTURE_2D,texture==textures.end()?0:texture->second);
            const unsigned x=polygon.viewport&255,y=(polygon.viewport>>8)&255;
            const unsigned w=uint8_t((polygon.viewport>>16)-x)+1,h=uint8_t((polygon.viewport>>24)-y)+1;
            const int base_y=y>191?int(y)-255:int(y);
            const float rw=original.w*w/256,rh=original.h*h/192;
            const float rx=original.x+original.w*x/256,ry=original.y+original.h*(192-base_y-int(h))/192;
            gl->Uniform2f(uniform(scene_program,"scale_xy"),rw/width,rh/height);
            gl->Uniform2f(uniform(scene_program,"offset_xy"),(2*rx+rw)/width-1,(2*ry+rh)/height-1);
            std::array<dsr::Gpu3DVertex,6> vertices{};const unsigned indices[]={0,1,2,0,2,3};
            const unsigned count=alpha?(polygon.count==4?6:3):polygon.count;bool valid=true;
            for(unsigned i=0;i<count;++i){const auto v=polygon.index[alpha?indices[i]:i];if(v>=scene.vertices.size()){valid=false;break;}vertices[i]=scene.vertices[v];}
            if(!valid)continue;
            if(layer==1&&world)for(unsigned i=0;i<count;++i)vertices[i].clip[0]*=(4.f/3)/aspect;
            float min_x=rx,min_y=ry,max_x=rx+rw,max_y=ry+rh;
            // Feedback copies only cover this polygon. Near-plane crossings
            // conservatively use the viewport; other quads use projected bounds.
            if(feedback&&std::all_of(vertices.begin(),vertices.begin()+count,[](const auto& v){return v.clip[3]>0;})) {
                min_x=max_x=rx+(vertices[0].clip[0]/vertices[0].clip[3]+1)*rw/2;
                min_y=max_y=ry+(vertices[0].clip[1]/vertices[0].clip[3]+1)*rh/2;
                for(unsigned i=1;i<count;++i){const auto& v=vertices[i];const float px=rx+(v.clip[0]/v.clip[3]+1)*rw/2,py=ry+(v.clip[1]/v.clip[3]+1)*rh/2;
                    min_x=std::min(min_x,px);max_x=std::max(max_x,px);min_y=std::min(min_y,py);max_y=std::max(max_y,py);}
                min_x=std::max(rx,min_x-1);min_y=std::max(ry,min_y-1);max_x=std::min(rx+rw,max_x+1);max_y=std::min(ry+rh,max_y+1);
            }
            const int left=std::clamp(int(std::floor(min_x)),0,width),bottom=std::clamp(int(std::floor(min_y)),0,height);
            const int right=std::clamp(int(std::ceil(max_x)),left,width),top=std::clamp(int(std::ceil(max_y)),bottom,height);
            if(right==left||top==bottom)continue;
            gl->Enable(GL_SCISSOR_TEST);gl->Scissor(left,bottom,right-left,top-bottom);
            if(feedback) {
                gl->ActiveTexture(GL_TEXTURE1);gl->BindTexture(GL_TEXTURE_2D,active_target->previous_color);gl->ReadBuffer(GL_COLOR_ATTACHMENT0);
                gl->CopyTexSubImage2D(GL_TEXTURE_2D,0,left,bottom,left,bottom,right-left,top-bottom);
                gl->ActiveTexture(GL_TEXTURE2);gl->BindTexture(GL_TEXTURE_2D,active_target->previous_state);gl->ReadBuffer(GL_COLOR_ATTACHMENT1);
                gl->CopyTexSubImage2D(GL_TEXTURE_2D,0,left,bottom,left,bottom,right-left,top-bottom);
                gl->ActiveTexture(GL_TEXTURE0);
            }
            gl->BindBuffer(GL_ARRAY_BUFFER,vbo);gl->BufferData(GL_ARRAY_BUFFER,count*sizeof(vertices[0]),vertices.data(),GL_STREAM_DRAW);
            for(unsigned i=0;i<3;++i)gl->EnableVertexAttribArray(i);
            gl->VertexAttribPointer(0,4,GL_FLOAT,GL_FALSE,sizeof(vertices[0]),reinterpret_cast<void*>(offsetof(dsr::Gpu3DVertex,clip)));
            gl->VertexAttribPointer(1,2,GL_FLOAT,GL_FALSE,sizeof(vertices[0]),reinterpret_cast<void*>(offsetof(dsr::Gpu3DVertex,u)));
            gl->VertexAttribPointer(2,3,GL_FLOAT,GL_FALSE,sizeof(vertices[0]),reinterpret_cast<void*>(offsetof(dsr::Gpu3DVertex,color)));
            gl->DrawArrays(alpha?GL_TRIANGLES:GL_LINE_LOOP,0,count);++draws;
        }
        gl->PolygonMode(GL_FRONT_AND_BACK,GL_FILL);gl->DepthMask(GL_TRUE);gl->Disable(GL_CULL_FACE);gl->Disable(GL_SCISSOR_TEST);
    }
    void delete_target(CapturedTarget& t) {
        if(t.fbo)gl->DeleteFramebuffers(1,&t.fbo);if(t.effects_fbo)gl->DeleteFramebuffers(1,&t.effects_fbo);
        for(auto texture:{t.color,t.state,t.result,t.previous_color,t.previous_state})if(texture)gl->DeleteTextures(1,&texture);
        if(t.depth)gl->DeleteRenderbuffers(1,&t.depth);t={};
    }
    CapturedTarget& captured_target(const Scene& scene,int w,int h,bool cache=true,unsigned layer=0,float aspect=4.f/3) {
        auto [position,inserted]=captured_targets.try_emplace(std::pair{scene.serial,layer});auto& target=position->second;
        if(inserted&&!spare_targets.empty()){
            auto spare=std::find_if(spare_targets.begin(),spare_targets.end(),[&](const auto& t){return t.w==w&&t.h==h;});
            if(spare==spare_targets.end())spare=spare_targets.end()-1;
            target=*spare;spare_targets.erase(spare);
        }
        if(!inserted&&target.fbo&&target.w==w&&target.h==h&&cache)return target;
        if(!target.fbo||target.w!=w||target.h!=h) {
            delete_target(target);target.w=w;target.h=h;
            auto allocate=[&](GLuint& texture,GLint format){gl->GenTextures(1,&texture);gl->BindTexture(GL_TEXTURE_2D,texture);
                gl->TexImage2D(GL_TEXTURE_2D,0,format,w,h,0,format==GL_RG32F?GL_RG:GL_RGBA,GL_FLOAT,nullptr);
                gl->TexParameteri(GL_TEXTURE_2D,GL_TEXTURE_MIN_FILTER,GL_NEAREST);gl->TexParameteri(GL_TEXTURE_2D,GL_TEXTURE_MAG_FILTER,GL_NEAREST);
                gl->TexParameteri(GL_TEXTURE_2D,GL_TEXTURE_WRAP_S,GL_CLAMP_TO_EDGE);gl->TexParameteri(GL_TEXTURE_2D,GL_TEXTURE_WRAP_T,GL_CLAMP_TO_EDGE);};
            gl->ActiveTexture(GL_TEXTURE0);
            allocate(target.color,GL_RGBA8);allocate(target.state,GL_RG32F);allocate(target.previous_color,GL_RGBA8);allocate(target.previous_state,GL_RG32F);allocate(target.result,GL_RGBA8);
            gl->TexParameteri(GL_TEXTURE_2D,GL_TEXTURE_MIN_FILTER,GL_LINEAR_MIPMAP_LINEAR);gl->TexParameteri(GL_TEXTURE_2D,GL_TEXTURE_MAG_FILTER,GL_LINEAR);
            gl->GenFramebuffers(1,&target.fbo);gl->BindFramebuffer(GL_FRAMEBUFFER,target.fbo);
            gl->FramebufferTexture2D(GL_FRAMEBUFFER,GL_COLOR_ATTACHMENT0,GL_TEXTURE_2D,target.color,0);
            gl->FramebufferTexture2D(GL_FRAMEBUFFER,GL_COLOR_ATTACHMENT1,GL_TEXTURE_2D,target.state,0);
            gl->GenRenderbuffers(1,&target.depth);gl->BindRenderbuffer(GL_RENDERBUFFER,target.depth);
            gl->RenderbufferStorage(GL_RENDERBUFFER,GL_DEPTH_COMPONENT24,w,h);
            gl->FramebufferRenderbuffer(GL_FRAMEBUFFER,GL_DEPTH_ATTACHMENT,GL_RENDERBUFFER,target.depth);
            const GLenum buffers[]={GL_COLOR_ATTACHMENT0,GL_COLOR_ATTACHMENT1};gl->DrawBuffers(2,buffers);
            check(gl->CheckFramebufferStatus(GL_FRAMEBUFFER)==GL_FRAMEBUFFER_COMPLETE,"enhanced-3D framebuffer unavailable");
            gl->GenFramebuffers(1,&target.effects_fbo);gl->BindFramebuffer(GL_FRAMEBUFFER,target.effects_fbo);
            gl->FramebufferTexture2D(GL_FRAMEBUFFER,GL_COLOR_ATTACHMENT0,GL_TEXTURE_2D,target.result,0);
            check(gl->CheckFramebufferStatus(GL_FRAMEBUFFER)==GL_FRAMEBUFFER_COMPLETE,"enhanced effects framebuffer unavailable");
        }
        gl->BindFramebuffer(GL_FRAMEBUFFER,target.fbo);active_target=&target;
        const auto c=layer==2?0:scene.clear_color;
        const float clear_depth=float(((scene.clear_depth&0x7fff)<<9)|0x1ff)/0xffffff;
        const float color[]={float(c&31)/31,float((c>>5)&31)/31,float((c>>10)&31)/31,float((c>>16)&31)/31};
        const float state[]={clear_depth,float(((c>>24)&63)|(((c>>15)&1)<<13)),0,0};
        gl->Viewport(0,0,w,h);gl->DepthMask(GL_TRUE);gl->Disable(GL_SCISSOR_TEST);gl->ClearDepth(clear_depth);
        gl->ClearBufferfv(GL_COLOR,0,color);gl->ClearBufferfv(GL_COLOR,1,state);gl->Clear(GL_DEPTH_BUFFER_BIT);
        const int previous_width=width,previous_height=height;width=w;height=h;
        geometry(scene,{0,0,float(w),float(h)},layer,aspect);
        gl->BindFramebuffer(GL_FRAMEBUFFER,target.effects_fbo);gl->UseProgram(effects_program);
        gl->ActiveTexture(GL_TEXTURE0);gl->BindTexture(GL_TEXTURE_2D,target.color);gl->Uniform1i(uniform(effects_program,"image"),0);
        gl->ActiveTexture(GL_TEXTURE1);gl->BindTexture(GL_TEXTURE_2D,target.state);gl->Uniform1i(uniform(effects_program,"states"),1);
        gl->Uniform1i(uniform(effects_program,"edges"),(scene.control&(1u<<5))!=0);gl->Uniform1i(uniform(effects_program,"edge_blend"),(scene.control&(1u<<4))!=0);
        gl->Uniform1i(uniform(effects_program,"edge_step"),std::max(1,h/384));
        gl->Uniform1i(uniform(effects_program,"fog"),(scene.control&(1u<<7))!=0);gl->Uniform1i(uniform(effects_program,"alpha_fog"),(scene.control&(1u<<6))!=0);
        gl->Uniform1i(uniform(effects_program,"fog_shift"),(scene.control>>8)&15);gl->Uniform1i(uniform(effects_program,"fog_offset"),scene.fog_offset&0x7fff);
        std::array<GLint,32> densities{};for(unsigned i=0;i<32;++i)densities[i]=scene.fog_density[i]&127;
        gl->Uniform1iv(uniform(effects_program,"density"),32,densities.data());
        const auto f=scene.fog_color;gl->Uniform4f(uniform(effects_program,"fog_color"),float(f&31)/31,float((f>>5)&31)/31,float((f>>10)&31)/31,float((f>>16)&31)/31);
        std::array<float,24> edge{};for(unsigned i=0;i<8;++i)for(unsigned j=0;j<3;++j)edge[i*3+j]=float((scene.edge[i]>>(j*5))&31)/31;
        gl->Uniform3fv(uniform(effects_program,"edge"),8,edge.data());
        const float vertices[]={-1,-1,0,0,1,-1,1,0,-1,1,0,1,-1,1,0,1,1,-1,1,0,1,1,1,1};
        gl->Disable(GL_DEPTH_TEST);gl->Disable(GL_BLEND);gl->DepthMask(GL_FALSE);
        gl->BindBuffer(GL_ARRAY_BUFFER,vbo);gl->BufferData(GL_ARRAY_BUFFER,sizeof(vertices),vertices,GL_STREAM_DRAW);
        gl->EnableVertexAttribArray(0);gl->VertexAttribPointer(0,4,GL_FLOAT,GL_FALSE,4*sizeof(float),nullptr);gl->DrawArrays(GL_TRIANGLES,0,6);
        width=previous_width;height=previous_height;
        gl->BindFramebuffer(GL_FRAMEBUFFER,0);gl->Viewport(0,0,width,height);gl->ActiveTexture(GL_TEXTURE0);active_target=nullptr;
        // A mip pyramid averages all covered high-resolution texels when the
        // 3D surface is reduced to the drawable, instead of point-sampling it.
        gl->BindTexture(GL_TEXTURE_2D,target.result);gl->GenerateMipmap(GL_TEXTURE_2D);
        return target;
    }
    void captured(const Scene& scene,const uint64_t* tags,Rect rect,bool opaque=true) {
        if(!tags||!scene.supported||scene.order.empty())return;
        std::vector<float> mapping(256*192*4);unsigned eligible=0;
        for(unsigned i=0;i<256*192;++i)if(tags[i]&&(tags[i]>>16)==scene.serial) {
            const auto pixel=unsigned(tags[i]&65535)-1;if(pixel>=256*192)continue;
            mapping[i*4]=(float(pixel%256)+.5f)/256;mapping[i*4+1]=(float(pixel/256)+.5f)/192;
            mapping[i*4+2]=scene.safe[pixel]?1.f:0.f;mapping[i*4+3]=1;eligible+=scene.safe[pixel]!=0;
        }
        if(!eligible)return;captured_pixel_count+=eligible;
        // Integer DS multiples avoid uneven raster samples. Supersampling
        // above drawable size provides antialiasing without buffering frames.
        scale=maximum_scale;
        auto& target=captured_target(scene,256*scale,192*scale,opaque);
        gl->UseProgram(captured_program);gl->ActiveTexture(GL_TEXTURE0);gl->BindTexture(GL_TEXTURE_2D,target.result);gl->Uniform1i(uniform(captured_program,"image"),0);
        gl->Uniform1i(uniform(captured_program,"opaque_output"),opaque);
        gl->ActiveTexture(GL_TEXTURE1);gl->BindTexture(GL_TEXTURE_2D,origin_texture);
        gl->TexParameteri(GL_TEXTURE_2D,GL_TEXTURE_MIN_FILTER,GL_NEAREST);gl->TexParameteri(GL_TEXTURE_2D,GL_TEXTURE_MAG_FILTER,GL_NEAREST);
        gl->TexParameteri(GL_TEXTURE_2D,GL_TEXTURE_WRAP_S,GL_CLAMP_TO_EDGE);gl->TexParameteri(GL_TEXTURE_2D,GL_TEXTURE_WRAP_T,GL_CLAMP_TO_EDGE);
        gl->TexImage2D(GL_TEXTURE_2D,0,GL_RGBA32F,256,192,0,GL_RGBA,GL_FLOAT,mapping.data());gl->Uniform1i(uniform(captured_program,"origins"),1);
        const float x0=2*rect.x/width-1,x1=2*(rect.x+rect.w)/width-1,y0=2*rect.y/height-1,y1=2*(rect.y+rect.h)/height-1;
        const float vertices[]={x0,y0,0,1,x1,y0,1,1,x0,y1,0,0,x0,y1,0,0,x1,y0,1,1,x1,y1,1,0};
        gl->Disable(GL_DEPTH_TEST);gl->Disable(GL_CULL_FACE);gl->DepthMask(GL_FALSE);
        if(opaque)gl->Disable(GL_BLEND);else {gl->Enable(GL_BLEND);gl->BlendFunc(GL_SRC_ALPHA,GL_ONE_MINUS_SRC_ALPHA);}
        gl->BindBuffer(GL_ARRAY_BUFFER,vbo);gl->BufferData(GL_ARRAY_BUFFER,sizeof(vertices),vertices,GL_STREAM_DRAW);
        gl->EnableVertexAttribArray(0);gl->VertexAttribPointer(0,4,GL_FLOAT,GL_FALSE,4*sizeof(float),nullptr);gl->DrawArrays(GL_TRIANGLES,0,6);
        gl->ActiveTexture(GL_TEXTURE0);
    }
    void blit(GLuint image,Box source,Rect destination,bool bottom_up,bool premultiplied=false,int brightness=0) {
        gl->UseProgram(flat_program);gl->ActiveTexture(GL_TEXTURE0);gl->BindTexture(GL_TEXTURE_2D,image);
        gl->Uniform1i(uniform(flat_program,"image"),0);gl->Uniform1i(uniform(flat_program,"brightness"),brightness);
        gl->Uniform1i(uniform(flat_program,"premultiplied"),premultiplied);
        const float x0=2*destination.x/width-1,x1=2*(destination.x+destination.w)/width-1;
        const float y0=2*destination.y/height-1,y1=2*(destination.y+destination.h)/height-1;
        const float u0=float(source.x)/256,u1=float(source.x+source.w)/256;
        float v0=float(source.y+source.h)/192,v1=float(source.y)/192;
        if(bottom_up){v0=1-v0;v1=1-v1;}
        const float vertices[]={x0,y0,u0,v0,x1,y0,u1,v0,x0,y1,u0,v1,x0,y1,u0,v1,x1,y0,u1,v0,x1,y1,u1,v1};
        gl->Disable(GL_DEPTH_TEST);gl->Disable(GL_CULL_FACE);gl->DepthMask(GL_FALSE);gl->Enable(GL_BLEND);
        gl->BlendFunc(premultiplied?GL_ONE:GL_SRC_ALPHA,GL_ONE_MINUS_SRC_ALPHA);
        gl->BindBuffer(GL_ARRAY_BUFFER,vbo);gl->BufferData(GL_ARRAY_BUFFER,sizeof(vertices),vertices,GL_STREAM_DRAW);
        gl->EnableVertexAttribArray(0);gl->VertexAttribPointer(0,4,GL_FLOAT,GL_FALSE,4*sizeof(float),nullptr);gl->DrawArrays(GL_TRIANGLES,0,6);
    }
    void native_pane(const uint32_t* pixels,Box source,Rect destination,bool lower) {
        gl->ActiveTexture(GL_TEXTURE0);upload(screen_texture,256,192,pixels,GL_BGRA);
        blit(screen_texture,source,destination,false);
        touch_regions.push_back({destination,source,lower});
    }
    bool dynamic(const Frame& frame) {
        if(!options.dynamic_widescreen||width<height||!frame.history||!frame.top_origins||!frame.bottom_origins)return false;
        // Follow the raster actually on the LCD, including CPU/VRAM captures,
        // rather than a newer submitted scene or POWCNT1 alone.
        std::map<std::pair<uint64_t,bool>,unsigned> counts;
        for(bool top:{false,true}) {
            const auto tags=top?frame.top_origins:frame.bottom_origins;
            for(unsigned i=0;i<256*192;++i)if(tags[i])++counts[{tags[i]>>16,top}];
        }
        const Scene* scene=nullptr;bool on_top=false;unsigned dominant=1024;
        for(const auto& s:*frame.history)if(s.widescreen&&s.supported&&
            std::any_of(s.polygons.begin(),s.polygons.end(),[](const auto& p){return world_polygon(p);}))
            for(bool top:{false,true})if(counts[{s.serial,top}]>dominant){scene=&s;on_top=top;dominant=counts[{s.serial,top}];}
        if(!scene) {
            // Complete framed 2D menus keep their 4:3 proportions. Unframed
            // pictures and movies retain both complete LCDs instead.
            const bool menu_bottom=layout_detail::full_window(frame.bottom);
            const bool menu_top=layout_detail::full_window(frame.top);
            if(!menu_bottom&&!menu_top)return false;
            layout_name="menu";const auto destination=fit(float(width),float(height),4.f/3);
            native_pane(menu_bottom?frame.bottom:frame.top,{0,0,256,192},destination,menu_bottom);
            const auto menu_tags=menu_bottom?frame.bottom_origins:frame.top_origins;
            for(const auto& s:*frame.history)captured(s,menu_tags,destination);
            const float margin=std::max(8.f,height/64.f),available=destination.x-2*margin;
            if(available>32){const float w=std::min(available,width*.24f);native_pane(menu_bottom?frame.top:frame.bottom,{0,0,256,192},{margin,height-margin-w*.75f,w,w*.75f},!menu_bottom);}
            return true;
        }
        const auto fg=on_top?frame.top_foreground:frame.bottom_foreground;
        const auto brightness=on_top?frame.top_brightness:frame.bottom_brightness;
        const auto tags=on_top?frame.top_origins:frame.bottom_origins;
        if(!fg||!brightness)return false;
        // A transformed captured picture or unsupported blending needs its
        // original mapping. Never silently drop UI in order to widen a scene.
        unsigned identity=0,opaque=0;
        for(unsigned i=0;i<256*192;++i){
            if(!(fg[i]&(1ull<<32))||(fg[i]&(1ull<<33)))return false;
            opaque+=uint8_t(fg[i]>>24)==255;
            identity+=tags[i]&&(tags[i]>>16)==scene->serial&&((tags[i]&65535)==i+1);
        }
        if(identity<dominant*9/10||!std::all_of(brightness,brightness+192,[&](uint8_t b){return b==brightness[0];}))return false;
        const float margin=std::max(8.f,height/64.f),ui_scale=height/384.f;
        const auto primary=on_top?frame.top:frame.bottom;
        const auto secondary=on_top?frame.bottom:frame.top;
        if(opaque>256*192*9/10) {
            layout_name="menu";const auto destination=fit(float(width),float(height),4.f/3);
            native_pane(primary,{0,0,256,192},destination,!on_top);
            for(const auto& s:*frame.history)captured(s,tags,destination);
            const float available=destination.x-2*margin;
            if(available>32){const float w=std::min(available,width*.24f);native_pane(secondary,{0,0,256,192},{margin,height-margin-w*.75f,w,w*.75f},on_top);}
            return true;
        }
        const float aspect=std::clamp(float(width)/height,4.f/3,4.f);
        const Rect canvas=fit(float(width),float(height),aspect);
        const int world_scale=std::max(1,std::min(maximum_scale,int(maximum_texture_size/(192*aspect))));scale=world_scale;
        auto& world=captured_target(*scene,int(std::ceil(192*world_scale*aspect)),192*world_scale,true,1,aspect);
        blit(world.result,{0,0,256,192},canvas,true,false,brightness[0]);
        captured_pixel_count=dominant;
        const int input_width=int(192*aspect);
        touch_regions.push_back({canvas,{(256-input_width)/2,0,input_width,192},!on_top});
        const auto party=on_top?layout_detail::party_band(secondary):Box{};
        layout_name=party.h?"battle":"field";
        if(party.h)native_pane(secondary,party,{margin,margin,party.w*ui_scale,party.h*ui_scale},true);
        else {
            const float w=std::min(width*.24f,height*.48f);
            const Rect map{margin,height-margin-w*.75f,w,w*.75f};
            native_pane(secondary,{0,0,256,192},map,on_top);
            const auto other_tags=on_top?frame.bottom_origins:frame.top_origins;
            for(const auto& s:*frame.history)captured(s,other_tags,map);
        }
        auto boxes=layout_detail::foreground_boxes(fg);
        for(const auto& p:scene->polygons)if(!world_polygon(p)&&!background_polygon(*scene,p)){
            const auto box=polygon_box(*scene,p);if(box.w&&box.h)boxes.push_back(box);
        }
        layout_detail::group(boxes);
        if(!boxes.empty()) {
            const int ui_resolution=std::min(maximum_scale,std::max(2,int(std::ceil(ui_scale*1.5f))));
            auto& overlay=captured_target(*scene,256*ui_resolution,192*ui_resolution,true,2);
            std::array<uint32_t,256*192> foreground{};
            for(size_t i=0;i<foreground.size();++i)foreground[i]=uint32_t(fg[i]);
            for(const auto b:boxes) {
                const bool dialogue=b.w>=190&&b.y+b.h>=155;
                const float w=b.w*ui_scale,h=b.h*ui_scale;
                Rect destination{dialogue?(width-w)/2:width-margin-w,
                    dialogue||b.y>=128?margin+(192-b.y-b.h)*ui_scale:height-margin-(b.y+b.h)*ui_scale,w,h};
                if(dialogue&&party.h) {
                    const float party_right=margin+party.w*ui_scale,party_top=margin+party.h*ui_scale;
                    if(destination.x<party_right+margin&&destination.y<party_top+margin) {
                        if(party_right+2*margin+w<=width)destination.x=party_right+margin;
                        else destination.y=party_top+margin;
                    }
                }
                blit(overlay.result,b,destination,true,false,brightness[0]);
                gl->ActiveTexture(GL_TEXTURE0);upload(screen_texture,256,192,foreground.data(),GL_BGRA);
                blit(screen_texture,b,destination,false,true,brightness[0]);
                touch_regions.push_back({destination,b,!on_top});
            }
        }
        return true;
    }
    bool wide_screens(const Frame& frame) {
        if(!options.dynamic_widescreen||width<height)return false;
        // Startup often puts a movie on one LCD and a tiny Start prompt on a
        // black second LCD. Enlarge the picture and place its controls below;
        // preserve every control pixel, including black glyphs inside buttons.
        std::array<uint64_t,256*192> content{};
        auto sparse=[&](const uint32_t* pixels,Box& box){
            unsigned count=0;
            for(size_t i=0;i<content.size();++i){const auto p=pixels[i];const bool active=((p>>16)&255)>8||((p>>8)&255)>8||(p&255)>8;
                content[i]=(1ull<<32)|(active?0xff000000ull:0);count+=active;}
            const auto boxes=layout_detail::foreground_boxes(content.data());box={};
            for(const auto b:boxes)box=box.w?layout_detail::unite(box,b):b;
            return count<256*192/8&&box.w*box.h<256*192/4;
        };
        Box bottom_box,top_box;
        const bool bottom_sparse=sparse(frame.bottom,bottom_box),top_sparse=sparse(frame.top,top_box);
        if(bottom_sparse!=top_sparse) {
            const bool picture_top=bottom_sparse;
            const auto picture=picture_top?frame.top:frame.bottom;
            const auto controls=picture_top?frame.bottom:frame.top;
            const auto box=picture_top?bottom_box:top_box;
            const auto destination=fit(float(width),float(height),4.f/3);
            layout_name="startup";native_pane(picture,{0,0,256,192},destination,true);
            const auto tags=picture_top?frame.top_origins:frame.bottom_origins;
            if(frame.history)for(const auto& scene:*frame.history)captured(scene,tags,destination);
            if(box.w&&box.h) {
                const float scale=height/384.f,margin=std::max(8.f,height/64.f);
                native_pane(controls,box,{(width-box.w*scale)/2,margin+(192-box.y-box.h)*scale,box.w*scale,box.h*scale},picture_top);
            }
            return true;
        }
        // When both pictures matter, show both at their original 4:3 ratio in
        // a landscape pair. This includes synchronized two-stream movies.
        layout_name="dual-wide";const auto total=fit(float(width),float(height),8.f/3);
        const Rect top{total.x,total.y,total.w/2,total.h},bottom{total.x+total.w/2,total.y,total.w/2,total.h};
        native_pane(frame.top,{0,0,256,192},top,false);native_pane(frame.bottom,{0,0,256,192},bottom,true);
        if(frame.history)for(const auto& scene:*frame.history){captured(scene,frame.top_origins,top);captured(scene,frame.bottom_origins,bottom);}
        return true;
    }
    void present(const Frame& frame) {
        check(frame.top&&frame.bottom,"missing DS video frames");captured_pixel_count=0;touch_regions.clear();layout_name="dual";
        if(!gl) {
            SDL_Rect top{0,0,256,192},bottom{0,192,256,192};
            check(SDL_UpdateTexture(software_texture,&top,frame.top,256*4)==0,SDL_GetError());
            check(SDL_UpdateTexture(software_texture,&bottom,frame.bottom,256*4)==0,SDL_GetError());
            SDL_RenderClear(software);SDL_RenderCopy(software,software_texture,nullptr,nullptr);
            SDL_GetRendererOutputSize(software,&width,&height);
            if(options.readback) {
                last_pixels.resize(size_t(width)*height);
                // SDL reads only the current viewport. Disable logical sizing
                // for a full-drawable capture, including the letterbox area.
                int logical_w,logical_h;SDL_RenderGetLogicalSize(software,&logical_w,&logical_h);
                check(SDL_RenderSetLogicalSize(software,0,0)==0,SDL_GetError());
                SDL_RenderSetViewport(software,nullptr);
                const int captured=SDL_RenderReadPixels(software,nullptr,SDL_PIXELFORMAT_ARGB8888,last_pixels.data(),width*4);
                const int restored=SDL_RenderSetLogicalSize(software,logical_w,logical_h);
                check(captured==0&&restored==0,SDL_GetError());
            }
            SDL_RenderPresent(software);return;
        }
        SDL_GL_GetDrawableSize(window,&width,&height);if(width<=0||height<=0)return;
        const bool has_3d=frame.scene&&frame.scene->supported&&!frame.scene->order.empty()&&frame.three_d&&
            std::any_of(frame.three_d,frame.three_d+256*192,[](uint8_t x){return x!=0;});
        gl->Viewport(0,0,width,height);gl->DepthMask(GL_TRUE);gl->ClearDepth(1);gl->ClearColor(0,0,0,1);gl->Clear(GL_COLOR_BUFFER_BIT|GL_DEPTH_BUFFER_BIT);
        if(frame.history)for(auto it=captured_targets.begin();it!=captured_targets.end();) {
            if(std::none_of(frame.history->begin(),frame.history->end(),[&](const Scene& s){return s.serial==it->first.first;})) {
                if(spare_targets.size()<4)spare_targets.push_back(it->second);else delete_target(it->second);
                it=captured_targets.erase(it);
            }else ++it;
        }
        if(!dynamic(frame)&&!wide_screens(frame)) {
            const auto total=fit(float(width),float(height),256.0F/384);
            Rect bottom{total.x,total.y,total.w,total.h/2},top{total.x,total.y+total.h/2,total.w,total.h/2};
            flat(frame.top,256,192,top);flat(frame.bottom,256,192,bottom);touch_rect=bottom;
            if(frame.history&&frame.top_origins&&frame.bottom_origins) {
                for(auto it=captured_targets.begin();it!=captured_targets.end();) {
                    if(std::none_of(frame.history->begin(),frame.history->end(),[&](const Scene& s){return s.serial==it->first.first;})) {
                        if(spare_targets.size()<2)spare_targets.push_back(it->second);else delete_target(it->second);
                        it=captured_targets.erase(it);
                    }else ++it;
                }
                for(const auto& scene:*frame.history) {captured(scene,frame.top_origins,top);captured(scene,frame.bottom_origins,bottom);}
            } else if(has_3d) {
                std::array<uint64_t,256*192> tags{};
                for(unsigned i=0;i<tags.size();++i)if(frame.three_d[i]&&frame.scene->safe[i])tags[i]=(frame.scene->serial<<16)|(i+1);
                captured(*frame.scene,tags.data(),frame.on_top?top:bottom,false);
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
}
bool Display::touch(int x,int y,int& ds_x,int& ds_y) const {
    if(impl_->software) {
        float lx,ly;SDL_RenderWindowToLogical(impl_->software,x,y,&lx,&ly);
        if(lx<0||lx>=256||ly<192||ly>=384)return false;
        ds_x=int(lx);ds_y=int(ly)-192;return true;
    }
    int ww,wh;SDL_GetWindowSize(impl_->window,&ww,&wh);if(ww<=0||wh<=0)return false;
    const float px=float(x)*impl_->width/ww,py=impl_->height-float(y)*impl_->height/wh;
    if(!impl_->touch_regions.empty()) {
        for(auto it=impl_->touch_regions.rbegin();it!=impl_->touch_regions.rend();++it) {
            const auto r=it->destination;
            if(r.w<=0||r.h<=0||px<r.x||px>=r.x+r.w||py<=r.y||py>r.y+r.h)continue;
            if(!it->enabled)return false;
            ds_x=std::clamp(it->source.x+int((px-r.x)*it->source.w/r.w),0,255);
            ds_y=std::clamp(it->source.y+int((r.y+r.h-py)*it->source.h/r.h),0,191);return true;
        }
        return false;
    }
    const auto r=impl_->touch_rect;
    if(r.w<=0||r.h<=0||px<r.x||px>=r.x+r.w||py<=r.y||py>r.y+r.h)return false;
    ds_x=std::clamp(int((px-r.x)*256/r.w),0,255);ds_y=std::clamp(int((r.y+r.h-py)*192/r.h),0,191);return true;
}
std::vector<uint32_t> Display::read_pixels() const{return impl_->last_pixels;}
int Display::width() const{return impl_->width;}
int Display::height() const{return impl_->height;}
const std::string& Display::renderer() const{return impl_->renderer_name;}
const std::string& Display::device() const{return impl_->device_name;}
uint64_t Display::polygons_drawn() const{return impl_->draws;}
uint64_t Display::captured_pixels() const{return impl_->captured_pixel_count;}
int Display::render_scale() const{return impl_->scale;}
float Display::world_aspect() const {
    if(!impl_->options.dynamic_widescreen||!impl_->gl)return 0;
    int w=0,h=0;SDL_GL_GetDrawableSize(impl_->window,&w,&h);
    return h>0?std::clamp(float(w)/h,4.f/3,4.f):0;
}
const std::string& Display::layout() const{return impl_->layout_name;}
}
