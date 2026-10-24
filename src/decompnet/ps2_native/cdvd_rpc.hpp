// SPDX-License-Identifier: MIT
// CDVD SCMD wire operations, as exposed by PS2SDK's ee/rpc/cdvd/src/scmd.c.
// Shared console services; no game addresses, patches or source data.
#pragma once
#include "ps2_runtime.h"
#include "Kernel/Syscalls/decomp_disc_files.hpp"
#include <optional>

namespace decomp_ps2 {
inline std::optional<ps2x::iop::RpcResult> cdvd_scmd(uint8_t *ram,const ps2x::iop::RpcRequest &request) {
    if(request.sid!=0x80000593u||(request.function!=3u&&request.function!=0x23u))return std::nullopt;
    auto span=[&](ps2x::iop::GuestBuffer buffer) {
        const uint32_t physical=buffer.address&0x1fffffffu;
        if(!ram||!buffer.address||buffer.size<4||physical>0x02000000u-4)
            throw std::runtime_error("invalid CDVD SCMD buffer");
        return ram+physical;
    };
    uint8_t *reply=span(request.receive);uint32_t value;
    if(request.function==3u)value=disc::medium();
    else {
        int32_t priority;std::memcpy(&priority,span(request.send),4);
        value=disc::set_priority(priority)?1u:0u;
    }
    std::memcpy(reply,&value,4);
    ps2x::iop::RpcResult result{};result.handled=true;result.resultAddress=request.receive.address;
    return result;
}
}
