use zakuro_gpu::backend::ScreenFilter;

#[derive(Clone, Copy, Default)]
pub enum AudioProfile {
    #[default]
    Stable,
    LowLatency,
}

impl AudioProfile {
    pub fn name(self) -> &'static str {
        match self {
            Self::Stable => "stable",
            Self::LowLatency => "low-latency",
        }
    }

    pub fn target(self) -> usize {
        match self {
            Self::Stable => 4096,
            Self::LowLatency => 1536,
        }
    }
}

#[derive(Default)]
pub struct Settings {
    pub scale: Option<u32>,
    pub filter: ScreenFilter,
    pub audio_profile: AudioProfile,
    pub audio_device: Option<usize>,
}

impl Settings {
    pub fn option(&mut self, arg: &str, args: &mut impl Iterator<Item = String>) -> Result<bool, String> {
        let value = |args: &mut _| -> Result<String, String> {
            Iterator::next(args).ok_or_else(|| format!("{arg} needs a value"))
        };
        match arg {
            "--scale" => {
                let value = value(args)?;
                self.scale = if value == "auto" { None } else {
                    Some(value.parse::<u32>().ok().filter(|scale| *scale > 0)
                        .ok_or("--scale must be auto or a positive integer")?)
                };
            }
            "--filter" => self.filter = match value(args)?.as_str() {
                "smooth" => ScreenFilter::Smooth,
                "sharp" => ScreenFilter::Sharp,
                _ => return Err("--filter must be smooth or sharp".into()),
            },
            "--audio-profile" => self.audio_profile = match value(args)?.as_str() {
                "stable" => AudioProfile::Stable,
                "low-latency" => AudioProfile::LowLatency,
                _ => return Err("--audio-profile must be stable or low-latency".into()),
            },
            "--audio-device" => {
                let value = value(args)?;
                self.audio_device = if value == "default" { None } else {
                    Some(value.parse().map_err(|_| "--audio-device must be default or an output index")?)
                };
            }
            _ => return Ok(false),
        }
        Ok(true)
    }

    pub fn cycle_scale(&mut self) {
        self.scale = match self.scale {
            None => Some(1),
            Some(scale @ 1..=5) => Some(scale + 1),
            _ => None,
        };
    }

    pub fn toggle_filter(&mut self) {
        self.filter = if self.filter == ScreenFilter::Sharp {
            ScreenFilter::Smooth
        } else {
            ScreenFilter::Sharp
        };
    }

    pub fn filter_name(&self) -> &'static str {
        if self.filter == ScreenFilter::Sharp { "sharp" } else { "smooth" }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn desktop_presets_and_flags() {
        let mut settings = Settings::default();
        for (arg, value) in [
            ("--scale", "4"), ("--filter", "sharp"),
            ("--audio-profile", "low-latency"), ("--audio-device", "2"),
        ] {
            assert!(settings.option(arg, &mut [value.to_owned()].into_iter()).unwrap());
        }
        assert_eq!(settings.scale, Some(4));
        assert_eq!(settings.filter_name(), "sharp");
        assert_eq!(settings.audio_profile.target(), 1536);
        assert_eq!(settings.audio_device, Some(2));
        assert!(settings.option("--scale", &mut ["0".into()].into_iter()).is_err());
        for expected in [Some(5), Some(6), None, Some(1)] {
            settings.cycle_scale();
            assert_eq!(settings.scale, expected);
        }
    }
}
