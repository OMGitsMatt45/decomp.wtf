file(GLOB generated CONFIGURE_DEPENDS "${DECOMP_PS2_PROBE_DIR}/generated/*.cpp")
if(NOT generated)
    message(FATAL_ERROR "Generate the original PS2 fixture first")
endif()
add_executable(ps2_cpu_probe "${DECOMP_PS2_PROBE_DIR}/runner.cpp" ${generated})
target_compile_features(ps2_cpu_probe PRIVATE cxx_std_20)
target_include_directories(ps2_cpu_probe BEFORE PRIVATE
    "${DECOMP_PS2_PROBE_DIR}"
    "${DECOMP_PS2_PROBE_DIR}/generated")
target_link_libraries(ps2_cpu_probe PRIVATE ps2_runtime)
if(MSVC)
    # Match the candidate runner's raylib / WinAPI CloseWindow workaround.
    target_link_options(ps2_cpu_probe PRIVATE /FORCE:MULTIPLE /STACK:8388608)
else()
    target_compile_options(ps2_cpu_probe PRIVATE -msse4.1)
endif()
