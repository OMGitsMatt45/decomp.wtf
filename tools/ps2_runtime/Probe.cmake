cmake_minimum_required(VERSION 3.24)
project(DecompPS2CPUProbe LANGUAGES C CXX)
file(GLOB generated CONFIGURE_DEPENDS "${CMAKE_CURRENT_SOURCE_DIR}/generated/*.cpp")
if(NOT generated)
    message(FATAL_ERROR "Generate the original PS2 fixture first")
endif()
add_executable(ps2_cpu_probe runner.cpp ${generated})
target_compile_features(ps2_cpu_probe PRIVATE cxx_std_20)
target_include_directories(ps2_cpu_probe BEFORE PRIVATE
    "${CMAKE_CURRENT_SOURCE_DIR}"
    "${CMAKE_CURRENT_SOURCE_DIR}/generated")
target_link_libraries(ps2_cpu_probe PRIVATE ps2_runtime)
if(MSVC)
    # Match the candidate runner's raylib / WinAPI CloseWindow workaround.
    target_link_options(ps2_cpu_probe PRIVATE /FORCE:MULTIPLE /STACK:8388608)
else()
    target_compile_options(ps2_cpu_probe PRIVATE -msse4.1)
endif()
