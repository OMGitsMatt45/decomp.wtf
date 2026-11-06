//! Clear-stream Tegra NVDEC VP8 packets and block-linear NV12 output.
use std::collections::HashMap;

use oxideav_vp8::{decoder::Vp8DecodedFrame, Vp8DecoderState};

use super::{block_linear_size, to_block_linear, trace, u32_at, Dma};

const PICTURE_INFO_SIZE: usize = 0xc0;
const MAX_DIMENSION: usize = 4096;
const MAX_PACKET_SIZE: usize = 16 * 1024 * 1024;

struct PictureInfo {
    width: usize,
    height: usize,
    key_frame: bool,
    version: u8,
    first_partition_size: usize,
    packet_size: usize,
    pitch: [usize; 2],
    frame_offset: [u32; 2],
    block_height: u32,
}

impl PictureInfo {
    fn parse(raw: &[u8]) -> Result<Self, String> {
        if raw.len() != PICTURE_INFO_SIZE {
            return Err("NVDEC: truncated VP8 picture setup".into());
        }
        // nvdec_vp8_pic_s from NVIDIA's open-gpu-doc.
        let width = u16::from_le_bytes([raw[0x38], raw[0x39]]) as usize;
        let height = u16::from_le_bytes([raw[0x3a], raw[0x3b]]) as usize;
        if !(1..=MAX_DIMENSION).contains(&width) || !(1..=MAX_DIMENSION).contains(&height) {
            return Err(format!("NVDEC: invalid VP8 dimensions {width}x{height}"));
        }
        if u32_at(raw, 0x30) & 1 != 0 {
            return Err("NVDEC: encrypted VP8 is unsupported".into());
        }
        let version = raw[0x3d];
        let gob_height = (raw[0x3e] >> 2) & 7;
        if raw[0x3c] > 1 || version > 3 {
            return Err("NVDEC: invalid VP8 frame tag".into());
        }
        if raw[0x3e] & 3 != 0 || gob_height > 4 || raw[0x84] != 0 {
            return Err("NVDEC: VP8 output requires Tegra block-linear NV12".into());
        }
        let first_partition_size = u32_at(raw, 0x40) as usize;
        let packet_size = u32_at(raw, 0x48) as usize;
        if first_partition_size == 0 || first_partition_size >= 1 << 19
            || first_partition_size > packet_size || packet_size > MAX_PACKET_SIZE
        {
            return Err("NVDEC: invalid VP8 packet or first partition size".into());
        }
        let mut pitch = [0; 2];
        for (i, visible) in [width, width.div_ceil(2) * 2].into_iter().enumerate() {
            // Tegra VP8 FrameStride entries count 16-byte units.
            let stride = u32_at(raw, 0x4c + i * 4).checked_mul(16)
                .ok_or("NVDEC: VP8 plane pitch overflow")? as usize;
            if stride < visible || stride > MAX_DIMENSION * 2 || !stride.is_multiple_of(64) {
                return Err(format!("NVDEC: invalid VP8 plane pitch {stride} for {visible} bytes"));
            }
            pitch[i] = stride;
        }
        Ok(Self { width, height, key_frame: raw[0x3c] == 1, version, first_partition_size,
            packet_size, pitch, frame_offset: [u32_at(raw, 0x5c), u32_at(raw, 0x68)],
            block_height: u32::from(gob_height) + 1 })
    }

    fn packet(&self, payload: &[u8]) -> Vec<u8> {
        // Tegra passes the coded partitions without the uncompressed frame header.
        // Every submission produces a surface, including a reference-only picture.
        let tag = ((self.first_partition_size as u32) << 5) | 0x10
            | (u32::from(self.version) << 1) | u32::from(!self.key_frame);
        let mut packet = Vec::with_capacity(payload.len() + if self.key_frame { 10 } else { 3 });
        packet.extend_from_slice(&tag.to_le_bytes()[..3]);
        if self.key_frame {
            packet.extend_from_slice(&[0x9d, 0x01, 0x2a]);
            packet.extend_from_slice(&(self.width as u16).to_le_bytes());
            packet.extend_from_slice(&(self.height as u16).to_le_bytes());
        }
        packet.extend_from_slice(payload);
        packet
    }

    fn tiled_nv12(&self, frame: &Vp8DecodedFrame) -> Result<[Vec<u8>; 2], String> {
        if (frame.width as usize, frame.height as usize) != (self.width, self.height) {
            return Err("NVDEC: VP8 decoded dimensions differ from picture setup".into());
        }
        let chroma_width = self.width.div_ceil(2) * 2;
        let chroma_height = self.height.div_ceil(2);
        let chroma_samples = chroma_width / 2 * chroma_height;
        if frame.y.len() != self.width * self.height || frame.u.len() != chroma_samples || frame.v.len() != chroma_samples {
            return Err("NVDEC: invalid VP8 decoded plane sizes".into());
        }
        let mut uv = Vec::with_capacity(chroma_width * chroma_height);
        for (&u, &v) in frame.u.iter().zip(&frame.v) {
            uv.extend_from_slice(&[u, v]);
        }
        Ok([
            tile_plane(&frame.y, self.width, self.height, self.pitch[0], self.block_height),
            tile_plane(&uv, chroma_width, chroma_height, self.pitch[1], self.block_height),
        ])
    }
}

