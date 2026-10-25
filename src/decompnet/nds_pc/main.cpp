// SPDX-License-Identifier: MIT. Original decomp.wtf experimental DS runner.
#include "runtime.hpp"
#include <iostream>
#include <stdexcept>

int main(int argc,char** argv) {
    try {
        std::filesystem::path assets="assets",save;
        uint64_t budget=100000;
        for(int i=1;i<argc;++i) {
            const std::string arg=argv[i];
            if(i+1>=argc)throw std::runtime_error("expected --assets PATH, --save PATH or --max-steps N");
            if(arg=="--assets")assets=argv[++i];
            else if(arg=="--save")save=argv[++i];
            else if(arg=="--max-steps") {
                const std::string number=argv[++i];
                if(number.empty() || number.find_first_not_of("0123456789")!=std::string::npos)
                    throw std::runtime_error("instruction budget must be a positive number");
                budget=std::stoull(number);
                if(!budget || budget>1000000000)throw std::runtime_error("instruction budget outside supported range");
            } else throw std::runtime_error("unknown runner option");
        }
        nds::Runtime rt(assets);rt.load_save(save);rt.run(budget);rt.write_save(save);
        std::cout << "{\"steps\":" << rt.steps;
        for(const auto& c:rt.cpu) {
            std::cout << ",\"arm" << (c.id==0?9:7) << "\":{\"registers\":[";
            for(unsigned i=0;i<16;++i)std::cout << (i?",":"") << (i==15?c.pc:c.r[i]);
            std::cout << "],\"nzcv\":" << ((uint32_t(c.n)<<31)|(uint32_t(c.z)<<30)|(uint32_t(c.carry)<<29)|(uint32_t(c.v)<<28)) << "}";
        }
        std::cout << ",\"observed\":[";
        for(unsigned i=0;i<nds::observation_count;++i)std::cout << (i?",":"") << rt.read32(nds::observations[i]);
        std::cout << "],\"overlay_loads\":[";
        for(unsigned i=0;i<rt.overlay_loads.size();++i)std::cout << (i?",":"") << rt.overlay_loads[i];
        std::cout << "]}\n";
    } catch(const std::exception& error) {
        std::cerr << "DS static runtime: " << error.what() << '\n';return 1;
    }
}
