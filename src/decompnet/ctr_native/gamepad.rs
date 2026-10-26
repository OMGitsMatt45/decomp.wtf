//! Standard controller input, merged with keyboard/touch instead of replacing it.
use gilrs::{Axis,Button,Gilrs};
use zakuro_core::services::hid::{InputState,PadState};

const BUTTONS:&[(Button,PadState)]=&[
    (Button::East,PadState::A),(Button::South,PadState::B),
    (Button::North,PadState::X),(Button::West,PadState::Y),
    (Button::LeftTrigger,PadState::L),(Button::RightTrigger,PadState::R),
    (Button::LeftTrigger2,PadState::ZL),(Button::RightTrigger2,PadState::ZR),
    (Button::Start,PadState::START),(Button::Select,PadState::SELECT),
    (Button::DPadUp,PadState::UP),(Button::DPadDown,PadState::DOWN),
    (Button::DPadLeft,PadState::LEFT),(Button::DPadRight,PadState::RIGHT),
];

fn merge(mut input:InputState,held:impl Fn(Button)->bool,axis:impl Fn(Axis)->f32)->InputState {
    for &(button,state) in BUTTONS {
        if held(button) {input.buttons.insert(state);}
    }
    for (pressed,state) in [(axis(Axis::DPadX)>0.5,PadState::RIGHT),(axis(Axis::DPadX)< -0.5,PadState::LEFT),
        (axis(Axis::DPadY)>0.5,PadState::UP),(axis(Axis::DPadY)< -0.5,PadState::DOWN)] {
        if pressed {input.buttons.insert(state);}
    }
    let (x,y)=(axis(Axis::LeftStickX),axis(Axis::LeftStickY));
    if x.hypot(y)>0.15 {input.circle_x=x.clamp(-1.0,1.0);input.circle_y=y.clamp(-1.0,1.0);}
    let (x,y)=(axis(Axis::RightStickX),axis(Axis::RightStickY));
    if x.hypot(y)>0.15 {input.c_stick_x=x.clamp(-1.0,1.0);input.c_stick_y=y.clamp(-1.0,1.0);}
    input
}

pub struct Gamepads {gilrs:Option<Gilrs>,pub error:Option<String>}
impl Gamepads {
    pub fn new()->Self {
        match Gilrs::new() {
            Ok(gilrs)=>Self {gilrs:Some(gilrs),error:None},
            Err(error)=>Self {gilrs:None,error:Some(error.to_string())},
        }
    }
    pub fn count(&self)->usize {self.gilrs.as_ref().map_or(0,|g|g.gamepads().count())}
    pub fn apply(&mut self,mut input:InputState)->InputState {
        let Some(gilrs)=&mut self.gilrs else {return input;};
        while gilrs.next_event().is_some() {}
        for (_,pad) in gilrs.gamepads() {
            input=merge(input,|b|pad.is_pressed(b),|a|pad.value(a));
        }
        input
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn absent_or_idle_controller_preserves_keyboard_and_touch() {
        let input=InputState {buttons:PadState::A,circle_x:1.0,touch:Some((123,45)),..InputState::default()};
        assert_eq!(merge(input,|_|false,|_|0.0),input);
    }
    #[test]
    fn buttons_axes_and_keyboard_combine_without_stale_releases() {
        let keyboard=InputState {buttons:PadState::L,touch:Some((20,10)),..InputState::default()};
        let input=merge(keyboard,|b|matches!(b,Button::East|Button::Start),|a|match a {
            Axis::LeftStickX=>0.7,Axis::RightStickY=>-0.8,Axis::DPadX=>-1.0,_=>0.0});
        assert!(input.buttons.contains(PadState::A|PadState::START|PadState::L|PadState::LEFT));
        assert_eq!((input.circle_x,input.c_stick_y,input.touch),(0.7,-0.8,Some((20,10))));
        assert_eq!(merge(keyboard,|_|false,|_|0.0),keyboard);
    }
}
