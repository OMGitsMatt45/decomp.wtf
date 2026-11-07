use super::{CLASS_2D, CLASS_3D, CLASS_COMPUTE, CLASS_DMA, CLASS_INLINE, fxhash::FastMap};

const CLASSES: [u32; 6] = [0, CLASS_3D, CLASS_COMPUTE, CLASS_INLINE, CLASS_DMA, CLASS_2D];

#[inline]
fn slot(class: u32) -> Option<usize> {
    Some(match class {
        0 => 0,
        CLASS_3D => 1,
        CLASS_COMPUTE => 2,
        CLASS_INLINE => 3,
        CLASS_DMA => 4,
        CLASS_2D => 5,
        _ => return None,
    })
}

pub(super) struct Registers {
    fixed: bool,
    known: [Option<Vec<u32>>; CLASSES.len()],
    other: FastMap<u32, Vec<u32>>,
}

impl Registers {
    pub(super) fn new(fixed: bool) -> Self {
        Self { fixed, known: std::array::from_fn(|_| None), other: FastMap::default() }
    }

    #[inline]
    pub(super) fn get_or_insert(&mut self, class: u32, words: usize) -> &mut Vec<u32> {
        if self.fixed && let Some(i) = slot(class) {
            return self.known[i].get_or_insert_with(|| vec![0; words]);
        }
        self.other.entry(class).or_insert_with(|| vec![0; words])
    }

    #[inline]
    pub(super) fn get(&self, class: &u32) -> Option<&Vec<u32>> {
        if self.fixed && let Some(i) = slot(*class) { return self.known[i].as_ref(); }
        self.other.get(class)
    }

    #[inline]
    pub(super) fn get_mut(&mut self, class: &u32) -> Option<&mut Vec<u32>> {
        if self.fixed && let Some(i) = slot(*class) { return self.known[i].as_mut(); }
        self.other.get_mut(class)
    }

    #[cfg(test)]
    pub(super) fn iter(&self) -> impl Iterator<Item = (&u32, &Vec<u32>)> {
        CLASSES.iter().zip(self.known.iter()).filter_map(|(class, regs)| Some((class, regs.as_ref()?)))
            .chain(self.other.iter())
    }
}

impl std::ops::Index<&u32> for Registers {
    type Output = Vec<u32>;

    #[inline]
    fn index(&self, class: &u32) -> &Self::Output {
        self.get(class).expect("engine register class is initialized")
    }
}
