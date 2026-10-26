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
# The large generated BIOS translation does not benefit from expensive O3
# optimization in normal builds. Preserve guest semantics and reasonable builds.
if(MSVC)
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
option(PS1_BUILD_REFERENCE "Build the separate optional interpreter reference" OFF)
function(decomp_add_player target native_only)
  psxrecomp_add_runtime_target(${target}
    GAME_GENERATED_FULL_C "${GAME_SOURCES};${GAME_DISPATCH}"
    GAME_GENERATED_DISPATCH_C "${CMAKE_CURRENT_SOURCE_DIR}/native/modules.c"
    PRELOADED_MODS_DIR NONE EXE_NAME ${target}
    DEFAULT_BIOS_PATH "bios/openbios.bin" DEFAULT_GAME_CONFIG_PATH "game.toml"
    WINDOW_TITLE "PS1 native PC game")
  target_include_directories(${target} PRIVATE native)
  target_sources(${target} PRIVATE native/copies.c)
  target_compile_definitions(${target} PRIVATE DECOMP_NO_RUNTIME_COMPILATION=1)
  get_target_property(_sources ${target} SOURCES)
  set(_kept "")
  set(_cpu_count 0)
  set(_main_count 0)
  foreach(_source IN LISTS _sources)
    get_filename_component(_absolute "${_source}" ABSOLUTE BASE_DIR "${CMAKE_CURRENT_SOURCE_DIR}")
    if(_absolute STREQUAL "${PSXRECOMP_ROOT}/runtime/src/dirty_ram_interp.c")
      math(EXPR _cpu_count "${_cpu_count}+1")
    elseif(native_only AND _absolute STREQUAL "${PSXRECOMP_ROOT}/runtime/src/main.cpp")
      math(EXPR _main_count "${_main_count}+1")
    else()
      list(APPEND _kept "${_source}")
    endif()
  endforeach()
  if(NOT _cpu_count EQUAL 1 OR (native_only AND NOT _main_count EQUAL 1))
    message(FATAL_ERROR "Pinned PS1 execution source layout differs")
  endif()
  set_property(TARGET ${target} PROPERTY SOURCES "${_kept}")
  if(native_only)
    target_sources(${target} PRIVATE native/static_main.cpp)
    set(_cpu "${CMAKE_CURRENT_SOURCE_DIR}/native/static_execution.c")
    set(_contract native-cps-entry-v1)
  else()
    set(_cpu "${PSXRECOMP_ROOT}/runtime/src/dirty_ram_interp.c")
    set(_contract reference-interpreter-v1)
  endif()
  # Both SDK timing profiles keep this target's CPU policy. The interpreter
  # is a distinct executable. Include wrappers and their actual bodies in
  # execution identity so snapshots cannot cross these CPU policies.
  psxrecomp_add_implementation(${target} NAME cpu-dispatch CONTRACT ${_contract}
    HLE_SOURCES "${_cpu}" LLE_SOURCES "${_cpu}"
    CONTRACT_FILES "${PSXRECOMP_ROOT}/runtime/src/dirty_ram_interp.c"
      "${PSXRECOMP_ROOT}/runtime/src/main.cpp"
      "${CMAKE_CURRENT_SOURCE_DIR}/native/decomp_host.hpp"
      "${CMAKE_CURRENT_SOURCE_DIR}/native/static_main.cpp")
  if(MSVC)
    target_compile_options(${target} PRIVATE /bigobj)
  endif()
  if(NOT WIN32 AND NOT APPLE)
    find_package(OpenGL QUIET)
    if(TARGET OpenGL::GL)
      target_link_libraries(${target} PRIVATE OpenGL::GL)
    elseif(SDL_UNIX_CONSOLE_BUILD)
      find_library(PS1_GL_LIBRARY NAMES GL libGL.so.1 REQUIRED)
      target_link_libraries(${target} PRIVATE "${PS1_GL_LIBRARY}")
    else()
      message(FATAL_ERROR "Install the OpenGL and X11 development packages listed in README.md")
    endif()
  endif()
  add_custom_command(TARGET ${target} POST_BUILD
    COMMAND "${CMAKE_COMMAND}" -E copy_if_different
      "${CMAKE_CURRENT_SOURCE_DIR}/game.toml" "$<TARGET_FILE_DIR:${target}>/game.toml"
    VERBATIM)
endfunction()
decomp_add_player(ps1_pc TRUE)
if(PS1_BUILD_REFERENCE)
  decomp_add_player(ps1_probe FALSE)
endif()
