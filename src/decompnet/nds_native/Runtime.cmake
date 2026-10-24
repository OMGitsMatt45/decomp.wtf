# Build the pinned MIT DQ9-Decomp runtime, with decomp.wtf's generic host.
# The full upstream runtime source, LICENSE and NOTICE ship in native/dsr.
set(DSR_ROOT "${CMAKE_CURRENT_SOURCE_DIR}/native/dsr")
if(NOT CMAKE_SIZEOF_VOID_P EQUAL 8 OR NOT CMAKE_SYSTEM_PROCESSOR MATCHES "^(x86_64|AMD64|amd64)$")
  message(FATAL_ERROR "This pinned DS runtime currently requires an x86-64 host")
endif()
add_library(ds_runtime STATIC
  ${DSR_ROOT}/runtime/core/src/abi_config.cpp
  ${DSR_ROOT}/runtime/core/src/machine.cpp
  ${DSR_ROOT}/runtime/core/src/render_frame.cpp
  ${DSR_ROOT}/runtime/core/src/cpu.cpp
  ${DSR_ROOT}/runtime/core/src/bus.cpp
  ${DSR_ROOT}/runtime/core/src/io.cpp
  ${DSR_ROOT}/runtime/core/src/timing.cpp
  ${DSR_ROOT}/runtime/core/src/scheduler.cpp
  ${DSR_ROOT}/runtime/core/src/runtime.cpp
  ${DSR_ROOT}/runtime/core/src/swi.cpp
  ${DSR_ROOT}/runtime/core/src/thread.cpp
  ${DSR_ROOT}/runtime/core/src/fiber.cpp
  ${DSR_ROOT}/runtime/gpu2d/src/gpu2d.cpp
  ${DSR_ROOT}/runtime/gpu3d/src/gpu3d.cpp
  ${DSR_ROOT}/runtime/gpu3d/src/gpu2d_adapter.cpp
  ${DSR_ROOT}/runtime/gpu3d/src/texture.cpp
  ${DSR_ROOT}/runtime/gpu3d/src/texture_rgba.cpp
  ${DSR_ROOT}/runtime/spu/src/spu.cpp
  ${DSR_ROOT}/runtime/periph/src/periph.cpp
  ${DSR_ROOT}/runtime/session/session.cpp
  ${DSR_ROOT}/runtime/session/session_rom.cpp)
target_include_directories(ds_runtime PUBLIC ${DSR_ROOT}/runtime/include
  ${DSR_ROOT}/runtime/core/include PRIVATE ${DSR_ROOT}/runtime/core/src)
target_compile_features(ds_runtime PUBLIC cxx_std_20)
find_package(Threads REQUIRED)
target_link_libraries(ds_runtime PUBLIC Threads::Threads)
if(WIN32)
  target_compile_definitions(ds_runtime PUBLIC WIN32_LEAN_AND_MEAN NOMINMAX SDL_MAIN_HANDLED)
  target_link_libraries(ds_runtime PRIVATE bcrypt)
  if(MSVC)
    target_compile_options(ds_runtime PRIVATE /fp:strict)
  else()
    target_compile_options(ds_runtime PRIVATE -ffp-contract=off)
  endif()
else()
  enable_language(ASM)
  target_sources(ds_runtime PRIVATE ${DSR_ROOT}/runtime/core/src/fiber_context.S)
endif()

option(NDS_WITH_SDL "Build the window, keyboard/touch and audio frontend" ON)
if(NDS_WITH_SDL)
  include(FetchContent)
  set(SDL_SHARED OFF CACHE BOOL "" FORCE)
  set(SDL_STATIC ON CACHE BOOL "" FORCE)
  set(SDL_TEST OFF CACHE BOOL "" FORCE)
  set(SDL_TESTS OFF CACHE BOOL "" FORCE)
  FetchContent_Declare(SDL2
    URL https://github.com/libsdl-org/SDL/releases/download/release-2.32.10/SDL2-2.32.10.tar.gz
    URL_HASH SHA256=5f5993c530f084535c65a6879e9b26ad441169b3e25d789d83287040a9ca5165)
  FetchContent_MakeAvailable(SDL2)
  target_link_libraries(ds_pc PRIVATE SDL2::SDL2-static)
  target_compile_definitions(ds_pc PRIVATE NDS_WITH_SDL SDL_MAIN_HANDLED)
endif()