fn tile_plane(plane: &[u8], width: usize, height: usize, pitch: usize, block_height: u32) -> Vec<u8> {
    if pitch == width.next_multiple_of(64) {
        return to_block_linear(plane, width, width, height, block_height);
    }
    let mut padded = vec![0; pitch * height];
    for (src, dst) in plane.chunks_exact(width).zip(padded.chunks_exact_mut(pitch)) {
        dst[..width].copy_from_slice(src);
    }
    to_block_linear(&padded, pitch, pitch, height, block_height)
}

#[derive(Default)]
pub(super) struct Vp8 {
    channels: HashMap<u32, Vp8DecoderState>,
}

impl Vp8 {
    pub(super) fn close(&mut self, context: u32) {
        self.channels.remove(&context);
    }

    fn decode_picture(&mut self, context: u32, info: &PictureInfo, payload: &[u8]) -> Result<Vp8DecodedFrame, String> {
        let decoder = self.channels.entry(context).or_insert_with(|| {
            Vp8DecoderState::new().with_max_pixels_per_frame((MAX_DIMENSION * MAX_DIMENSION) as u64)
        });
        if !info.key_frame && let Some(width) = decoder.visible_width()
            && (width as usize != info.width || decoder.visible_height() != Some(info.height as u32))
        {
            return Err("NVDEC: VP8 interframe dimensions differ from the last keyframe".into());
        }
        let result = decoder.decode_frame(&info.packet(payload));
        if result.is_err() {
            self.close(context);
        }
        result.map_err(|error| format!("NVDEC: {error}"))
    }

