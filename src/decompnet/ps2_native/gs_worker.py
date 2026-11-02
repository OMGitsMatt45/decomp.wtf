"""Ordered GS integration and prompt release of consumed command payloads."""
from pathlib import Path
from .runtime_patch import replace


def patch(root):
    source=Path(root)/'thirdparty/PS2Recomp/ps2xRuntime/src/lib/gs/gs_threaded_backend.cpp'
    replace(source,'''                            for (size_t i = index; i < end; ++i)
                                bytes += batch[i].bytes();''', '''                            for (size_t i = index; i < end; ++i) {
                                bytes += batch[i].bytes();
                                discardConsumed(batch[i]);
                            }''')
    replace(source,'''                    execute(command);
                    bytes += command.bytes();''', '''                    execute(command);
                    bytes += command.bytes();
                    discardConsumed(batch[index]);''')
    replace(source,'    static constexpr size_t kReleaseBytes = 64u * 1024u;', '''    static void discardConsumed(Command &command) {
        // A later preparation may wait for a presentation slot. Retaining an
        // earlier result until the entire batch ends would retain its slot too.
        // Account for the original bytes first; completed commands own no data.
        command.op = Op::Flush;
        command.data = std::monostate{};
    }

    static constexpr size_t kReleaseBytes = 64u * 1024u;''')
