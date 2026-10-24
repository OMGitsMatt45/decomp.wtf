cmake_minimum_required(VERSION 3.24)
project(PS1Native LANGUAGES C CXX)
set(CMAKE_C_STANDARD 11)
set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
if(NOT CMAKE_BUILD_TYPE AND NOT CMAKE_CONFIGURATION_TYPES)
  set(CMAKE_BUILD_TYPE Release CACHE STRING "Build type" FORCE)
endif()
set(PSXRECOMP_ROOT "${CMAKE_CURRENT_SOURCE_DIR}/runtime/psxrecomp")
set(PSX_RECOMP_UI OFF CACHE BOOL "" FORCE)
set(PSX_NETPLAY OFF CACHE BOOL "" FORCE)
set(PSX_REWIND OFF CACHE BOOL "" FORCE)
set(PSX_OPENXR OFF CACHE BOOL "" FORCE)
set(PSX_ENABLE_VULKAN OFF CACHE BOOL "" FORCE)
set(PSX_DEBUG_TOOLS OFF CACHE BOOL "" FORCE)
set(PSXRECOMP_BIOS_STEMS OpenBIOS CACHE STRING "" FORCE)
include("${PSXRECOMP_ROOT}/runtime/runtime.cmake")
file(GLOB_RECURSE GAME_SOURCES CONFIGURE_DEPENDS "${CMAKE_CURRENT_SOURCE_DIR}/game/*_full_*.c")
file(GLOB_RECURSE GAME_DISPATCH CONFIGURE_DEPENDS "${CMAKE_CURRENT_SOURCE_DIR}/game/*_dispatch.c")
psxrecomp_add_runtime_target(ps1_pc
  GAME_GENERATED_FULL_C "${GAME_SOURCES};${GAME_DISPATCH}"
  GAME_GENERATED_DISPATCH_C "${CMAKE_CURRENT_SOURCE_DIR}/native/modules.c"
  PRELOADED_MODS_DIR NONE EXE_NAME ps1_pc
  DEFAULT_BIOS_PATH "bios/openbios.bin" DEFAULT_GAME_CONFIG_PATH "game.toml"
  WINDOW_TITLE "PS1 native PC game")
target_include_directories(ps1_pc PRIVATE native)
target_compile_definitions(ps1_pc PRIVATE DECOMP_NO_RUNTIME_COMPILATION=1)
# The large generated BIOS translation does not benefit from expensive O3
# optimization in normal builds. Preserve guest semantics and reasonable builds.
if(MSVC)
  target_compile_options(ps1_pc PRIVATE /bigobj)
  # The pinned runtime enables MSVC atomics for audio_trace.c only, while these
  # newer device/thread sources also include stdatomic.h. Scope the switch to
  # C sources so Visual Studio does not leak it into the mixed C++ target.
  foreach(unit guest_tty render_thread starvation_ring host_overlay gpu_gl_renderer host_span_ring)
    set_property(SOURCE "${PSXRECOMP_ROOT}/runtime/src/${unit}.c"
      APPEND PROPERTY COMPILE_OPTIONS /experimental:c11atomics)
  endforeach()
  set_source_files_properties("${PSXRECOMP_ROOT}/generated/OpenBIOS_full.c" PROPERTIES COMPILE_OPTIONS /O1)
else()
  set_source_files_properties("${PSXRECOMP_ROOT}/generated/OpenBIOS_full.c" PROPERTIES COMPILE_OPTIONS -O1)
endif()
# CMake diagnoses missing desktop graphics dependencies before a final link.
if(NOT WIN32 AND NOT APPLE)
  find_package(OpenGL QUIET)
  if(TARGET OpenGL::GL)
    target_link_libraries(ps1_pc PRIVATE OpenGL::GL)
  elseif(SDL_UNIX_CONSOLE_BUILD)
    # Developer headless qualification on hosts with runtime libraries only.
    find_library(PS1_GL_LIBRARY NAMES GL libGL.so.1 REQUIRED)
    target_link_libraries(ps1_pc PRIVATE "${PS1_GL_LIBRARY}")
  else()
    message(FATAL_ERROR "Install the OpenGL and X11 development packages listed in README.md")
  endif()
endif()
# Keep release/debug layouts equally usable, including launches from another cwd.
add_custom_command(TARGET ps1_pc POST_BUILD
  COMMAND "${CMAKE_COMMAND}" -E copy_if_different
    "${CMAKE_CURRENT_SOURCE_DIR}/game.toml" "$<TARGET_FILE_DIR:ps1_pc>/game.toml"
  VERBATIM)
