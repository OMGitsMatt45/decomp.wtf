// Original signal through the actual host callback; virtual-device evidence.
#[cfg(test)]
mod device_test {
    use super::*;
    #[test]
    fn original_tone_reaches_a_requested_virtual_output() {
        if std::env::var("DECOMP_TEST_3DS_AUDIO_NULL").as_deref()!=Ok("1") {return;}
        let audio=Audio::open(zakuro_core::AUDIO_SAMPLE_RATE).expect("open the selected virtual audio output");
        let samples=(0..8192).map(|i|{
            let x=(std::f64::consts::TAU*440.0*i as f64/zakuro_core::AUDIO_SAMPLE_RATE).sin();
            let value=(x*12000.0) as i16;
            [value,-value]
        }).collect::<Vec<_>>();
        audio.push(&samples);
        for _ in 0..100 {
            let (played,nonzero)=audio.output_frames();
            if played>0 && nonzero>0 {return;}
            std::thread::sleep(std::time::Duration::from_millis(2));
        }
        panic!("the virtual output did not consume the original nonzero signal");
    }
}
