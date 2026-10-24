add_executable(decomp_ps2_gs_probe "${DECOMP_PS2_GS_PROBE}/probe.cpp")
target_link_libraries(decomp_ps2_gs_probe PRIVATE parallel-gs)
