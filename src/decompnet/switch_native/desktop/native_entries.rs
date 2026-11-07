//! Cache immutable entry locations; guest code bytes are still checked on every entry.
use std::cell::Cell;

pub(super) struct Code {
    pub base: u64,
    pub text: Vec<u8>,
    pub entries: Vec<u64>,
}

const SLOTS: usize = 4096;
#[derive(Clone, Copy)]
struct Hint { address: u64, module: usize, index: usize }
thread_local! {
    static ENTRIES: [Cell<Hint>; SLOTS] = const {
        [const { Cell::new(Hint { address: 0, module: usize::MAX, index: 0 }) }; SLOTS]
    };
}

fn slot(address: u64) -> usize { ((address >> 2) ^ (address >> 14)) as usize & (SLOTS - 1) }

pub(super) struct Entry<'a> {
    pub code: &'a Code,
    pub index: usize,
    pub address: u64,
    pub end: u64,
}

impl Entry<'_> {
    /// The reservation and the entry range are live, as for the uncached guard.
    /// No validation result is cached: compare the complete guest range each time.
    #[inline]
    pub unsafe fn matches(&self, memory: *const u8) -> bool {
        let offset = (self.address - self.code.base) as usize;
        let size = (self.end - self.address) as usize;
        let bytes = unsafe { std::slice::from_raw_parts(memory.add(self.address as usize), size) };
        entry_bytes_equal(bytes, &self.code.text[offset..offset + size])
    }
}

// Use fixed-width loads only when their union covers the entire span.
#[inline]
fn entry_bytes_equal(live: &[u8], expected: &[u8]) -> bool {
    #[cfg(target_arch = "x86_64")]
    {
        use std::ptr::read_unaligned;
        if live.len() != expected.len() { return false; }
        let len = live.len();
        let a = live.as_ptr();
        let b = expected.as_ptr();
        // Each load stays in its slice. For 9..16 bytes the two eight-byte
        // ranges overlap or meet, so every byte participates.
        unsafe {
            if len == 4 {
                return read_unaligned(a.cast::<u32>()) == read_unaligned(b.cast::<u32>());
            }
            if len == 8 {
                return read_unaligned(a.cast::<u64>()) == read_unaligned(b.cast::<u64>());
            }
            if (9..=16).contains(&len) {
                let offset = len - 8;
                let head = read_unaligned(a.cast::<u64>()) ^ read_unaligned(b.cast::<u64>());
                let tail = read_unaligned(a.add(offset).cast::<u64>()) ^ read_unaligned(b.add(offset).cast::<u64>());
                return head | tail == 0;
            }
        }
    }
    live == expected
}

pub(super) struct Lookup<'a> {
    pub entry: Option<Entry<'a>>,
    pub cache_hit: bool,
    pub hint_hit: bool,
    pub searched: bool,
}

fn entry(code: &Code, index: usize, address: u64) -> Option<Entry<'_>> {
    let text_end = code.base.checked_add(code.text.len() as u64)?;
    if address < code.base || address >= text_end || code.entries.get(index) != Some(&address) {
        return None;
    }
    let end = code.entries.get(index + 1).copied().unwrap_or(text_end);
    if end <= address || end > text_end { return None; }
    Some(Entry { code, index, address, end })
}

