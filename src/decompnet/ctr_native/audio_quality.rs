//! Band-limited stereo reconstruction without allocations in the device callback.
use std::collections::VecDeque;
use std::f64::consts::PI;

const HALF: usize = 16;
const TAPS: usize = HALF * 2;
const PHASES: usize = 256;

pub(super) struct Filter {
    weights: Vec<[f32; TAPS]>,
    history: VecDeque<[f32; 2]>,
}

impl Filter {
    pub(super) fn new(input_per_output: f64) -> Self {
        // Leave headroom for clock drift and reduce the bandwidth when downsampling.
        let cutoff = 0.94 / input_per_output.max(1.0);
        let weights = (0..=PHASES).map(|phase| {
            let fraction = phase as f64 / PHASES as f64;
            let weights: [f64; TAPS] = std::array::from_fn(|tap| {
                let x = tap as f64 - (HALF - 1) as f64 - fraction;
                let sinc = if x == 0.0 { cutoff } else { (PI * x * cutoff).sin() / (PI * x) };
                let window = 0.42 + 0.5 * (PI * x / HALF as f64).cos()
                    + 0.08 * (2.0 * PI * x / HALF as f64).cos();
                sinc * window
            });
            let sum: f64 = weights.iter().sum();
            weights.map(|weight| (weight / sum) as f32)
        }).collect();
        Self { weights, history: VecDeque::with_capacity(HALF) }
    }

    pub(super) fn consume(&mut self, sample: [f32; 2]) {
        if self.history.len() == HALF - 1 {
            self.history.pop_front();
        }
        self.history.push_back(sample);
    }

    pub(super) fn clear(&mut self) {
        self.history.clear();
    }

    pub(super) fn sample(&self, future: &VecDeque<[f32; 2]>, fraction: f64) -> [f32; 2] {
        // At startup or the tail of an underrun, do not convolve across a gap.
        if self.history.len() < HALF - 1 || future.len() <= HALF {
            let (a, b) = (future[0], future[1]);
            let t = fraction as f32;
            return [a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t];
        }
        let phase = (fraction * PHASES as f64).round() as usize;
        let mut out = [0.0; 2];
        for (frame, &weight) in self.history.iter().chain(future).zip(&self.weights[phase]) {
            out[0] += frame[0] * weight;
            out[1] += frame[1] * weight;
        }
        out.map(|sample| sample.clamp(-1.0, 1.0))
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn keeps_stereo_dc_gain_and_rejects_downsampling_alias() {
        let mut filter = Filter::new(2.0);
        let mut future = VecDeque::from(vec![[0.6, -0.3]; TAPS]);
        for _ in 0..HALF { filter.consume([0.6, -0.3]); }
        let sample = filter.sample(&future, 0.37);
        assert!((sample[0] - 0.6).abs() < 1e-6);
        assert!((sample[1] + 0.3).abs() < 1e-6);

        let input = |i: usize| if i % 2 == 0 { [0.8, -0.8] } else { [-0.8, 0.8] };
        filter.clear();
        for i in 0..HALF - 1 { filter.consume(input(i)); }
        for (i, sample) in future.iter_mut().enumerate() { *sample = input(i + HALF - 1); }
        assert!(filter.sample(&future, 0.0)[0].abs() < 0.005);
    }
}
