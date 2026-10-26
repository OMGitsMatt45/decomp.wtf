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
    change('                    let [left, right] = queue.next();',
        '''                    let [left, right] = queue.next();
                    queue.played += 1;
                    if left != 0.0 || right != 0.0 { queue.nonzero += 1; }''')
    change('    /// how many times the sound ran dry since the last call.',
        '''    pub fn output_frames(&self) -> (u64,u64) {
        self.queue.lock().map(|q|(q.played,q.nonzero)).unwrap_or((0,0))
    }

    /// how many times the sound ran dry since the last call.''')
    audio+='\n'+Path(__file__).with_name('audio_device_test.rs').read_text(encoding='utf-8')
    (app/'src/audio.rs').write_text(audio,encoding='utf-8')
