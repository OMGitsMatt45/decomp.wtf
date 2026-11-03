"""Small, revision-guarded adaptations of the copied PS1 runtime."""
from importlib import resources
from .codegen import retain_initializer
from . import execution_policy


def replace(text,old,new):
    if text.count(old)!=1:raise ValueError('pinned PS1 runtime integration site differs: '+old[:80])
    return text.replace(old,new)


def keyboard_sampling(text,header):
    """Keep quick SDL keyboard presses for a bounded number of pad samples."""
    marker='static uint8_t s_suppressed[PSXKB_MAX_PLAYERS][PSXKB_MOUSE_SC_BASE + 6];'
    text=replace(text,marker,marker+r'''
static uint8_t decomp_pulse_next[PSXKB_MAX_PLAYERS][SDL_NUM_SCANCODES];
static uint8_t decomp_pulse_current[PSXKB_MAX_PLAYERS][SDL_NUM_SCANCODES];
static uint8_t decomp_tap_frames=1;
void decomp_keybinds_set_tap_frames(unsigned frames) {
    if(frames>=1&&frames<=30)decomp_tap_frames=(uint8_t)frames;
}
void decomp_keybinds_note_keydown(SDL_Scancode sc) {
    if((int)sc<=0||(int)sc>=SDL_NUM_SCANCODES)return;
    for(int slot=0;slot<PSXKB_MAX_PLAYERS;slot++)
        if(!s_suppressed[slot][sc])decomp_pulse_next[slot][sc]=1;
}
void decomp_keybinds_begin_sample(void) {
    for(int slot=0;slot<PSXKB_MAX_PLAYERS;slot++)
        for(int sc=0;sc<SDL_NUM_SCANCODES;sc++) {
            uint8_t *current=&decomp_pulse_current[slot][sc];
            if(decomp_pulse_next[slot][sc])*current=decomp_tap_frames;
            else if(*current)--*current;
        }
    memset(decomp_pulse_next,0,sizeof(decomp_pulse_next));
}
void decomp_keybinds_clear_pulses(void) {
    memset(decomp_pulse_current,0,sizeof(decomp_pulse_current));
    memset(decomp_pulse_next,0,sizeof(decomp_pulse_next));
}
''')
    text=replace(text,'        s_suppressed[player - 1][(int)sc] = 1;',
        '''        {s_suppressed[player - 1][(int)sc] = 1;
         if((int)sc<SDL_NUM_SCANCODES){
             decomp_pulse_current[player-1][sc]=0;decomp_pulse_next[player-1][sc]=0;}}
''')
    text=replace(text,'(int)sc < SDL_NUM_SCANCODES && keys[sc];',
        '(int)sc < SDL_NUM_SCANCODES && (keys[sc] || decomp_pulse_current[slot][sc]);')
    header=replace(header,'#ifdef __cplusplus\n}\n#endif',
        'void decomp_keybinds_note_keydown(SDL_Scancode sc);\n'
        'void decomp_keybinds_set_tap_frames(unsigned frames);\n'
        'void decomp_keybinds_begin_sample(void);\nvoid decomp_keybinds_clear_pulses(void);\n'
        '#ifdef __cplusplus\n}\n#endif')
    return text,header