/// CONFIG is immutable. Cached indices must still match this exact address and
/// module range, including when a slot collides or a fixture changes modules.
#[inline]
pub(super) fn lookup(codes: &[Code], address: u64, last: u64, next: u64, index: u64, cache: bool) -> Lookup<'_> {
    if cache {
        let hint = ENTRIES.with(|hints| hints[slot(address)].get());
        if hint.address == address
            && let Some(code) = codes.get(hint.module)
            && let Some(found) = entry(code, hint.index, address)
        {
            return Lookup { entry: Some(found), cache_hit: true, hint_hit: false, searched: false };
        }
    }
    let Some((module, code)) = codes.iter().enumerate().find(|(_, code)| {
            address >= code.base && address.checked_sub(code.base).is_some_and(|offset| offset < code.text.len() as u64)
        }) else {
            return Lookup { entry: None, cache_hit: false, hint_hit: false, searched: false };
        };
        let is_next = next == address;
        let hint_index = (index as usize).checked_add(usize::from(is_next));
        let (index, hint_hit, searched) = if (is_next || last == address)
            && let Some(index) = hint_index
            && code.entries.get(index) == Some(&address)
        {
            (Some(index), true, false)
        } else {
            (code.entries.binary_search(&address).ok(), false, true)
        };
        let found = index.and_then(|index| entry(code, index, address));
        if cache && let Some(found) = &found {
            ENTRIES.with(|hints| hints[slot(address)].set(Hint { address, module, index: found.index }));
        }
        Lookup { entry: found, cache_hit: false, hint_hit, searched }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn short_entry_comparison_covers_every_byte_and_alignment() {
        for len in 0..=64 {
            for offset in 0..8 {
                let expected = vec![0xa6; len + 8];
                let mut live = vec![0xa6; len + 8];
                let wanted = &expected[7 - offset..7 - offset + len];
                let span = &mut live[offset..offset + len];
                assert!(entry_bytes_equal(span, wanted));
                for byte in 0..len {
                    span[byte] ^= 1;
                    assert!(!entry_bytes_equal(span, wanted));
                    span[byte] ^= 1;
                }
                assert!(!entry_bytes_equal(span, &expected[..len + 1]));
            }
        }
    }

    fn code(base: u64, entries: Vec<u64>) -> Code {
        Code { base, text: (0..64).collect(), entries }
    }

    #[test]
    fn warm_entry_still_checks_every_guest_byte() {
        let codes = [code(0x1000, vec![0x1000, 0x1010])];
        let mut memory = vec![0; 0x1040];
        memory[0x1000..].copy_from_slice(&codes[0].text);
        let cold = lookup(&codes, 0x1000, 0, 0, 0, true);
        assert!(cold.entry.is_some());
        assert!(unsafe { cold.entry.unwrap().matches(memory.as_ptr()) });
        for byte in 0x1000..0x1010 {
            memory[byte] ^= 1;
            let warm = lookup(&codes, 0x1000, 0, 0, 0, true);
            assert!(warm.cache_hit);
            assert!(!unsafe { warm.entry.unwrap().matches(memory.as_ptr()) });
            memory[byte] ^= 1;
        }
        let warm = lookup(&codes, 0x1000, 0, 0, 0, true);
        assert!(unsafe { warm.entry.unwrap().matches(memory.as_ptr()) });
    }

    #[test]
    fn colliding_slots_do_not_reuse_another_address() {
        let first = 0x2000;
        let second = first + (1 << 28);
        assert_eq!(slot(first), slot(second));
        let codes = [code(first, vec![first]), code(second, vec![second])];
        for address in [first, second, first, second] {
            let found = lookup(&codes, address, 0, 0, 0, true).entry.unwrap();
            assert_eq!(found.address, address);
            assert_eq!(found.code.base, address);
        }
    }

    #[test]
    fn cached_indices_are_rechecked_across_module_changes() {
        let codes = [code(0x3000, vec![0x3000]), code(0x4000, vec![0x4000])];
        lookup(&codes, 0x3000, 0, 0, 0, true).entry.unwrap();
        let swapped = [code(0x4000, vec![0x4000]), code(0x3000, vec![0x3000])];
        let found = lookup(&swapped, 0x3000, 0, 0, 0, true);
        assert!(!found.cache_hit);
        assert_eq!(found.entry.unwrap().code.base, 0x3000);
        let changed = [code(0x3000, vec![0x3000, 0x3010])];
        lookup(&changed, 0x3010, 0, 0, 0, true).entry.unwrap();
        let shifted = [code(0x3000, vec![0x3000, 0x3008, 0x3010])];
        let found = lookup(&shifted, 0x3010, 0, 0, 0, true);
        assert!(!found.cache_hit);
        assert_eq!(found.entry.unwrap().index, 2);
        assert!(lookup(&shifted, 0x3014, 0, 0, 0, true).entry.is_none());
    }

    #[test]
    fn last_and_next_hints_remain_exact_fallbacks() {
        let codes = [code(0x5000, vec![0x5000, 0x5010, 0x5020])];
        let last = lookup(&codes, 0x5000, 0x5000, 0x5010, 0, true);
        assert!(last.hint_hit && !last.searched);
        let next = lookup(&codes, 0x5010, 0x5000, 0x5010, 0, true);
        assert!(next.hint_hit && !next.searched);
        let stale = lookup(&codes, 0x5020, 0x5020, 0, 99, true);
        assert!(stale.searched && !stale.hint_hit);
        assert_eq!(stale.entry.unwrap().index, 2);
    }

    #[test]
    fn disabled_cache_uses_the_original_hint_and_search_paths() {
        let codes = [code(0x6000, vec![0x6000, 0x6010])];
        lookup(&codes, 0x6000, 0, 0, 0, true).entry.unwrap();
        let disabled = lookup(&codes, 0x6000, 0, 0, 0, false);
        assert!(!disabled.cache_hit && disabled.searched);
        let hinted = lookup(&codes, 0x6010, 0x6000, 0x6010, 0, false);
        assert!(!hinted.cache_hit && hinted.hint_hit && !hinted.searched);
        let mut memory = vec![0; 0x6040];
        memory[0x6000..].copy_from_slice(&codes[0].text);
        assert!(unsafe { disabled.entry.unwrap().matches(memory.as_ptr()) });
        memory[0x600f] ^= 1;
        let disabled = lookup(&codes, 0x6000, 0, 0, 0, false);
        assert!(!unsafe { disabled.entry.unwrap().matches(memory.as_ptr()) });
        assert!(lookup(&codes, 0x6000, 0, 0, 0, true).cache_hit);
    }
}
