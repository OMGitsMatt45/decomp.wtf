// SPDX-License-Identifier: GPL-3.0-only
#pragma once
#include "runtime/ps2_vu1.h"
#include <cstdint>

using DecompVuFunction=bool(*)(VU1Interpreter&,uint64_t,uint32_t);
DecompVuFunction decomp_find_vu_pair(uint64_t word,bool unit1);