    pub(super) fn decode(&mut self, dma: &Dma, context: u32, setup: u32, input: u32, output: [u32; 2]) -> Result<(), String> {
        let raw = dma.read(setup, PICTURE_INFO_SIZE).ok_or("NVDEC: VP8 picture setup is not mapped")?;
        let info = PictureInfo::parse(&raw)?;
        let payload = dma.read(input, info.packet_size).ok_or("NVDEC: VP8 bitstream is not mapped")?;
        let [Some(luma), Some(chroma)] = std::array::from_fn(|i| output[i].checked_add(info.frame_offset[i])) else {
            return Err("NVDEC: VP8 surface offset overflow".into());
        };
        let y_len = block_linear_size(info.pitch[0], info.height, info.block_height);
        let uv_len = block_linear_size(info.pitch[1], info.height.div_ceil(2), info.block_height);
        if !dma.is_mapped(luma, y_len) || !dma.is_mapped(chroma, uv_len) {
            return Err("NVDEC: VP8 output surface is not mapped".into());
        }
        let frame = self.decode_picture(context, &info, &payload)?;
        let [y, uv] = info.tiled_nv12(&frame)?;
        if !dma.write(luma, &y) || !dma.write(chroma, &uv) {
            self.close(context);
            return Err("NVDEC: VP8 output surface is not mapped".into());
        }
        if trace() {
            eprintln!("nvdec: VP8 picture on channel {context}: {}x{}, {} bytes -> {luma:#x}/{chroma:#x}",
                info.width, info.height, info.packet_size);
        }
        Ok(())
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use super::super::{from_block_linear, nvdec::Nvdec, Iova};
    use crate::{gpu::{Gpu, NvMap}, mem::GuestMemory};

    // Two original 16×16 flat I420 frames encoded with libvpx, a keyframe
    // followed by an interframe. FFmpeg's native VP8 decoder reproduced the
    // input plane values (72, 110, 150) and (88, 104, 157) byte for byte.
    const KEY: &str = concat!(
        "b002009d012a1000100000070885858885848800281013ad501fc01067ee20fe",
        "fe480affdfeabdfd57bfaaff769ffe8e37e8e37e8e37fe8b80",
    );
    const INTER: &str = "f101000010100018074ff833e633f3002400fef0f1abd7c1f65547d445496f0000";

    fn split_frame(hex: &str) -> ([u8; PICTURE_INFO_SIZE], Vec<u8>, Vec<u8>) {
        let frame: Vec<u8> = hex.as_bytes().chunks_exact(2).map(|pair| {
            u8::from_str_radix(std::str::from_utf8(pair).unwrap(), 16).unwrap()
        }).collect();
        let tag = u32::from_le_bytes([frame[0], frame[1], frame[2], 0]);
        let key = tag & 1 == 0;
        let payload = frame[if key { 10 } else { 3 }..].to_vec();
        let mut setup = [0; PICTURE_INFO_SIZE];
        setup[0x38..0x3c].copy_from_slice(&[16, 0, 16, 0]);
        setup[0x3c] = u8::from(key);
        setup[0x3d] = ((tag >> 1) & 7) as u8;
        for (offset, value) in [(0x40, tag >> 5), (0x48, payload.len() as u32),
            (0x4c, 8), (0x50, 4), (0x5c, 1), (0x68, 2)]
        {
            setup[offset..offset + 4].copy_from_slice(&value.to_le_bytes());
        }
        (setup, frame, payload)
    }

    #[test]
    fn rejects_bad_or_unsupported_setup() {
        let (setup, packet, payload) = split_frame(KEY);
        assert_eq!(PictureInfo::parse(&setup).unwrap().packet(&payload), packet);
        assert!(PictureInfo::parse(&setup[..setup.len() - 1]).is_err());
        for (offset, value) in [(0x30, 1), (0x38, 0), (0x3d, 4), (0x3e, 1), (0x84, 1)] {
            let mut bad = setup;
            bad[offset] = value;
            assert!(PictureInfo::parse(&bad).is_err(), "field {offset:#x}");
        }
        for (offset, value) in [(0x40, 1u32 << 19), (0x48, 1), (0x48, MAX_PACKET_SIZE as u32 + 1),
            (0x4c, 0), (0x4c, 3), (0x4c, 1 << 28)]
        {
            let mut bad = setup;
            bad[offset..offset + 4].copy_from_slice(&value.to_le_bytes());
            assert!(PictureInfo::parse(&bad).is_err(), "field {offset:#x}");
        }
    }

    #[test]
    fn parses_720p_picture_pitch_in_16_byte_units() {
        let (mut setup, _, _) = split_frame(KEY);
        setup[0x38..0x3a].copy_from_slice(&1280u16.to_le_bytes());
        setup[0x3a..0x3c].copy_from_slice(&720u16.to_le_bytes());
        setup[0x4c..0x50].copy_from_slice(&80u32.to_le_bytes());
        setup[0x50..0x54].copy_from_slice(&80u32.to_le_bytes());
        assert_eq!(PictureInfo::parse(&setup).unwrap().pitch, [1280, 1280]);
    }

    #[test]
    fn nvdec_writes_reference_pixels_and_keeps_channels_separate() {
        let mem = GuestMemory::new().unwrap();
        let gpu = Gpu::default();
        let mut iova = Iova::default();
        let addr = 0x20_0000;
        let size = 0x4000;
        mem.map(addr, size).unwrap();
        let base = iova.map(1, NvMap { addr, size, ..Default::default() }).unwrap() >> 8;
        let dma = Dma { iova: &iova, mem: &mem, gpu: &gpu, later: None };
        let mut nvdec = Nvdec::default();
        for (register, value) in [(0x200, 5), (0x404, base), (0x408, base + 1),
            (0x430 + 3 * 4, base + 8), (0x474 + 3 * 4, base + 24)]
        {
            nvdec.write(&dma, 1, register / 4, value).unwrap();
        }

        for (hex, expected) in [(KEY, 0xa0579ca2b84a8925), (INTER, 0x3180f6208cad4665)] {
            let (setup, frame, payload) = split_frame(hex);
            assert_eq!(PictureInfo::parse(&setup).unwrap().packet(&payload), frame);
            assert!(dma.write(base, &setup));
            assert!(dma.write(base + 1, &payload));
            if setup[0x3c] == 0 {
                assert!(nvdec.write(&dma, 2, 0x300 / 4, 1).is_err());
                let before = dma.read(base + 9, 128 * 16).unwrap();
                nvdec.write(&dma, 1, 0x474 / 4 + 3, base + 0x40).unwrap();
                assert!(nvdec.write(&dma, 1, 0x300 / 4, 1).is_err());
                assert_eq!(dma.read(base + 9, 128 * 16).unwrap(), before);
                nvdec.write(&dma, 1, 0x474 / 4 + 3, base + 24).unwrap();
            }
            nvdec.write(&dma, 1, 0x300 / 4, 1).unwrap();

            let luma = dma.read(base + 9, 128 * 16).unwrap();
            let chroma = dma.read(base + 26, 64 * 16).unwrap();
            let y = from_block_linear(&luma, 128, 16, 1);
            let uv = from_block_linear(&chroma, 64, 8, 1);
            let planar = y.chunks_exact(128).flat_map(|row| row[..16].iter().copied())
                .chain(uv.chunks_exact(64).flat_map(|row| row[..16].iter().copied().step_by(2)))
                .chain(uv.chunks_exact(64).flat_map(|row| row[1..16].iter().copied().step_by(2)));
            let hash = planar.fold(0xcbf29ce484222325u64, |hash, byte| {
                (hash ^ u64::from(byte)).wrapping_mul(0x100000001b3)
            });
            assert_eq!(hash, expected);
        }
        nvdec.close_vp8_channel(1);
        assert!(nvdec.write(&dma, 1, 0x300 / 4, 1).is_err());
    }
}
