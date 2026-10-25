cmake_minimum_required(VERSION 3.20)
project(GbaNativeProbe VERSION 0.1.0 LANGUAGES C CXX)
set(CMAKE_C_STANDARD 11)
set(CMAKE_CXX_STANDARD 20)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
if(MSVC)
  add_compile_options(/utf-8 $<$<COMPILE_LANGUAGE:CXX>:/Zc:__cplusplus>)
  add_compile_definitions(_CRT_SECURE_NO_WARNINGS NOMINMAX WIN32_LEAN_AND_MEAN)
endif()
set(SDK "${CMAKE_CURRENT_SOURCE_DIR}/runtime/anygba")
file(GLOB CORE CONFIGURE_DEPENDS "${SDK}/runtime/src/*.cpp")
file(GLOB HARDWARE CONFIGURE_DEPENDS
  "${SDK}/runtime/src/apu/*.cpp" "${SDK}/runtime/src/ppu/*.cpp"
  "${SDK}/runtime/src/bios/*.cpp" "${SDK}/runtime/src/save/*.cpp"
  "${SDK}/runtime/src/state/*.cpp" "${SDK}/runtime/src/interp/*.cpp"
  "${SDK}/tools/recomp/decode/*.cpp")
add_library(gba_runtime STATIC ${CORE} ${HARDWARE}
  "${SDK}/common/src/sha256.cpp" "${SDK}/common/src/crc32.cpp")
target_include_directories(gba_runtime PUBLIC "${SDK}/runtime/include" "${SDK}/common/include"
  PRIVATE "${SDK}/runtime/src" "${SDK}/tools/recomp")
target_compile_definitions(gba_runtime PRIVATE ANYGBA_VERSION="decomp.wtf-probe")
file(GLOB GAME CONFIGURE_DEPENDS "game/*.c")
add_executable(gba_probe native/main.cpp ${GAME})
target_include_directories(gba_probe PRIVATE game "${SDK}/runtime/src")
target_link_libraries(gba_probe PRIVATE gba_runtime)
include(CTest)
add_test(NAME usage COMMAND gba_probe --help)
