// SPDX-License-Identifier: MIT
// Execute original upstream fixtures against this export's integrated runtime.
#include "MiniTest.h"
#include "decomp_ee_timer.hpp"
#include "runtime/ps2_memory.h"
#include <cstdlib>

void reset_ps2_test_function_table();
void register_pad_input_tests();
void register_ps2_runtime_io_tests();
void register_ps2_runtime_kernel_tests();
void register_ps2_runtime_interrupt_tests();
void register_ee_fiber_tests();
void register_ps2_memory_tests();
void register_ps2_vu1_tests();
void register_ps2_vu1_upper_engine_tests();
void register_ps2_vu1_program_tests();
void register_ps2_vu_tests();
void register_ps2_gs_tests();
void register_ps2_iop_tests();
void register_ps2_native_iop_tests();
void register_ps2_sif_rpc_tests();
void register_ps2_sif_dma_tests();
void register_ps2_runtime_expansion_tests();
void register_decomp_irx_tests();

void register_deferred_ee_timer_tests()
{
    MiniTest::Case("Deferred EE timers", [](TestCase &tc)
    {
        constexpr uint32_t count = 0x10000000u;
        constexpr uint32_t mode = 0x10000010u;
        constexpr uint32_t compare = 0x10000020u;
        constexpr uint32_t cue = 1u << 7;
        constexpr uint32_t compareEnabled = 1u << 8;
        constexpr uint32_t compareFlag = 1u << 10;

        tc.Run("Observe and reload the pending count through guest MMIO", [](TestCase &t)
        {
            PS2Memory mem;
            t.IsTrue(mem.initialize(), "Initialize timer memory");
            decomp_ps2::ee_timer::Session session(mem, true);
            mem.write32(count, 0xffu);
            mem.write32(compare, 0x103u);
            mem.write32(mode, cue | compareEnabled);

            t.Equals(mem.advanceEeTimers(3u), 0u, "Advance below the compare event");
            t.Equals(mem.cyclesUntilNextEeTimerInterrupt(), uint64_t{5}, "Deadline excludes accrued cycles");
            t.Equals(mem.read8(count + 1u), uint8_t{1}, "Byte read observes the accrued high COUNT byte");
            t.Equals(mem.cyclesUntilNextEeTimerInterrupt(), uint64_t{5}, "Read keeps the deadline");
            t.Equals(mem.advanceEeTimers(4u), 0u, "Advance with one cycle remaining");
            mem.write16(count, 0x100u);
            t.Equals(mem.cyclesUntilNextEeTimerInterrupt(), uint64_t{6}, "COUNT write resets phase and deadline");
            t.Equals(mem.advanceEeTimers(5u), 0u, "Reload prevents the old deadline");
            t.Equals(mem.read16(count), uint16_t{0x102}, "Halfword read materializes the current count");
            t.Equals(mem.advanceEeTimers(1u), 1u, "Return the compare IRQ on its exact cycle");
            t.IsTrue((mem.read32(mode) & compareFlag) != 0u, "Compare flag is visible");
            mem.write32(mode, cue | compareEnabled | compareFlag);
            t.IsTrue((mem.read32(mode) & compareFlag) == 0u, "MODE write-one clears the compare flag");
        });

        tc.Run("A nested memory keeps its eager state and finishing commits the owning state", [](TestCase &t)
        {
            PS2Memory mem, other;
            t.IsTrue(mem.initialize(), "Initialize the owner memory");
            t.IsTrue(other.initialize(), "Initialize the second memory");
            decomp_ps2::ee_timer::Session session(mem, true);
            {
                decomp_ps2::ee_timer::Session nested(other, true);
                other.write32(mode, cue);
                other.advanceEeTimers(4u);
                t.Equals(other.read32(count), 2u, "Second memory progresses independently");
            }
            mem.write32(mode, cue);
            mem.advanceEeTimers(5u);
            session.finish();
            t.IsTrue(decomp_ps2::ee_timer::stateFor(&mem) == nullptr, "Finish releases the deferred owner");
            t.Equals(mem.read32(count), 2u, "Finish publishes the final count");
            mem.advanceEeTimers(1u);
            t.Equals(mem.read32(count), 3u, "Finish preserves the prescaler remainder for eager execution");

            decomp_ps2::ee_timer::Session renewed(mem, true);
            mem.advanceEeTimers(8u);
            mem.resetEeTimers();
            t.Equals(mem.read32(count), 0u, "Reset discards the old timer cycle debt");
            t.Equals(mem.cyclesUntilNextEeTimerInterrupt(), decomp_ps2::ee_timer::never, "Reset clears the IRQ deadline");
        });
    });
}

int main(int argc,char **argv) {
    std::cout<<std::unitbuf;
    MiniTest::BeforeEach(reset_ps2_test_function_table);
    const std::pair<const char*,void(*)()> suites[]={
        {"pad",register_pad_input_tests},{"io",register_ps2_runtime_io_tests},
        {"kernel",register_ps2_runtime_kernel_tests},{"interrupt",register_ps2_runtime_interrupt_tests},
        {"fiber",register_ee_fiber_tests},{"memory",register_ps2_memory_tests},
        {"vu1",register_ps2_vu1_tests},{"vu_upper",register_ps2_vu1_upper_engine_tests},
        {"vu_program",register_ps2_vu1_program_tests},{"vu0",register_ps2_vu_tests},
        {"gs",register_ps2_gs_tests},{"iop",register_ps2_iop_tests},
        {"native_iop",register_ps2_native_iop_tests},{"sif_rpc",register_ps2_sif_rpc_tests},
        {"sif_dma",register_ps2_sif_dma_tests},{"media",register_ps2_runtime_expansion_tests},
        {"irx",register_decomp_irx_tests},{"deferred_timer",register_deferred_ee_timer_tests}};
    if(argc!=1&&(argc!=3||std::string(argv[1])!="--suite"))return 2;
    bool selected=false;
    for(const auto &[name,run]:suites)if(argc==1||std::string(argv[2])==name){run();selected=true;}
    if(!selected)return 2;
    const int failed=MiniTest::Run();
    std::cout.flush();std::cerr.flush();
    // Runtime tests deliberately leave scheduler state for process teardown.
    std::_Exit(failed?1:0);
}
