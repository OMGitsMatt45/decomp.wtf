//! Numeric-kind lookup for shader variants. Guest descriptors are always read fresh.

use kirikae_maxwell::{Env, Kind, TextureUse};

use crate::gpu::{Gpu, formats, threed::CB_SLOTS};
use crate::mem::GuestMemory;

pub(super) struct TextureKindTable([Kind; 2048]);

impl TextureKindTable {
    pub(super) fn shared() -> &'static Self {
        static KINDS: std::sync::LazyLock<TextureKindTable> = std::sync::LazyLock::new(|| {
            TextureKindTable(std::array::from_fn(|index| {
                let components = (index & 0x7f) as u32;
                let data_type = (index >> 7 & 7) as u32;
                let srgb = index & (1 << 10) != 0;
                formats::texture(components, data_type, srgb).map_or(Kind::Float, |format| format.kind)
            }))
        });
        &KINDS
    }

    fn lookup(&self, descriptor: &[u8; 32]) -> Kind {
        let format = usize::from(u16::from_le_bytes([descriptor[0], descriptor[1]])) & 0x3ff;
        let srgb = usize::from(descriptor[18] >> 6 & 1);
        self.0[format | (srgb << 10)]
    }
}

fn full_texture_kind(descriptor: &[u8]) -> Kind {
    let Some(words) = crate::gpu::tic::words(descriptor) else { return Kind::Float; };
    let header = crate::gpu::tic::texture_header(&words);
    formats::texture(header.components, header.data_type, header.srgb).map_or(Kind::Float, |format| format.kind)
}

pub(super) struct ShaderEnv<'a> {
    pub(super) gpu: &'a Gpu,
    pub(super) mem: &'a GuestMemory,
    pub(super) cbufs: [Option<(u64, u32)>; CB_SLOTS],
    pub(super) default_slot: u32,
    pub(super) header_pool: u64,
    pub(super) kind_table: Option<&'static TextureKindTable>,
}

impl Env for ShaderEnv<'_> {
    fn texture_use_kind(&self, usage: &TextureUse) -> Kind {
        let Ok(word) = usage.handle_word(self.default_slot, |slot, offset| self.cbuf(slot, offset).ok_or(())) else {
            return Kind::Float;
        };
        let address = self.header_pool + (word & 0xfffff) as u64 * 32;
        // Require the same complete descriptor as the full decoder. The table
        // only caches the immutable format interpretation, never guest bytes.
        let Some(descriptor) = self.gpu.bytes(self.mem, address, 32) else { return Kind::Float; };
        if let Some(table) = self.kind_table {
            let Ok(descriptor) = <&[u8; 32]>::try_from(descriptor) else { return Kind::Float; };
            table.lookup(descriptor)
        } else {
            full_texture_kind(descriptor)
        }
    }

    fn cbuf(&self, slot: u32, offset: u32) -> Option<u32> {
        let (address, size) = self.cbufs.get(slot as usize).copied().flatten()?;
        if offset.checked_add(4)? > size { return None; }
        let address = address.checked_add(u64::from(offset))?;
        let word = if self.kind_table.is_some() {
            self.gpu.bytes(self.mem, address, 4)?.try_into().ok()?
        } else {
            self.gpu.read(self.mem, address, 4)?.try_into().ok()?
        };
        Some(u32::from_le_bytes(word))
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn fast_texture_kind_matches_every_format_field() {
        let table = TextureKindTable::shared();
        let mut seed = 0x6fa1_03c9u32;
        for field in 0..2048usize {
            let mut descriptor = std::array::from_fn(|_| {
                seed ^= seed << 13;
                seed ^= seed >> 17;
                seed ^= seed << 5;
                seed as u8
            });
            descriptor[0] = field as u8;
            descriptor[1] = descriptor[1] & !3 | (field >> 8 & 3) as u8;
            descriptor[18] = descriptor[18] & !(1 << 6) | ((field >> 10) as u8) << 6;
            assert_eq!(table.lookup(&descriptor), full_texture_kind(&descriptor), "TIC format {field:#x}");
        }
    }

    #[test]
    fn fast_texture_kind_rereads_mapped_handles_and_full_descriptors() {
        use kirikae_maxwell::TexDim;

        const CBUF0: u64 = 0x1_0010_0000;
        const CBUF1: u64 = 0x1_0010_1000;
        const TIC: u64 = 0x2_0000_0000;
        const SHORT: u64 = 0x2_0000_1000;
        const HEADER_A: u64 = 0x210000;
        const HEADER_B: u64 = 0x220000;
        const TAIL: u64 = 0x230000;
        let mem = GuestMemory::new().unwrap();
        let gpu = Gpu::default();
        for (va, cpu) in [(CBUF0, 0x200000), (CBUF1, 0x201000), (TIC, HEADER_A), (SHORT, TAIL)] {
            mem.map(cpu, 0x1000).unwrap();
            gpu.map(va, cpu, 0x1000);
        }
        mem.map(HEADER_B, 0x1000).unwrap();
        let descriptor = |data_type: u32| {
            let mut raw = [0; 32];
            raw[..4].copy_from_slice(&(0x08 | data_type << 7).to_le_bytes());
            raw
        };
        assert!(mem.write(HEADER_A, &descriptor(4)));
        assert!(mem.write(HEADER_A + 32, &descriptor(3)));
        assert!(mem.write(HEADER_B, &descriptor(2)));
        assert!(mem.write(0x200000, &0xabc0_0000u32.to_le_bytes()));
        assert!(mem.write(0x201004, &1u32.to_le_bytes()));
        assert!(mem.write(TAIL + 0xfe8, &descriptor(4)[..24]));

        let mut cbufs = [None; CB_SLOTS];
        cbufs[1] = Some((CBUF0, 8));
        cbufs[2] = Some((CBUF1, 8));
        let bound = TextureUse { kind: Kind::Float, or_cbuf: None, slot: None, handle: 0,
            dim: TexDim::D2, array: false, shadow: false, binding: 40 };
        let check = |usage, header_pool, expected| {
            for kind_table in [None, Some(TextureKindTable::shared())] {
                let env = ShaderEnv { gpu: &gpu, mem: &mem, cbufs, default_slot: 1, header_pool, kind_table };
                assert_eq!(env.texture_use_kind(&usage), expected);
            }
        };
        check(bound, TIC, Kind::Uint);
        check(TextureUse { or_cbuf: Some((2, 4)), ..bound }, TIC, Kind::Sint);
        check(TextureUse { slot: Some(2), handle: 1, ..bound }, TIC, Kind::Sint);
        check(TextureUse { or_cbuf: Some((3, 4)), ..bound }, TIC, Kind::Float);
        check(TextureUse { handle: 2, ..bound }, TIC, Kind::Float);
        check(bound, SHORT + 0xfe8, Kind::Float);

        assert!(mem.write(0x200000, &0xabc0_0001u32.to_le_bytes()));
        check(bound, TIC, Kind::Sint);
        assert!(mem.write(0x200000, &0xabc0_0000u32.to_le_bytes()));
        assert!(mem.write(HEADER_A, &descriptor(3)));
        check(bound, TIC, Kind::Sint);
        gpu.map(TIC, HEADER_B, 0x1000);
        check(bound, TIC, Kind::Float);
        gpu.unmap(TIC);
        check(bound, TIC, Kind::Float);
    }
}
