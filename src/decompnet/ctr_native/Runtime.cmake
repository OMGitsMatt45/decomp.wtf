cmake_minimum_required(VERSION 3.20)
project(CTRRuntimeProject LANGUAGES C)
set(CMAKE_C_STANDARD 11)
file(GLOB GAME_SOURCE CONFIGURE_DEPENDS "${CMAKE_CURRENT_SOURCE_DIR}/game/*.c")
add_library(ctr_game STATIC ${GAME_SOURCE})
target_include_directories(ctr_game PRIVATE game)
if(NOT MSVC)
  target_compile_options(ctr_game PRIVATE -fno-strict-aliasing)
endif()
find_program(CTR_CARGO cargo REQUIRED)
set(CTR_CARGO_TARGET "${CMAKE_CURRENT_BINARY_DIR}/host" CACHE PATH "Rust host build directory")
set(CTR_CARGO_PROFILE dev CACHE STRING "Cargo profile: dev or release")
option(CTR_DESKTOP "Build the adaptive Vulkan window and keyboard/touch frontend" ON)
if(CTR_DESKTOP)
  set(CTR_FEATURES --features desktop)
endif()
add_custom_target(ctr_runtime ALL
  COMMAND ${CMAKE_COMMAND} -E env
    "CTR_GAME_LIBRARY=$<TARGET_FILE:ctr_game>"
    "CARGO_TARGET_DIR=${CTR_CARGO_TARGET}"
    "CARGO_BUILD_JOBS=2"
    "CARGO_INCREMENTAL=0"
    "${CTR_CARGO}" build --locked --profile "${CTR_CARGO_PROFILE}" ${CTR_FEATURES}
    --manifest-path "${CMAKE_CURRENT_SOURCE_DIR}/native/app/Cargo.toml"
  DEPENDS ctr_game
  USES_TERMINAL VERBATIM)
add_custom_target(ctr_runtime_tests
  COMMAND ${CMAKE_COMMAND} -E env
    "CTR_GAME_LIBRARY=$<TARGET_FILE:ctr_game>"
    "CARGO_TARGET_DIR=${CTR_CARGO_TARGET}"
    "CARGO_BUILD_JOBS=2"
    "CARGO_INCREMENTAL=0"
    "${CTR_CARGO}" test --locked --profile "${CTR_CARGO_PROFILE}" ${CTR_FEATURES}
    --bin ctr_runtime --manifest-path "${CMAKE_CURRENT_SOURCE_DIR}/native/app/Cargo.toml"
  DEPENDS ctr_game
  USES_TERMINAL VERBATIM)
