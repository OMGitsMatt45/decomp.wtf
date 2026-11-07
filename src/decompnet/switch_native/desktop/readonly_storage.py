"""Keep desktop transform feedback on the shared storage ring."""

from .patches import replace_once


def apply(root, adapter):
    rt = root / 'crates/rt'
    descriptors = rt / 'src/gpu/vulkan/descriptors.rs'
    replace_once(descriptors, '        let resident_storage = self.readonly_storage_cache && self.buffer_cache_on\n',
                 '        let resident_storage = self.readonly_storage_cache && self.buffer_cache_on\n'
                 '            && regs[crate::gpu::threed::reg::STREAM_OUTPUT] & 1 == 0\n')

    probe = rt / 'examples/decomp-graphics.rs'
    end_of_main = '    gpfifo_continuation(&gpu, &mem);\n    gpu.shutdown();'
    replace_once(probe, end_of_main, end_of_main + '\n    readonly_storage_qualification();')
    with probe.open('a', encoding='utf-8', newline='\n') as output:
        output.write((adapter / 'readonly_storage_probe.rs').read_text(encoding='utf-8'))
