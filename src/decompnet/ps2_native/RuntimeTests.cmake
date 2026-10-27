# Tests from the same pinned, source-shipped runtime linked by the native game.
option(DECOMP_PS2_BUILD_RUNTIME_TESTS "Build pinned IOP/VU/IRQ/media runtime checks" OFF)
if(DECOMP_PS2_BUILD_RUNTIME_TESTS)
  if(NOT DECOMP_PS2_REFERENCE)
    message(FATAL_ERROR "Configure the pinned instruction-reference suites in a separate build with -DDECOMP_PS2_REFERENCE=ON; native execution probes use -DDECOMP_PS2_BUILD_NATIVE_TESTS=ON")
  endif()
  set(PS2_TEST_ROOT "${PORT_ROOT}/thirdparty/PS2Recomp/ps2xTest")
  set(PS2_RUNTIME_SUITES
    pad_input ps2_runtime_io ps2_runtime_kernel ps2_runtime_interrupt ee_fiber
    ps2_memory ps2_vu1 ps2_vu1_upper_engine ps2_vu1_program ps2_vu ps2_gs
    ps2_iop ps2_native_iop ps2_sif_rpc ps2_sif_dma ps2_runtime_expansion)
  set(PS2_RUNTIME_TEST_SOURCES "${PS2_TEST_ROOT}/src/test_function_table.cpp")
  foreach(suite IN LISTS PS2_RUNTIME_SUITES)
    list(APPEND PS2_RUNTIME_TEST_SOURCES "${PS2_TEST_ROOT}/src/${suite}_tests.cpp")
  endforeach()
  add_executable(ps2_runtime_tests tests/runtime.cpp tests/irx.cpp ${PS2_RUNTIME_TEST_SOURCES})
  target_include_directories(ps2_runtime_tests PRIVATE "${PS2_TEST_ROOT}/include"
    "${PORT_ROOT}/thirdparty/PS2Recomp/ps2xRuntime/src/lib"
    "${PORT_ROOT}/thirdparty/PS2Recomp/ps2xIOP/src")
  target_link_libraries(ps2_runtime_tests PRIVATE ps2_runtime ps2_recomp_lib)
  if(UNIX AND NOT APPLE)
    target_link_libraries(ps2_runtime_tests PRIVATE ${CMAKE_DL_LIBS})
  endif()
  if(MSVC)
    target_compile_options(ps2_runtime_tests PRIVATE /bigobj)
    target_link_options(ps2_runtime_tests PRIVATE /STACK:8388608)
    target_sources(ps2_runtime_tests PRIVATE native/utf8.manifest)
  endif()
  ps2x_stage_ffmpeg_runtime_dlls(ps2_runtime_tests)
endif()
