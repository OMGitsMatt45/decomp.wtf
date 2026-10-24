"""Small, revision-guarded adaptations of the copied PS1 runtime."""
from .codegen import retain_initializer


def replace(text,old,new):
    if text.count(old)!=1:raise ValueError('pinned PS1 runtime integration site differs: '+old[:80])
    return text.replace(old,new)


def patch(root):
    bios=root/'generated/OpenBIOS_dispatch.c'
    bios.write_text(retain_initializer(bios.read_text(encoding='utf-8'),'bios'),encoding='utf-8')
    bios=root/'generated/OpenBIOS_full.c'
    text=bios.read_text(encoding='utf-8-sig')
    text=replace(text,'void OpenBIOS_func_1FC06AE4(CPUState* cpu) {',
        'void OpenBIOS_func_1FC06AE4(CPUState* cpu) {\n    extern void decomp_openbios_config_defaults(CPUState*);\n    decomp_openbios_config_defaults(cpu);')
    bios.write_text(text,encoding='utf-8')
    path=root/'runtime/src/main.cpp'
    text=path.read_text(encoding='utf-8-sig')
    text=replace(text,'/* ---- SDL state ---- */',
        '/* ---- SDL state ---- */\nstatic void decomp_frame_end();\nstatic bool decomp_event(const SDL_Event&);\n'
        'static void decomp_opening_size(int*,int*,int,int);\nstatic void decomp_place_window(SDL_Window*);')
    text=replace(text,'    SDL_Rect bounds;\n    const int have_bounds =\n        (SDL_GetDisplayUsableBounds(0, &bounds) == 0 && bounds.w > 0 && bounds.h > 0);\n    psx_window_size(w, h, num, den, have_bounds,\n                    have_bounds ? bounds.w : 0, have_bounds ? bounds.h : 0);',
        '    decomp_opening_size(w,h,num,den);')
    text=replace(text,'int main(int argc, char** argv) {',
        '#include "decomp_host.hpp"\nint main(int argc, char** argv) {\n    decomp_parse(argc,argv);')
    text=replace(text,'    CPUState cpu;\n    std::memset(&cpu, 0, sizeof(cpu));',
        '    CPUState cpu;\n    decomp_cpu=&cpu;\n    std::memset(&cpu, 0, sizeof(cpu));')
    text=replace(text,'        frame_report_tick(s_frame_count);',
        '        frame_report_tick(s_frame_count);\n        decomp_frame_end();')
    text=replace(text,'static bool drain_host_events() {\n    SDL_Event ev;\n    while (SDL_PollEvent(&ev)) {',
        'static bool drain_host_events() {\n    SDL_Event ev;\n    while (SDL_PollEvent(&ev)) {\n        if(decomp_event(ev))continue;')
    text=replace(text,'    Uint32 win_flags = SDL_WINDOW_SHOWN | SDL_WINDOW_RESIZABLE;',
        '    if(decomp_fullscreen)g_fullscreen=1;\n    Uint32 win_flags = SDL_WINDOW_SHOWN | SDL_WINDOW_RESIZABLE;')
    text=replace(text,'    sdl_window = SDL_CreateWindow(\n        window_title.c_str(),',
        '    if(decomp_width){game_w=decomp_width;game_h=decomp_height;}\n    sdl_window = SDL_CreateWindow(\n        window_title.c_str(),')
    text=replace(text,'    psx_apply_window_icon(sdl_window, argv[0]);',
        '    decomp_place_window(sdl_window);\n    psx_apply_window_icon(sdl_window, argv[0]);')
    text=replace(text,'    if (!sdl_window) {\n        std::fprintf(stderr, "SDL_CreateWindow failed: %s\\n", SDL_GetError());',
        '''    if(!sdl_window && (win_flags & SDL_WINDOW_OPENGL) && !decomp_require_gpu) {
        std::fprintf(stderr,"decomp.wtf: OpenGL window unavailable; trying reported software fallback\\n");
        sdl_window=SDL_CreateWindow(window_title.c_str(),SDL_WINDOWPOS_CENTERED,SDL_WINDOWPOS_CENTERED,
            game_w,game_h,win_flags & ~(Uint32)SDL_WINDOW_OPENGL);
    }
    if (!sdl_window) {
        std::fprintf(stderr, "SDL_CreateWindow failed: %s\\n", SDL_GetError());''')
    text=replace(text,'    const int h = psx_sdl_display_pixel_height(window);',
        '''    int h=0,w=0;
    if(window)SDL_GL_GetDrawableSize(window,&w,&h);
    if(h<=0)h=psx_sdl_display_pixel_height(window);''')
    path.write_text(text,encoding='utf-8')
    path=root/'runtime/src/autocompile.c'
    text=path.read_text(encoding='utf-8-sig')
    text=replace(text,'void autocompile_configure(const char *cmd, const char *cwd) {',
        'void autocompile_configure(const char *cmd, const char *cwd) {\n#ifdef DECOMP_NO_RUNTIME_COMPILATION\n    cmd = NULL;\n#endif')
    text=replace(text,'int autocompile_request(void) {',
        'int autocompile_request(void) {\n#ifdef DECOMP_NO_RUNTIME_COMPILATION\n    return 0;\n#endif')
    path.write_text(text,encoding='utf-8')
