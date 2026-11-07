//! A GP-FIFO entry is a segment of the method stream, not a packet boundary.
//! NVIDIA PBDMA documents compressed method sequences spanning PB segments:
//! https://github.com/NVIDIA/open-gpu-doc/blob/master/manuals/turing/tu104/dev_pbdma.ref.txt

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
struct Packet {
    kind: u32,
    sub: u32,
    method: u32,
    remaining: u32,
    consumed: u32,
}

#[derive(Default, Debug, PartialEq, Eq)]
pub(super) struct Stream {
    packet: Option<Packet>,
}

impl Stream {
    pub(super) fn is_idle(&self) -> bool { self.packet.is_none() }

    pub(super) fn next(&mut self, words: &[u32], at: &mut usize) -> Option<(u32, u32, u32)> {
        loop {
            if let Some(packet) = self.packet.as_mut() {
                let value = *words.get(*at)?;
                *at += 1;
                let method = packet.method + match packet.kind {
                    1 => packet.consumed,
                    3 => 0,
                    _ => u32::from(packet.consumed != 0),
                };
                let sub = packet.sub;
                packet.consumed += 1;
                packet.remaining -= 1;
                if packet.remaining == 0 { self.packet = None; }
                return Some((sub, method, value));
            }
            let header = *words.get(*at)?;
            *at += 1;
            let (kind, count, sub, method) = (header >> 29, header >> 16 & 0x1fff, header >> 13 & 7, header & 0xfff);
            match kind {
                1 | 3 | 5 if count != 0 => self.packet = Some(Packet { kind, sub, method, remaining: count, consumed: 0 }),
                4 => return Some((sub, method, count)),
                _ => {}
            }
        }
    }

    /// Host-model execution must not bypass an entry that leaves raw parameters
    /// for the next segment, even when the stream was initially idle.
    pub(super) fn complete_entry(words: &[u32]) -> bool {
        let mut at = 0;
        while let Some(&header) = words.get(at) {
            at += 1;
            if matches!(header >> 29, 1 | 3 | 5) {
                let count = (header >> 16 & 0x1fff) as usize;
                if count > words.len() - at { return false; }
                at += count;
            }
        }
        true
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn decode(parts: &[&[u32]]) -> (Stream, Vec<(u32,u32,u32)>) {
        let mut stream = Stream::default();
        let mut methods = Vec::new();
        for part in parts {
            let mut at = 0;
            while let Some(method) = stream.next(part, &mut at) { methods.push(method); }
        }
        (stream, methods)
    }

    #[test]
    fn every_split_preserves_incrementing_nonincrementing_and_increment_once() {
        for kind in [1,3,5] {
            let words = [kind << 29 | 6 << 16 | 2 << 13 | 0x480, 0, 0xffff_ffff, 0x2001_0000, 7, 0, 0x8000_0001];
            let (expected, methods) = decode(&[&words]);
            assert!(expected.is_idle());
            for split in 0..=words.len() {
                assert_eq!(decode(&[&words[..split], &[], &words[split..]]), (Stream::default(), methods.clone()));
            }
            let parts: Vec<_> = words.chunks(1).collect();
            assert_eq!(decode(&parts), (Stream::default(), methods.clone()));
            for (offset, &(sub, method, _)) in methods.iter().enumerate() {
                assert_eq!(sub, 2);
                assert_eq!(method, 0x480 + match kind {1 => offset as u32,3 => 0,_ => u32::from(offset != 0)});
            }
        }
    }

    #[test]
    fn zero_count_and_zero_valued_inline_words_do_not_reset_the_stream() {
        let words = [0x2000_0100, 0x6000_0101, 0xa000_0102, 0x8000_0103, 0x2001_0104, 0, 0];
        let expected = vec![(0,0x103,0),(0,0x104,0)];
        let parts: Vec<_> = words.chunks(1).collect();
        assert_eq!(decode(&parts), (Stream::default(),expected));
        assert!(Stream::complete_entry(&words));
        assert!(!Stream::complete_entry(&[0xa006_0e3a,4]));
        assert!(Stream::complete_entry(&[0xa006_0e3a,4,270,7,36,0,258447]));
    }

    #[test]
    fn captured_indexed_indirect_arguments_continue_the_macro_packet() {
        let prefix = [0xa006_0e3a,4];
        let arguments = [270,7,36,0,258447];
        let suffix = [0x9100_0002];
        let (stream, methods) = decode(&[&prefix,&[],&arguments,&suffix]);
        assert!(stream.is_idle());
        assert_eq!(methods, vec![(0,0xe3a,4),(0,0xe3b,270),(0,0xe3b,7),(0,0xe3b,36),(0,0xe3b,0),(0,0xe3b,258447),(0,2,0x1100)]);
    }
}
