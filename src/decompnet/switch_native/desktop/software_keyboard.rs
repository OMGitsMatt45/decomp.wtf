//! Desktop replacement for the normal software-keyboard applet. ABI fields:
//! libnx SwkbdArgCommon; no retail addresses or fixed trainer names.
#[derive(Debug, PartialEq)]
struct Config { prompt: String, initial: String, min: usize, max: usize }
fn string(bytes: &[u8]) -> String {
    let units: Vec<_> = bytes.chunks_exact(2).map(|b| u16::from_le_bytes([b[0],b[1]])).take_while(|&u| u != 0).collect();
    String::from_utf16_lossy(&units)
}
impl Config {
    fn read(inputs: &[Vec<u8>], capacity: usize) -> Self {
        let mut result = Self { prompt:"Enter text for the game".into(), initial:String::new(), min:0, max:capacity };
        let Some((index, arg)) = inputs.iter().enumerate().find(|(_, b)| b.len() >= 0x3d1 && b.len() <= 0x500) else { return result; };
        let word = |at| u32::from_le_bytes(arg[at..at+4].try_into().unwrap()) as usize;
        result.max = match word(0x3ac) { 0 => capacity, value => value.min(capacity) };
        result.min = word(0x3b0).min(result.max);
        let prompt: Vec<_> = [(0x24,130),(0xa6,258),(0x1a8,514)].into_iter()
            .map(|(at,len)| string(&arg[at..at+len])).filter(|s| !s.is_empty()).collect();
        if !prompt.is_empty() { result.prompt = prompt.join("\n"); }
        if let Some(work) = inputs.get(index+1) {
            let at = word(0x3c0); let bytes = word(0x3c4).checked_mul(2);
            if let Some(end) = bytes.and_then(|n| at.checked_add(n)) {
                if let Some(raw) = work.get(at..end) { result.initial = string(raw); }
            }
        }
        result
    }
    fn valid(&self, text: &str) -> bool {
        let len = text.encode_utf16().count();
        (self.min..=self.max).contains(&len) && !text.contains('\0')
    }
}
fn encode(text: Option<&str>, size: usize) -> Vec<u8> {
    let mut out = vec![0;size];
    let Some(text) = text else { out[..4].copy_from_slice(&1u32.to_le_bytes()); return out; };
    for (i, unit) in text.encode_utf16().take((size-6)/2).enumerate() {
        out[4+i*2..6+i*2].copy_from_slice(&unit.to_le_bytes());
    }
    out
}
pub(super) fn output(inputs: &[Vec<u8>], size: usize) -> Vec<u8> {
    let config = Config::read(inputs, (size-6)/2);
    #[cfg(test)]
    let text = Some("Kirikae".to_string()); // Original synthetic unit fixture only.
    #[cfg(not(test))]
    let text = if let Ok(text) = std::env::var("DECOMP_SWITCH_KEYBOARD_TEXT") {
        config.valid(&text).then_some(text)
    } else if crate::env_var!("KIRIKAE_HEADLESS").is_some() { None }
    else { dialog(&config) };
    crate::input::release_all();
    encode(text.as_deref().filter(|text| config.valid(text)), size)
}
#[cfg(not(windows))]
fn dialog(_config: &Config) -> Option<String> {
    eprintln!("decomp.wtf: interactive software keyboard requires Windows; use DECOMP_SWITCH_KEYBOARD_TEXT for scripted runs");
    None
}
#[cfg(windows)]
fn dialog(config: &Config) -> Option<String> {
    windows::show(config)
}
#[cfg(windows)]
mod windows {
    use super::Config;
    use std::ffi::c_void;
    type Window = *mut c_void;
    struct State<'a> { config: &'a Config, text: Option<String> }
    #[link(name="user32")]
    unsafe extern "system" {
        fn DialogBoxIndirectParamW(module: Window, template: *const u32, owner: Window,
            proc: unsafe extern "system" fn(Window,u32,usize,isize)->isize, param:isize) -> isize;
        fn SetWindowLongPtrW(window:Window,index:i32,value:isize)->isize;
        fn GetWindowLongPtrW(window:Window,index:i32)->isize;
        fn SetDlgItemTextW(window:Window,id:i32,text:*const u16)->i32;
        fn GetDlgItemTextW(window:Window,id:i32,text:*mut u16,count:i32)->u32;
        fn GetDlgItem(window:Window,id:i32)->Window;
        fn SendMessageW(window:Window,message:u32,w:usize,l:isize)->isize;
        fn SetFocus(window:Window)->Window;
        fn EndDialog(window:Window,result:isize)->i32;
        fn MessageBoxW(window:Window,text:*const u16,title:*const u16,kind:u32)->i32;
        fn GetActiveWindow()->Window;
    }
    fn wide(value:&str)->Vec<u16> { value.encode_utf16().chain([0]).collect() }
    unsafe extern "system" fn procedure(window:Window,message:u32,w:usize,l:isize)->isize {
        unsafe {
            if message == 0x110 {
                SetWindowLongPtrW(window,16,l);
                let state = &mut *(l as *mut State<'_>);
                SetDlgItemTextW(window,100,wide(&state.config.prompt).as_ptr());
                SetDlgItemTextW(window,101,wide(&state.config.initial).as_ptr());
                let edit = GetDlgItem(window,101);
                SendMessageW(edit,0xc5,state.config.max,0); // EM_SETLIMITTEXT
                SetFocus(edit); SendMessageW(edit,0xb1,0,-1); // EM_SETSEL
                return 0;
            }
            let ptr = GetWindowLongPtrW(window,16) as *mut State<'_>;
            if ptr.is_null() { return 0; }
            if message == 0x10 || (message == 0x111 && w & 0xffff == 2) { EndDialog(window,0); return 1; }
            if message == 0x111 && w & 0xffff == 1 {
                let state = &mut *ptr;
                let mut buffer = vec![0u16;state.config.max+1];
                let len = GetDlgItemTextW(window,101,buffer.as_mut_ptr(),buffer.len() as i32) as usize;
                let text = String::from_utf16_lossy(&buffer[..len]);
                if !state.config.valid(&text) {
                    MessageBoxW(window,wide(&format!("Enter {} to {} characters.",state.config.min,state.config.max)).as_ptr(),wide("Game keyboard").as_ptr(),0x30);
                    return 1;
                }
                state.text = Some(text); EndDialog(window,1); return 1;
            }
            0
        }
    }
    fn u16v(out:&mut Vec<u8>,value:u16) { out.extend_from_slice(&value.to_le_bytes()); }
    fn u32v(out:&mut Vec<u8>,value:u32) { out.extend_from_slice(&value.to_le_bytes()); }
    fn text(out:&mut Vec<u8>,value:&str) { for unit in wide(value) { u16v(out,unit); } }
    fn control(out:&mut Vec<u8>,class:u16,id:u16,style:u32,x:u16,y:u16,w:u16,h:u16,label:&str) {
        while out.len()%4 != 0 { out.push(0); }
        u32v(out,style); u32v(out,0); for n in [x,y,w,h,id,0xffff,class] { u16v(out,n); }
        text(out,label); u16v(out,0);
    }
    pub(super) fn show(config:&Config)->Option<String> {
        let mut data = Vec::new();
        u32v(&mut data,0x80c808c0); u32v(&mut data,0);
        for n in [4,0,0,280,105,0,0] { u16v(&mut data,n); }
        text(&mut data,"Game keyboard"); u16v(&mut data,9); text(&mut data,"Segoe UI");
        control(&mut data,0x82,100,0x50000000,12,10,256,30,"");
        control(&mut data,0x81,101,0x50810080,12,44,256,16,"");
        control(&mut data,0x80,1,0x50010001,154,76,54,18,"OK");
        control(&mut data,0x80,2,0x50010000,214,76,54,18,"Cancel");
        while data.len()%4 != 0 { data.push(0); }
        let template: Vec<u32> = data.chunks_exact(4).map(|b| u32::from_le_bytes(b.try_into().unwrap())).collect();
        let mut state = State { config, text:None };
        unsafe { DialogBoxIndirectParamW(std::ptr::null_mut(),template.as_ptr(),GetActiveWindow(),procedure,&mut state as *mut _ as isize); }
        state.text
    }
}
#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn native_config_and_initial_utf16_are_bounded() {
        let mut arg=vec![0;0x3e0]; arg[0x3ac..0x3b0].copy_from_slice(&10u32.to_le_bytes());
        arg[0x3b0..0x3b4].copy_from_slice(&1u32.to_le_bytes());
        arg[0x3c0..0x3c4].copy_from_slice(&2u32.to_le_bytes()); arg[0x3c4..0x3c8].copy_from_slice(&3u32.to_le_bytes());
        let cfg=Config::read(&[vec![0;0x20],arg,vec![0,0,b'A',0,b'B',0,0,0]],1000);
        assert_eq!((cfg.min,cfg.max,cfg.initial.as_str()),(1,10,"AB"));
        assert!(!cfg.valid("")); assert!(!cfg.valid("12345678901")); assert!(cfg.valid("Red"));
        assert!(!cfg.valid("a\0b"));
    }
    #[test]
    fn utf16_reply_and_cancel_use_the_native_layout() {
        let out=encode(Some("A😀"),0x7d8); assert_eq!(&out[..4],&[0;4]);
        assert_eq!(string(&out[4..]),"A😀"); assert_eq!(&encode(None,0x7d8)[..4],&[1,0,0,0]);
    }
}
