// SPDX-License-Identifier: CC0-1.0
// Real scheduler regression: completed callbacks must not exhaust the EE pool
// while their owning threads remain alive and asleep.
#include "ps2_runtime.h"
#include "ps2_runtime_macros.h"
#include "runtime/ee_scheduler.h"
#include "EeHostPacing.h"
#include <chrono>
#include <cstdio>
#include <cstring>
#include <stdexcept>
#include <unordered_map>

struct EeSchedulerPacingTestAccess {
    using Clock = ee_host_pacing::Clock;

    static void reset(PS2Runtime &runtime, double rate)
    {
        auto &scheduler = runtime.eeScheduler();
        scheduler.reset(runtime.memory().getRDRAM(), R5900Context{});
        scheduler.setHostSpeed(rate);
        scheduler.m_deadlines.clear();
        scheduler.updateNextDeadline();
    }

    static void alarm(EeScheduler &scheduler, uint64_t cycle, Clock::time_point wall, uint32_t id)
    {
        scheduler.m_alarms[id] = EeAlarm{static_cast<int>(id), 1, 0x100000u};
        scheduler.scheduleEvent(cycle, wall, EeEvent{EeEventType::Alarm, id, 0});
    }

    static unsigned checkOrder(PS2Runtime &runtime)
    {
        using namespace std::chrono_literals;
        auto &scheduler = runtime.eeScheduler();
        Clock::time_point wall{100s};
        const ee_host_pacing::ClockHooks hooks{&wall,
            [](void *value) { return *static_cast<Clock::time_point *>(value); },
            [](void *value, Clock::time_point deadline) {
                auto &now = *static_cast<Clock::time_point *>(value);
                if (now <= deadline)
                    now = deadline + 1us;
            }};
        struct RestoreClock {
            ~RestoreClock() { ee_host_pacing::clockHooks = nullptr; }
        } restore;
        ee_host_pacing::clockHooks = &hooks;
        unsigned checked = 0;

        for (const double rate : {1.0, 1.28, 1.60}) {
            reset(runtime, rate);
            const auto now = scheduler.pacingNow();
            alarm(scheduler, 200, now + 5us, 3);
            alarm(scheduler, 100, now + 10us, 2);
            alarm(scheduler, 100, now + 20us, 1);
            scheduler.m_eeCycle = 250;
            scheduler.processDueDeadlines();
            if (scheduler.m_pendingInvocations.size() != 3)
                throw std::runtime_error("scheduler did not deliver all guest-cycle-ready alarms");
            for (const uint32_t id : {1, 2, 3}) {
                if (getRegU32(&scheduler.m_pendingInvocations[id - 1].context, 4) != id)
                    throw std::runtime_error("host pacing reordered alarms");
            }
            ++checked;

            // The guest winner is cycle 32 in each case. Reverse the host
            // deadline preference by placing the scheduled alarm in the
            // future or the past and moving the EE timer to the other cycle.
            for (const bool timerFirst : {false, true}) {
                const uint64_t timerCycles = timerFirst ? 32u : 64u;
                reset(runtime, rate);
                runtime.memory().write32(0x10000020u, static_cast<uint32_t>(timerCycles / 2));
                runtime.memory().write32(0x10000010u, 0x180u);
                if (runtime.memory().cyclesUntilNextEeTimerInterrupt() != timerCycles)
                    throw std::runtime_error("unexpected EE timer cycle in pacing fixture");
                alarm(scheduler, timerFirst ? 64u : 32u,
                      scheduler.pacingNow() + (timerFirst ? -1ms : 1ms), 1);
                scheduler.waitForEvent();
                if (scheduler.eeCycle() != 32 || (scheduler.m_pendingEeTimerInterrupts != 0) != timerFirst)
                    throw std::runtime_error("wall time changed the next guest event while the EE was idle");
                ++checked;
            }
        }
        scheduler.setHostSpeed(1.0);
        return checked;
    }
};