def patch(root):
    keys=root/'runtime/src/psx_keybinds.c';key_header=root/'runtime/include/psx_keybinds.h'
    body,header=keyboard_sampling(keys.read_text(encoding='utf-8-sig'),key_header.read_text(encoding='utf-8-sig'))
    keys.write_text(body,encoding='utf-8');key_header.write_text(header,encoding='utf-8')
    config=root/'recompiler/src/config_loader.h'
    text=config.read_text(encoding='utf-8-sig')
    text=replace(text,'int                   video_depth24_trailing_margin = 8;',
        'int                   video_depth24_trailing_margin = 0;')
    config.write_text(text,encoding='utf-8')
    execution=root/'runtime/src/dirty_ram_interp.c'
    execution.write_text(execution_policy.patch(execution.read_text(encoding='utf-8-sig')),encoding='utf-8')
    bios=root/'generated/OpenBIOS_dispatch.c'
    text=retain_initializer(bios.read_text(encoding='utf-8'),'bios')
    bridge=resources.files(__package__).joinpath('kernel_stubs.inc').read_text(encoding='utf-8')
    text=replace(text,'static int psx_bios_try_native_call_stub(CPUState* cpu, uint32_t addr) {',
        bridge+'\nstatic int psx_bios_try_native_call_stub(CPUState* cpu, uint32_t addr) {')
    text=replace(text,'        /* Byte-guarded A0/B0/C0 call-vector tail stubs. */',
        '        if (!found && decomp_psx_kernel_stub(cpu,addr,\n'
        '            OpenBIOS_psx_bios_kernel_patch_ranges,OpenBIOS_psx_bios_kernel_patch_range_count))found=1;\n'
        '        /* Byte-guarded A0/B0/C0 call-vector tail stubs. */')
    bios.write_text(text,encoding='utf-8')
    bios=root/'generated/OpenBIOS_full.c'
    text=bios.read_text(encoding='utf-8-sig')
    text=replace(text,'void OpenBIOS_func_1FC06AE4(CPUState* cpu) {',
        'void OpenBIOS_func_1FC06AE4(CPUState* cpu) {\n    extern void decomp_openbios_config_defaults(CPUState*);\n    decomp_openbios_config_defaults(cpu);')
    bios.write_text(text,encoding='utf-8')
    path=root/'runtime/src/main.cpp'
    text=path.read_text(encoding='utf-8-sig')
    # A CPU-upload coverage heuristic cannot identify pixels rendered/copied
    # entirely inside VRAM. Preserve the full 24-bit scanout by default;
    # explicit game configuration can still request a trailing margin.
    text=replace(text,'static int           g_video_depth24_trailing_margin = 8;',
        'static int           g_video_depth24_trailing_margin = 0;')
    text=replace(text,'/* ---- SDL state ---- */',
        '/* ---- SDL state ---- */\nstatic void decomp_frame_end();\nstatic int decomp_script_input();\nstatic bool decomp_event(const SDL_Event&);\nstatic void decomp_input_trace(int);\n'
        'static void decomp_opening_size(int*,int*,int,int);\nstatic void decomp_place_window(SDL_Window*);\n'
        'static bool decomp_bounded_run();')
    text=replace(text,'static bool frontend_unattended() { return g_headless || g_hidden_window; }',
        'static bool frontend_unattended() { return g_headless || g_hidden_window || decomp_bounded_run(); }')
    # The source-shipped menu also edits settings when recomp-ui is absent.
    text=replace(text,'        g_overlay_settings_path = settings_path;\n#endif',
        '#endif\n        g_overlay_settings_path = settings_path;')
    text=replace(text,'            (void)quality_save_user_settings(g_overlay_settings_path, us);',
        '            if (!us.parse_error) (void)quality_save_user_settings(g_overlay_settings_path, us);')
    text=replace(text,'    SDL_Rect bounds;\n    const int have_bounds =\n        (SDL_GetDisplayUsableBounds(0, &bounds) == 0 && bounds.w > 0 && bounds.h > 0);\n    psx_window_size(w, h, num, den, have_bounds,\n                    have_bounds ? bounds.w : 0, have_bounds ? bounds.h : 0);',
        '    decomp_opening_size(w,h,num,den);')
    text=replace(text,'int main(int argc, char** argv) {',
        '#include "decomp_host.hpp"\nint main(int argc, char** argv) {\n    decomp_parse(argc,argv);')
    text=replace(text,'    CPUState cpu;\n    std::memset(&cpu, 0, sizeof(cpu));',
        '    CPUState cpu;\n    decomp_cpu=&cpu;\n    std::memset(&cpu, 0, sizeof(cpu));')
    text=replace(text,'        frame_report_tick(s_frame_count);',
        '        frame_report_tick(s_frame_count);\n        decomp_frame_end();\n'
        '        const int scripted_input=decomp_script_input();\n'
        '        if(scripted_input>=0)override=scripted_input;')
    text=replace(text,'static bool drain_host_events() {\n    SDL_Event ev;\n    while (SDL_PollEvent(&ev)) {',
        'static bool drain_host_events() {\n    SDL_Event ev;\n    while (SDL_PollEvent(&ev)) {\n        if(decomp_event(ev))continue;')
    if text.count('sample_pad_into_sio(override);')!=2:
        raise ValueError('pinned PS1 pad sampling sites differ')
    text=text.replace('sample_pad_into_sio(override);',
        '{sample_pad_into_sio(override);decomp_input_trace(override);}')
    text=replace(text,"    /* Sample each player's device and feed the matching SIO pad slot.",
        "    decomp_keybinds_begin_sample();\n    /* Sample each player's device and feed the matching SIO pad slot.")
    text=replace(text,'if (!repeat && host_keymap_match_event(HOST_KEYMAP_OPEN_LAUNCHER, key, scan, mod))',
        'if (!repeat && (key == SDLK_F1 || host_keymap_match_event(HOST_KEYMAP_OPEN_LAUNCHER, key, scan, mod)))')
    for key,keypad,action in (('UP','8','UP'),('DOWN','2','DOWN'),('LEFT','4','LEFT'),('RIGHT','6','RIGHT')):
        text=replace(text,f'else if (key == SDLK_{key}) psx_runtime_menu_input(PSX_MENU_{action}, repeat);',
            f'else if (key == SDLK_{key} || key == SDLK_KP_{keypad}) psx_runtime_menu_input(PSX_MENU_{action}, repeat);')
    text=replace(text,'    Uint32 win_flags = SDL_WINDOW_SHOWN | SDL_WINDOW_RESIZABLE;',
        '    if(decomp_fullscreen)g_fullscreen=1;\n    Uint32 win_flags = SDL_WINDOW_SHOWN | SDL_WINDOW_RESIZABLE;')
    text=replace(text,'    sdl_window = SDL_CreateWindow(\n        window_title.c_str(),',
        '    if(decomp_width){game_w=decomp_width;game_h=decomp_height;}\n    sdl_window = SDL_CreateWindow(\n        window_title.c_str(),')
    text=replace(text,'    psx_apply_window_icon(sdl_window, argv[0]);',
        '    decomp_place_window(sdl_window);\n    psx_apply_window_icon(sdl_window, argv[0]);')
    # Give compile-time policy constants static storage: MSVC otherwise treats
    # their use in the captured launch callback's static_assert as a runtime read.
    for name in ('frame_interpolation_offered','skip_fmv_offered'):
        text=replace(text,f'    constexpr bool {name} = false;',f'    static constexpr bool {name} = false;')
    text=replace(text,'    if (!sdl_window) {\n        std::fprintf(stderr, "SDL_CreateWindow failed: %s\\n", SDL_GetError());',
        '''    if(!sdl_window && (win_flags & SDL_WINDOW_OPENGL) && !decomp_require_gpu) {
        std::fprintf(stderr,"decomp.wtf: OpenGL window unavailable; trying reported software fallback\\n");
        sdl_window=SDL_CreateWindow(window_title.c_str(),SDL_WINDOWPOS_CENTERED,SDL_WINDOWPOS_CENTERED,
            game_w,game_h,win_flags & ~(Uint32)SDL_WINDOW_OPENGL);
    }
    if (!sdl_window) {
        if(decomp_require_gpu)decomp_gpu_error();
        std::fprintf(stderr, "SDL_CreateWindow failed: %s\\n", SDL_GetError());''')
    text=replace(text,'    if (!sdl_renderer) {\n        std::fprintf(stderr, "SDL_CreateRenderer failed: %s\\n", SDL_GetError());',
        '''    if(!sdl_renderer) {
        SDL_SetHint(SDL_HINT_RENDER_DRIVER,"software");
        sdl_renderer=SDL_CreateRenderer(sdl_window,-1,SDL_RENDERER_SOFTWARE);
    }
    if (!sdl_renderer) {
        std::fprintf(stderr, "SDL_CreateRenderer failed: %s\\n", SDL_GetError());''')
    text=replace(text,'    const int h = psx_sdl_display_pixel_height(window);',
        '''    int h=0,w=0;
    if(window)SDL_GL_GetDrawableSize(window,&w,&h);
    if(h<=0)h=psx_sdl_display_pixel_height(window);''')
    path.write_text(text,encoding='utf-8')
    path=root/'runtime/src/gpu_gl_renderer.c'
    text=path.read_text(encoding='utf-8-sig')
    text=replace(text,'static int s_pgxp_render_wanted = 0;', 'static atomic_int s_pgxp_render_wanted = 0;')
    text=replace(text,'    __atomic_store_n(&s_pgxp_render_wanted,\n                     (s_pgxp_depth || s_pgxp_cpersp || s_pgxp_seam || s_bcls_on) ? 1 : 0,\n                     __ATOMIC_RELEASE);',
        '    atomic_store_explicit(&s_pgxp_render_wanted,\n                     (s_pgxp_depth || s_pgxp_cpersp || s_pgxp_seam || s_bcls_on) ? 1 : 0,\n                     memory_order_release);')
    text=replace(text,'    return __atomic_load_n(&s_pgxp_render_wanted, __ATOMIC_ACQUIRE);',
        '    return atomic_load_explicit(&s_pgxp_render_wanted, memory_order_acquire);')
    path.write_text(text,encoding='utf-8')
    path=root/'runtime/src/autocompile.c'
    text=path.read_text(encoding='utf-8-sig')
    text=replace(text,'void autocompile_configure(const char *cmd, const char *cwd) {',
        'void autocompile_configure(const char *cmd, const char *cwd) {\n#ifdef DECOMP_NO_RUNTIME_COMPILATION\n    cmd = NULL;\n#endif')
    text=replace(text,'int autocompile_request(void) {',
        'int autocompile_request(void) {\n#ifdef DECOMP_NO_RUNTIME_COMPILATION\n    return 0;\n#endif')
    path.write_text(text,encoding='utf-8')
    path=root/'runtime/src/disc_identity.cpp'
    text=path.read_text(encoding='utf-8-sig')
    text=replace(text,'    // Expect 4 letters + 5 digits.',
        '    // Match the importer: P is also a valid executable-name separator.\n'
        "    if (s.size() == 10 && s[4] == 'P') s.erase(4, 1);\n"
        '    // Expect 4 letters + 5 digits.')
    path.write_text(text,encoding='utf-8')
