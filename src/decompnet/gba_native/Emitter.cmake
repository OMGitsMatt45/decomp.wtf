cmake_minimum_required(VERSION 3.20)
project(GbaEmitter VERSION 0.3.0 LANGUAGES C CXX)
set(CMAKE_CXX_STANDARD 20)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
if(MSVC)
  add_compile_options(/utf-8 /Zc:__cplusplus /permissive-)
endif()
include(FetchContent)
FetchContent_Declare(tomlplusplus
  URL https://raw.githubusercontent.com/marzer/tomlplusplus/v3.4.0/toml.hpp
  URL_HASH SHA256=6b5172ad4dd6519aec67b919181fa7a38a2234131e5b2afa232dfe444819783e
  DOWNLOAD_NO_EXTRACT TRUE)
FetchContent_MakeAvailable(tomlplusplus)
add_library(tomlplusplus INTERFACE)
target_include_directories(tomlplusplus SYSTEM INTERFACE "${tomlplusplus_SOURCE_DIR}")
add_library(tomlplusplus::tomlplusplus ALIAS tomlplusplus)
function(anygba_configure_target target)
endfunction()
add_subdirectory("${GBA_SDK}/common" common)
add_subdirectory("${GBA_SDK}/tools/recomp" recomp)
# Hardware events must observe completed instructions, including memory writes.
# Batching an entire basic block lets DMA/audio see writes before their cycles.
file(READ "${GBA_SDK}/tools/recomp/codegen/c_emitter.cpp" EMITTER_SOURCE)
string(REPLACE "        emit_instruction(in);"
  "        emit_instruction(in);\n        if (!is_control(in)) flush_cycles(in.next());"
  EMITTER_PRECISE "${EMITTER_SOURCE}")
if(EMITTER_PRECISE STREQUAL EMITTER_SOURCE)
  message(FATAL_ERROR "GBA instruction timing patch no longer applies")
endif()
# A load's additional bus phase precedes the sampled value. Charging it after
# the read made live timer observations one cycle early (independently checked
# against mGBA with zero, one and sixteen intervening ARM instructions).
string(REPLACE "case Op::LDR: case Op::LDRB: case Op::LDRH: case Op::LDRSB: case Op::LDRSH: return 1;"
  "case Op::LDR: case Op::LDRB: case Op::LDRH: case Op::LDRSB: case Op::LDRSH: return 0;"
  EMITTER_PRECISE "${EMITTER_PRECISE}")
string(REPLACE "        line(\"AG_ENTER_RAM(c, %s, %d);\", hex(fn_.entry).c_str(), fn_.mode == analysis::Mode::Thumb ? 1 : 0);"
  "        const auto footprint = code_footprint(fn_, options_.image);\n        const auto source = options_.image ? options_.image->rom_offset(footprint.begin, footprint.end-footprint.begin) : std::nullopt;\n        line(\"if (!anygba_ram_variant_valid(c, %s, %s, %s)) { c->r[15]=%s; return; }\", hex(footprint.begin).c_str(), hex(footprint.end).c_str(), hex(source ? analysis::kRomBase+*source : 0).c_str(), hex(fn_.entry).c_str());"
  EMITTER_PRECISE "${EMITTER_PRECISE}")
set(PRECISE_SOURCE "${CMAKE_CURRENT_BINARY_DIR}/precise_emitter.cpp")
file(CONFIGURE OUTPUT "${PRECISE_SOURCE}" CONTENT "${EMITTER_PRECISE}" @ONLY)
get_target_property(RECOMP_SOURCES anygba_recomp_lib SOURCES)
set(PRECISE_SOURCES)
foreach(source IN LISTS RECOMP_SOURCES)
  if(source STREQUAL "codegen/c_emitter.cpp")
    list(APPEND PRECISE_SOURCES "${PRECISE_SOURCE}")
  else()
    list(APPEND PRECISE_SOURCES "${GBA_SDK}/tools/recomp/${source}")
  endif()
endforeach()
set_property(TARGET anygba_recomp_lib PROPERTY SOURCES "${PRECISE_SOURCES}")
# Direct calls into mutable RAM must pass the byte guard for each invocation.
file(READ "${GBA_SDK}/tools/recomp/codegen/arm_ops.cpp" ARM_OPS_SOURCE)
string(REPLACE "direct = callee != functions->end() && callee->second.mode == fn_.mode;"
  "direct = analysis::Image::is_rom(in.imm_value) && callee != functions->end() && callee->second.mode == fn_.mode;"
  GUARDED_ARM_OPS "${ARM_OPS_SOURCE}")
if(GUARDED_ARM_OPS STREQUAL ARM_OPS_SOURCE)
  message(FATAL_ERROR "GBA mutable call patch no longer applies")
endif()
string(REPLACE "    // A PC-relative word load from ROM reads a constant: fold it."
  "    if (load) line(\"if (--c->cycles <= 0) anygba_load_events(c);\");\n    // A PC-relative word load from ROM reads a constant: fold it."
  GUARDED_ARM_OPS "${GUARDED_ARM_OPS}")
file(CONFIGURE OUTPUT "${CMAKE_CURRENT_BINARY_DIR}/guarded_arm_ops.cpp" CONTENT "${GUARDED_ARM_OPS}" @ONLY)
list(REMOVE_ITEM PRECISE_SOURCES "${GBA_SDK}/tools/recomp/codegen/arm_ops.cpp")
list(APPEND PRECISE_SOURCES "${CMAKE_CURRENT_BINARY_DIR}/guarded_arm_ops.cpp")
set_property(TARGET anygba_recomp_lib PROPERTY SOURCES "${PRECISE_SOURCES}")
add_executable(gba-overlays overlay_emitter.cpp)
target_link_libraries(gba-overlays PRIVATE anygba_recomp_lib)
