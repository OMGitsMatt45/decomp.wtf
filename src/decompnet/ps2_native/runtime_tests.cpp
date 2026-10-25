// SPDX-License-Identifier: MIT
// Execute original upstream fixtures against this export's integrated runtime.
#include "MiniTest.h"
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
        {"irx",register_decomp_irx_tests}};
    if(argc!=1&&(argc!=3||std::string(argv[1])!="--suite"))return 2;
    bool selected=false;
    for(const auto &[name,run]:suites)if(argc==1||std::string(argv[2])==name){run();selected=true;}
    if(!selected)return 2;
    const int failed=MiniTest::Run();
    std::cout.flush();std::cerr.flush();
    // Runtime tests deliberately leave scheduler state for process teardown.
    std::_Exit(failed?1:0);
}
