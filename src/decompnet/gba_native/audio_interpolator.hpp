// SPDX-License-Identifier: MIT
#pragma once
#include <algorithm>
#include <array>
#include <cmath>
#include <cstdint>
#include <span>

namespace anygba {
// Reconstruct the DirectSound stream before the DAC mix. Future samples are
// already queued in the hardware FIFO: no extra audio buffering or guest ticks.
// This presentation state is deliberately separate from the emulated hardware.
class AudioInterpolator {
public:
    void reset() { count_=0;last_=0;period_=0; }
    void push(std::int8_t value,std::uint64_t at) {
        if(count_) {
            const auto delta=at>last_?at-last_:0;
            if(!delta || (period_ && delta!=period_))reset();
            else if(!period_) {period_=delta;make_kernel();}
        }
        last_=at;
        for(unsigned i=7;i>0;--i)history_[i]=history_[i-1];
        history_[0]=value;
        count_=std::min(count_+1,8u);
    }
    double sample(std::uint64_t at,std::span<const std::int8_t> future,double held) const {
        if(count_<2 || !period_ || at<last_ || at-last_>period_)return held;
        const double phase=double(at-last_)*phases/double(period_);
        const auto p=std::min(unsigned(phase),phases-1);
        const double blend=phase-p;
        double result=0;
        for(int k=-7;k<=8;++k) {
            const double value=k<=0?history_[std::min(unsigned(-k),count_-1)]:
                (future.empty()?held:future[std::min(std::size_t(k-1),future.size()-1)]);
            const auto i=unsigned(k+7);
            result+=value*(kernel_[p][i]+blend*(kernel_[p+1][i]-kernel_[p][i]));
        }
        return result;
    }
private:
    static constexpr unsigned phases=256;
    void make_kernel() {
        constexpr double pi=3.14159265358979323846;
        // At source rates above the 32768 Hz output, also reject frequencies
        // above the output Nyquist limit instead of introducing new aliases.
        const double cutoff=std::min(1.0,double(period_)/512.0);
        for(unsigned p=0;p<=phases;++p) {
            double sum=0;
            for(int k=-7;k<=8;++k) {
                const double distance=double(p)/phases-k,x=pi*distance*cutoff;
                const double sinc=std::abs(x)<1e-12?1.0:std::sin(x)/x;
                const double window=std::abs(distance)>=8?0.0:
                    0.42+0.5*std::cos(pi*distance/8)+0.08*std::cos(pi*distance/4);
                sum+=(kernel_[p][unsigned(k+7)]=sinc*window*cutoff);
            }
            for(auto& coefficient:kernel_[p])coefficient/=sum;
        }
    }
    std::array<double,8> history_{};
    std::array<std::array<double,16>,phases+1> kernel_{};
    std::uint64_t last_=0,period_=0;
    unsigned count_=0;
};
}
