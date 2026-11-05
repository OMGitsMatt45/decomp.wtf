//! Desktop applet policy for a single, foreground application session.
//! Operation/performance mode stay fixed; notification enables and focus,
//! capture and suspension policies persist for the lifetime of that session.

#[derive(Default, Debug)]
pub(super) struct ControlState {
    exit_locks: u32,
    screenshot_permission: u32,
    operation_notifications: bool,
    performance_notifications: bool,
    focus_handling: [bool; 3],
    restart_messages: bool,
    out_of_focus_suspending: bool,
    firmware_section: bool,
    capture_button_messages: bool,
    album_orientation: u32,
}

impl ControlState {
    pub(super) fn apply(&mut self, command: u32, data: &[u8]) -> Option<u32> {
        fn flag(data: &[u8], i: usize) -> Option<bool> {
            let value = *data.get(i)?;
            (value <= 1).then_some(value != 0)
        }
        fn word(data: &[u8]) -> Option<u32> {
            Some(u32::from_le_bytes(data.get(..4)?.try_into().ok()?))
        }
        match command {
            1 => self.exit_locks = self.exit_locks.checked_add(1)?,
            2 => self.exit_locks = self.exit_locks.saturating_sub(1),
            10 => {
                let permission = word(data)?;
                if permission > 2 { return None; }
                self.screenshot_permission = permission;
            }
            11 => self.operation_notifications = flag(data, 0)?,
            12 => self.performance_notifications = flag(data, 0)?,
            13 => self.focus_handling = [flag(data, 0)?, flag(data, 1)?, flag(data, 2)?],
            14 => self.restart_messages = flag(data, 0)?,
            16 => self.out_of_focus_suspending = flag(data, 0)?,
            17 => {
                let enabled = flag(data, 0)?;
                if self.firmware_section == enabled { return Some(0x40280); }
                self.firmware_section = enabled;
            }
            18 => self.capture_button_messages = flag(data, 0)?,
            19 => {
                let orientation = word(data)?;
                if orientation > 3 { return None; }
                self.album_orientation = orientation;
            }
            _ => return None,
        }
        Some(0)
    }
}

#[cfg(test)]
mod tests {
    use super::ControlState;

    #[test]
    fn focus_flags_are_packed_and_retained() {
        let mut state = ControlState::default();
        assert_eq!(state.apply(13, &[1, 0, 1, 0, 0, 0, 0, 0]), Some(0));
        assert_eq!(state.focus_handling, [true, false, true]);
        assert_eq!(state.apply(13, &[0, 1, 0]), Some(0));
        assert_eq!(state.focus_handling, [false, true, false]);
    }

    #[test]
    fn malformed_and_unknown_controls_remain_unhandled() {
        let mut state = ControlState::default();
        for (command, data) in [(13, vec![1, 0]), (13, vec![1, 2, 0]),
                               (10, 3u32.to_le_bytes().to_vec()), (15, vec![0; 32]), (999, vec![])] {
            assert_eq!(state.apply(command, &data), None);
        }
        assert_eq!(state.focus_handling, [false; 3]);
    }

    #[test]
    fn firmware_section_rejects_duplicate_state() {
        let mut state = ControlState::default();
        assert_eq!(state.apply(17, &[0]), Some(0x40280));
        assert_eq!(state.apply(17, &[1]), Some(0));
        assert_eq!(state.apply(17, &[1]), Some(0x40280));
        assert_eq!(state.apply(17, &[0]), Some(0));
    }

    #[test]
    fn session_policies_and_exit_locks_persist() {
        let mut state = ControlState::default();
        for command in [11, 12, 14, 16, 18] { assert_eq!(state.apply(command, &[1]), Some(0)); }
        assert!(state.operation_notifications && state.performance_notifications && state.restart_messages);
        assert!(state.out_of_focus_suspending && state.capture_button_messages);
        assert_eq!(state.apply(10, &2u32.to_le_bytes()), Some(0));
        assert_eq!(state.screenshot_permission, 2);
        assert_eq!(state.apply(1, &[]), Some(0));
        assert_eq!(state.apply(1, &[]), Some(0));
        assert_eq!(state.exit_locks, 2);
        assert_eq!(state.apply(2, &[]), Some(0));
        assert_eq!(state.exit_locks, 1);
    }
}
