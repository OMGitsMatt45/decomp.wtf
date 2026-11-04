"""Checked adapter for the pinned MIT host audio sink and its signal tests."""
from pathlib import Path

from ..pc import PCError


def install(native,app):
    audio=(native/'runtime/crates/zakuro/src/audio.rs').read_text(encoding='utf-8')
    def change(before,after,count=1):
        nonlocal audio
        if audio.count(before)!=count:
            raise PCError('pinned 3DS audio integration no longer applies')
        audio=audio.replace(before,after)
    change('|error| log::warn!("sound output, {error}"),','|error| eprintln!("3DS audio output: {error}"),')
    change('    refill: usize,','    refill: usize,\n    played: u64,\n    nonzero: u64,')
    change('            refill: RESUME,','            refill: RESUME,\n            played: 0,\n            nonzero: 0,',count=2)
    change('use std::collections::VecDeque;', '''#[path = "audio_quality.rs"]
mod quality;
use super::presentation::AudioProfile;
use std::collections::VecDeque;''')
    change('''/// the queue stretches sound only once it is down to this, about 63 ms.
/// every stretch splices the sound, so smaller shortfalls are left to DRIFT.
const STRETCH_BELOW: usize = TARGET / 2;
''', '')
    change('    nonzero: u64,', '    nonzero: u64,\n    target: usize,\n    filter: quality::Filter,')
    change('self.samples.len() < 2', 'self.samples.len() <= self.step.ceil().max(1.0) as usize')
    change('            self.refill = RESUME;', '''            self.refill = refill_at(self.target);
            self.fraction = self.fraction.fract();''')
    change('''        let (a, b) = (self.samples[0], self.samples[1]);
        let t = self.fraction as f32;
        let out = [a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t];''',
        '        let out = self.filter.sample(&self.samples, self.fraction);')
    change('(self.samples.len() as f64 - TARGET as f64) / TARGET as f64',
        '(self.samples.len() as f64 - self.target as f64) / self.target as f64')
    change('            self.samples.pop_front();', '            self.filter.consume(self.samples.pop_front().unwrap());')
    change('        self.refill = TARGET;', '        self.refill = self.target;\n        self.filter.clear();')
    change('    _stream: cpal::Stream,', '    device_name: String,\n    output_rate: u32,\n    _stream: cpal::Stream,')
    change('''    pub fn open(rate: f64) -> Result<Audio, String> {
        let host = cpal::default_host();
        let device = host.default_output_device().ok_or("there is no sound output device")?;''',
        '''    #[cfg(test)]
    pub fn open(rate: f64) -> Result<Audio, String> {
        Self::open_with(rate, AudioProfile::Stable, None)
    }

    pub fn open_with(rate: f64, profile: AudioProfile, selected: Option<usize>) -> Result<Audio, String> {
        let host = cpal::default_host();
        let device = match selected {
            Some(index) => host.output_devices().map_err(|error| error.to_string())?
                .nth(index).ok_or_else(|| format!("audio output {index} was not found; use --list-audio-devices"))?,
            None => host.default_output_device().ok_or("there is no sound output device")?,
        };
        let device_name = device.name().unwrap_or_else(|_| "Unnamed output".into());''')
    change('        let queue = Arc::new(Mutex::new(Queue {', '''        let target = profile.target();
        let step = rate / config.sample_rate.0 as f64;
        let queue = Arc::new(Mutex::new(Queue {''')
    change('            step: rate / config.sample_rate.0 as f64,','            step,')
    change('''            starved: true,
            last: [0.0; 2],
            underruns: 0,
            refill: RESUME,
            played: 0,
            nonzero: 0,''','''            starved: true,
            last: [0.0; 2],
            underruns: 0,
            refill: refill_at(target),
            played: 0,
            nonzero: 0,
            target,
            filter: quality::Filter::new(step),''')
    change('''            starved: false,
            last: [0.0; 2],
            underruns: 0,
            refill: RESUME,
            played: 0,
            nonzero: 0,''','''            starved: false,
            last: [0.0; 2],
            underruns: 0,
            refill: RESUME,
            played: 0,
            nonzero: 0,
            target: TARGET,
            filter: quality::Filter::new(step),''')
    change('stretch: std::cell::RefCell::new(Stretch::new()), _stream: stream',
        'stretch: std::cell::RefCell::new(Stretch::new()), device_name, output_rate: config.sample_rate.0, _stream: stream')
    change('    /// how many times the sound ran dry since the last call.', '''    pub fn report(&self) -> serde_json::Value {
        let counters = self.queue.lock().map(|q| (q.played, q.nonzero, q.underruns)).unwrap_or_default();
        serde_json::json!({"device":self.device_name,"sample_rate":self.output_rate,
            "output_frames":counters.0,"nonzero_frames":counters.1,"underruns":counters.2})
    }

    /// how many times the sound ran dry since the last call.''')
    change('''        let Ok(mut queue) = self.queue.lock() else { return };
        enqueue(&mut queue, &mut self.stretch.borrow_mut(), &samples);''','''        let factor = match self.queue.lock() {
            Ok(queue) => stretch_factor(queue.samples.len(), queue.target),
            Err(_) => return,
        };
        let mut stretched = Vec::with_capacity(samples.len() * 2);
        self.stretch.borrow_mut().process(&samples, factor, &mut stretched);
        if let Ok(mut queue) = self.queue.lock() {
            append(&mut queue, stretched);
        }''')
    change('''fn enqueue(queue: &mut Queue, stretch: &mut Stretch, samples: &[[f32; 2]]) {
    let short = STRETCH_BELOW.saturating_sub(queue.samples.len()) as f64 / STRETCH_BELOW as f64;
    let mut stretched = Vec::with_capacity(samples.len() * 2);
    stretch.process(samples, (1.0 + short).min(MOST_STRETCH), &mut stretched);
    queue.samples.extend(stretched);''','''fn refill_at(target: usize) -> usize {
    (target / 4).max(768)
}

fn stretch_factor(queued: usize, target: usize) -> f64 {
    // Let the small queue stretch earlier, before one late redraw empties it.
    let threshold = (target / 2).max(1536);
    let short = threshold.saturating_sub(queued) as f64 / threshold as f64;
    (1.0 + short).min(MOST_STRETCH)
}

#[cfg(test)]
fn enqueue(queue: &mut Queue, stretch: &mut Stretch, samples: &[[f32; 2]]) {
    let mut stretched = Vec::with_capacity(samples.len() * 2);
    stretch.process(samples, stretch_factor(queue.samples.len(), queue.target), &mut stretched);
    append(queue, stretched);
}

fn append(queue: &mut Queue, stretched: Vec<[f32; 2]>) {
    queue.samples.extend(stretched);''')
    change('''    if queue.samples.len() > TARGET * 4 {
        let excess = queue.samples.len() - TARGET;
        queue.samples.drain(..excess);
    }
}''','''    if queue.samples.len() > queue.target * 4 {
        let excess = queue.samples.len() - queue.target;
        queue.samples.drain(..excess);
        queue.fraction = 0.0;
        queue.filter.clear();
    }
}

pub fn list_devices() -> Result<(), String> {
    let host = cpal::default_host();
    let default = host.default_output_device().and_then(|device| device.name().ok());
    if let Some(name) = default { println!("default  {name}"); }
    for (index, device) in host.output_devices().map_err(|error| error.to_string())?.enumerate() {
        println!("{index}  {}", device.name().unwrap_or_else(|_| "Unnamed output".into()));
    }
    Ok(())
}''')
    # Used by the original queue tests only. The live target comes from the profile.
    change('const TARGET: usize = 4096;', '#[cfg(test)]\nconst TARGET: usize = 4096;')
    change('const RESUME: usize = TARGET / 4;', '#[cfg(test)]\nconst RESUME: usize = TARGET / 4;')
    change('                    let [left, right] = queue.next();',
        '''                    let [left, right] = queue.next();
                    queue.played += 1;
                    if left != 0.0 || right != 0.0 { queue.nonzero += 1; }''')
    change('    /// how many times the sound ran dry since the last call.',
        '''    #[cfg(test)]
    pub fn output_frames(&self) -> (u64,u64) {
        self.queue.lock().map(|q|(q.played,q.nonzero)).unwrap_or((0,0))
    }

    /// how many times the sound ran dry since the last call.''')
    audio+='\n'+Path(__file__).with_name('audio_device_test.rs').read_text(encoding='utf-8')
    (app/'src/audio.rs').write_text(audio,encoding='utf-8')
    (app/'src/audio_quality.rs').write_bytes(Path(__file__).with_name('audio_quality.rs').read_bytes())
