// SPDX-License-Identifier: MIT
// Members inserted into the pinned Discoverer. No game-specific addresses.
    void scan_pointer_candidates() {
        // Callback tables are often reached through RAM state. Such a pointer
        // never appears in the literal pool of an already-discovered function.
        // Treat ROM words as hypotheses, then require a complete decoded body.
        std::set<std::uint64_t> checked;
        const auto& bytes = image_.rom();
        unsigned adopted = 0;
        // Script records can pack a command byte directly before a callback
        // pointer. The storage alignment does not establish the code alignment.
        for (std::size_t offset = 0; offset + 4 <= bytes.size(); ++offset) {
            const auto raw = image_.read32(kRomBase + static_cast<std::uint32_t>(offset));
            if (!raw || !Image::is_rom(*raw)) continue;
            // A callback stored as an ordinary data/code-copy pointer can be
            // even, with its Thumb bit added only when it is installed in RAM.
            for(unsigned hypothesis=0;hypothesis<((*raw&1u)?1u:2u);++hypothesis) {
            const Mode mode = (*raw & 1u) || hypothesis ? Mode::Thumb : Mode::Arm;
            if (mode == Mode::Arm && (*raw & 3u)) continue;
            const std::uint32_t address = Image::canonical(*raw & ~1u);
            if (!image_.contains(address, mode == Mode::Thumb ? 2 : 4) || skipped(address)) continue;
            if (known_.contains(address)) continue;
            const auto first = decode_at(image_, address, mode);
            if (!first.valid() || first.cond != decode::Cond::AL) continue;
            const bool saves_lr =
                (first.op == decode::Op::STM && first.rn == decode::kSP &&
                 (first.reglist & (1u << decode::kLR))) ||
                (first.op == decode::Op::STR && first.rn == decode::kSP && first.rd == decode::kLR &&
                 first.pre && !first.up && first.writeback && first.imm && first.imm_value == 4);
            // Packed script callbacks need not save LR: a short leaf can
            // return directly to its caller. Verify the entire straight-line
            // body before deduplication, so rejected packed aliases still
            // cannot suppress stronger aligned/table evidence later.
            const bool packed=(offset&3u)!=0;
            if(packed && !saves_lr) {
                bool leaf_return=false;
                auto pc=address;
                for(unsigned count=0;count<32;++count) {
                    const auto in=decode_at(image_,pc,mode);
                    if(!in.valid() || in.cond!=decode::Cond::AL)break;
                    if(is_return(in)){leaf_return=true;break;}
                    if(in.op==decode::Op::B || in.op==decode::Op::BL ||
                       in.op==decode::Op::BX || in.op==decode::Op::BL_HI ||
                       in.op==decode::Op::BL_LO || in.op==decode::Op::SWI ||
                       in.rd==decode::kPC)break;
                    pc=in.next();
                }
                if(!leaf_return)continue;
            }
            unsigned neighbors=1;
            for(int direction : {-1,1}) {
                for(int distance=1;distance<=2;++distance) {
                    const auto location=std::int64_t(offset)+4*direction*distance;
                    if(location<0 || std::uint64_t(location)+4>bytes.size())break;
                    const auto word=image_.read32(kRomBase+std::uint32_t(location));
                    if(!word || !Image::is_rom(*word) || (!(*word&1u) && (*word&3u)))break;
                    const auto target=Image::canonical(*word&~1u);
                    const auto other=decode_at(image_,target,(*word&1u)?Mode::Thumb:Mode::Arm);
                    if(!other.valid() || other.cond!=decode::Cond::AL)break;
                    ++neighbors;
                }
            }
            // A dense table supplies independent evidence for longer naked
            // assembly callbacks, without assuming a compiler's stack prologue.
            const bool callback_table=neighbors>=3;
            // Rejection depends on the evidence at this occurrence. A packed
            // alias rejected above must not poison a later aligned pointer,
            // and an isolated pointer must not suppress a later dense table.
            const auto key = (std::uint64_t(address) << 2) |
                (mode == Mode::Thumb ? 2u : 0u) | (callback_table ? 1u : 0u);
            if (!checked.insert(key).second) continue;
            bool deferred_stack=false;
            for(auto pc=address;pc<address+64;) {
                const auto in=decode_at(image_,pc,mode);if(!in.valid())break;
                if(in.cond==decode::Cond::AL &&
                    ((in.op==decode::Op::STM && in.rn==decode::kSP && (in.reglist&(1u<<decode::kLR))) ||
                     (in.op==decode::Op::STR && in.rn==decode::kSP && in.rd==decode::kLR &&
                      in.pre && !in.up && in.writeback && in.imm && in.imm_value==4)))deferred_stack=true;
                pc=in.next();
            }
            bool short_leaf = false;
            if (!saves_lr) {
                auto pc = address;
                for (unsigned i = 0; i < 32; ++i) {
                    const auto instruction = decode_at(image_, pc, mode);
                    if (!instruction.valid() || instruction.cond != decode::Cond::AL) break;
                    if (is_return(instruction) || instruction.op == decode::Op::BX ||
                        ((instruction.op == decode::Op::MOV || instruction.op == decode::Op::LDR) &&
                         instruction.rd == decode::kPC)) { short_leaf = true; break; }
                    // A leaf hypothesis cannot cross a call, jump, exception,
                    // or a destination write that changes the program counter.
                    if (instruction.op == decode::Op::B || instruction.op == decode::Op::BL ||
                        instruction.op == decode::Op::BX || instruction.op == decode::Op::BL_HI ||
                        instruction.op == decode::Op::BL_LO || instruction.op == decode::Op::SWI ||
                        instruction.rd == decode::kPC) break;
                    pc = instruction.next();
                }
            }
            if (!saves_lr && !deferred_stack && !short_leaf && !callback_table) continue;
            const EntryPoint candidate{address, mode, EntrySource::LiteralPool};
            const auto walk = walk_function(image_, candidate, known_, noreturn_, options_.skip);
            // A callback may end entirely in branches to already discovered
            // functions. That is a complete tail-call body without a local BX.
            bool known_tail = !walk.function.tail_calls.empty();
            for(const auto target : walk.function.tail_calls)
                known_tail = known_tail && known_.contains(target);
            // Interworking epilogues may POP the saved LR into another
            // register and BX it. A verified stack entry need not contain a
            // literal BX LR or POP PC to be a callable function.
            if (walk.function.hit_undefined || (!walk.function.has_exit && !known_tail) ||
                (packed && !saves_lr && walk.function.insns.size()>32) ||
                (!saves_lr && !deferred_stack && !callback_table && !(short_leaf && walk.function.insns.size()<=32))) continue;
            enqueue(candidate);
            ++adopted;
            }
        }
        drain();
        out_.notes.push_back("decomp.wtf: verified " + std::to_string(adopted) +
                             " ROM callback-table entry hypotheses");
    }