namespace {
constexpr uint32_t main_pc=0x27000,worker_pc=0x27010,outer_pc=0x27020,child_pc=0x27030,follow_pc=0x27040;
constexpr unsigned workers=48;
unsigned completed=0,nested=0,followed=0;
std::unordered_map<int,uint32_t> outer_stacks;
uint32_t value(const R5900Context &ctx,unsigned reg){return uint32_t(_mm_cvtsi128_si32(ctx.r[reg]));}
void check(bool condition){if(!condition)throw std::runtime_error("scheduler stack contents or lifetime changed");}
void write(uint8_t *ram,uint32_t sp,uint32_t word){std::memcpy(ram+sp-32,&word,4);}
uint32_t read(uint8_t *ram,uint32_t sp){uint32_t word;std::memcpy(&word,ram+sp-32,4);return word;}
void main_entry(uint8_t*,R5900Context *ctx,PS2Runtime *runtime){
    runtime->eeScheduler().setupCurrentThread(0x01f40000u,0x000c0000u,0);ctx->pc=0;
}
void follow(uint8_t *ram,R5900Context *ctx,PS2Runtime*){
    write(ram,value(*ctx,29),0xf0110u);++followed;ctx->pc=0;
}
void child(uint8_t *ram,R5900Context *ctx,PS2Runtime *runtime){
    const auto parent=outer_stacks.at(runtime->eeScheduler().currentThreadId());
    check(value(*ctx,29)!=parent);check(read(ram,parent)==0xaabbccddu);
    write(ram,value(*ctx,29),0x11223344u);++nested;ctx->pc=0;
}
void outer(uint8_t *ram,R5900Context *ctx,PS2Runtime *runtime){
    const uint32_t sp=value(*ctx,29);
    if(!value(*ctx,16)){
        SET_GPR_U32(ctx,16,1);write(ram,sp,0xaabbccddu);
        outer_stacks[runtime->eeScheduler().currentThreadId()]=sp;
        GuestInvocation invocation{};invocation.context.pc=child_pc;
        invocation.onComplete=[ram,sp](const R5900Context &done,R5900Context &){
            check(read(ram,value(done,29))==0x11223344u);check(read(ram,sp)==0xaabbccddu);
        };
        runtime->eeScheduler().invokeCurrent(std::move(invocation));
    }
    check(read(ram,sp)==0xaabbccddu);ctx->pc=0;
}
void worker(uint8_t *ram,R5900Context *ctx,PS2Runtime *runtime){
    if(!value(*ctx,16)){
        SET_GPR_U32(ctx,16,1);GuestInvocation invocation{};invocation.context.pc=outer_pc;
        invocation.onComplete=[ram,runtime](const R5900Context &done,R5900Context &){
            check(read(ram,value(done,29))==0xaabbccddu);
            // A completion can immediately schedule another callback at the
            // same depth. Its newly live stack must survive the cleanup.
            GuestInvocation next{};next.context.pc=follow_pc;
            runtime->eeScheduler().invokeCurrent(std::move(next));
        };
        runtime->eeScheduler().invokeCurrent(std::move(invocation));
    }
    ++completed;
    if(completed==workers){runtime->requestStop();ctx->pc=0;return;}
    runtime->eeScheduler().sleepCurrent();
}
}
int main(){
    try{
        PS2Runtime runtime;check(runtime.memory().initialize());
        const unsigned ordered=EeSchedulerPacingTestAccess::checkOrder(runtime);
        for(auto pair:{std::pair{main_pc,main_entry},std::pair{worker_pc,worker},
                      std::pair{outer_pc,outer},std::pair{child_pc,child},std::pair{follow_pc,follow}})
            runtime.registerFunction(pair.first,pair.second);
        R5900Context context{};context.pc=main_pc;
        auto &scheduler=runtime.eeScheduler();scheduler.reset(runtime.memory().getRDRAM(),context);
        for(unsigned n=0;n<workers;++n){
            EeThreadCreateParams params{};params.entry=worker_pc;params.priority=40;
            params.stack=0x00100000u+n*0x1000u;params.stackSize=0x1000;
            const int id=scheduler.createThread(params);check(id>0);
            check(scheduler.startThread(id,0,context,false)==0);
        }
        scheduler.run();check(completed==workers&&nested==workers&&followed==workers);
        std::printf("{\"success\":true,\"living_owners\":%u,\"nested_callbacks\":%u,\"completion_callbacks\":%u,\"ordered_deadline_cases\":%u}\n",completed,nested,followed,ordered);
        return 0;
    }catch(const std::exception &error){
        std::printf("{\"success\":false,\"completed\":%u,\"error\":\"%s\"}\n",completed,error.what());return 1;
    }
}
