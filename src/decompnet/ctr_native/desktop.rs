//! Independent Vulkan window. No library browser or runtime code compilation.
use std::time::{Duration, Instant};
use winit::{application::ApplicationHandler, dpi::PhysicalSize,
    event::{ElementState, MouseButton, WindowEvent}, event_loop::{ActiveEventLoop, EventLoop, ControlFlow},
    keyboard::{KeyCode, PhysicalKey}, window::{Fullscreen, Window, WindowId}};
use zakuro_common::Screen;
use zakuro_core::{System, services::hid::{InputState, PadState}};
use zakuro_gpu::{backend::{vulkan::VulkanPresenter, layout, unified}, Overlay, PresentError, Presenter,
    ScreenImage, ScreenLayout};

pub fn arrangement(unified:bool,bottom:bool)->ScreenLayout {
    if !unified {ScreenLayout::Stacked} else if bottom {ScreenLayout::UnifiedBottom} else {ScreenLayout::Unified}
}

pub struct Outcome {
    pub stop: &'static str,
    pub presented: u64,
    pub drawable: [u32;2],
    pub unified: bool,
    pub bottom_primary: bool,
    pub audio_open: bool,
    pub audio_frames: u64,
    pub audio_error: Option<String>,
    pub controllers: usize,
    pub controller_error: Option<String>,
}

struct Host<'a> {
    system: &'a mut System,
    // Drop the swapchain before its window.
    presenter: Option<VulkanPresenter>,
    window: Option<Window>,
    input: InputState,
    pointer: Option<(f64,f64)>,
    pressed: bool,
    circle: [bool;4],
    focused: bool,
    audio: Option<super::audio::Audio>,
    gamepads: super::gamepad::Gamepads,
    limit: Option<u64>,
    frame_limit: Option<u64>,
    next_frame: Instant,
    result: Outcome,
    error: Option<String>,
}

impl Host<'_> {
    fn resize(&mut self) -> Result<(),String> {
        let size=self.window.as_ref().unwrap().inner_size();
        self.result.drawable=[size.width,size.height];
        let mode=arrangement(self.result.unified,self.result.bottom_primary);
        let presenter=self.presenter.as_mut().unwrap();
        presenter.set_layout(mode);
        if size.width>0 && size.height>0 {presenter.resize(size.width,size.height);}
        self.system.resize_drawable(size.width,size.height,mode)?;
        self.touch();
        Ok(())
    }

    fn touch(&mut self) {
        self.input.touch=None;
        if !self.pressed {return;}
        if let Some((x,y))=self.pointer {
            let [w,h]=self.result.drawable;
            let mode=arrangement(self.result.unified,self.result.bottom_primary);
            let (top,bottom)=layout(w,h,mode,400.0,false);
            self.input.touch=unified::touch(top,bottom,
                self.result.unified && self.result.bottom_primary,x,y);
        }
    }

    fn redraw(&mut self)->Result<Option<&'static str>,String> {
        let [w,h]=self.result.drawable;
        if w==0 || h==0 {return Ok(None);}
        let input=self.gamepads.apply(self.input);
        self.result.controllers=self.gamepads.count();
        self.system.set_input(if self.focused {input} else {InputState::default()});
        let deadline=self.system.cpu.cycles.saturating_add(zakuro_core::CYCLES_PER_FRAME)
            .min(self.limit.unwrap_or(u64::MAX));
        while self.system.cpu.cycles<deadline {
            if let Some(stop)=super::advance(self.system,deadline) {return Ok(Some(stop));}
        }
        let top_gpu=self.system.gpu_screen(Screen::Top);
        let bottom_gpu=self.system.gpu_screen(Screen::Bottom);
        let top=if top_gpu.is_none() {self.system.read_screen_scaled(Screen::Top)}
            else {(std::sync::Arc::new(Vec::new()),400,240)};
        let bottom=if bottom_gpu.is_none() {self.system.read_screen_scaled(Screen::Bottom)}
            else {(std::sync::Arc::new(Vec::new()),320,240)};
        let presented=self.presenter.as_mut().unwrap().present(
            ScreenImage {width:top.1,height:top.2,pixels:top.0.as_slice(),gpu:top_gpu},
            ScreenImage {width:bottom.1,height:bottom.2,pixels:bottom.0.as_slice(),gpu:bottom_gpu},
            ScreenImage {width:0,height:0,pixels:&[],gpu:None},&Overlay::default());
        match presented {
            Ok(())=>self.result.presented+=1,
            // The presenter already recreated its swapchain. Calling resize
            // here would mark it stale again and prevent every future frame.
            Err(PresentError::OutOfDate)=>{},
            Err(error)=>return Err(error.to_string()),
        }
        let samples=self.system.take_audio();
        if let Some(audio)=&self.audio {
            audio.push(&samples);
            self.result.audio_frames+=samples.len() as u64;
        }
        if self.limit.is_some_and(|n|self.system.cpu.cycles>=n) {return Ok(Some("budget"));}
        if self.frame_limit.is_some_and(|n|self.result.presented>=n) {return Ok(Some("window-frame-limit"));}
        let period=Duration::from_secs_f64(1.0/60.0);
        self.next_frame+=period;
        // Rendering and swapchain waits count toward the frame interval.
        // After a long stall, resume rather than running a burst of old frames.
        if Instant::now().saturating_duration_since(self.next_frame)>period*2 {
            self.next_frame=Instant::now();
        }
        Ok(None)
    }

    fn key(&mut self,key:KeyCode,down:bool) {
        let button=match key {
            KeyCode::KeyJ=>PadState::A,KeyCode::KeyK=>PadState::B,
            KeyCode::KeyU=>PadState::X,KeyCode::KeyI=>PadState::Y,
            KeyCode::KeyQ=>PadState::L,KeyCode::KeyE=>PadState::R,
            KeyCode::Enter=>PadState::START,KeyCode::Backspace=>PadState::SELECT,
            KeyCode::ArrowUp=>PadState::UP,KeyCode::ArrowDown=>PadState::DOWN,
            KeyCode::ArrowLeft=>PadState::LEFT,KeyCode::ArrowRight=>PadState::RIGHT,
            _=>PadState::empty(),
        };
        self.input.buttons.set(button,down);
        let axis=match key {KeyCode::KeyA=>Some(0),KeyCode::KeyD=>Some(1),KeyCode::KeyS=>Some(2),KeyCode::KeyW=>Some(3),_=>None};
        if let Some(i)=axis {self.circle[i]=down;}
        self.input.circle_x=self.circle[1] as u8 as f32-self.circle[0] as u8 as f32;
        self.input.circle_y=self.circle[3] as u8 as f32-self.circle[2] as u8 as f32;
    }
}

impl ApplicationHandler for Host<'_> {
    fn resumed(&mut self,events:&ActiveEventLoop) {
        if self.window.is_some() {return;}
        let initialize=||->Result<(Window,VulkanPresenter),String> {
            let window=events.create_window(Window::default_attributes()
                .with_title("3DS native project — F6 layout · F7 primary screen · F11 fullscreen")
                .with_inner_size(PhysicalSize::new(1280,720))).map_err(|e|e.to_string())?;
            let size=window.inner_size();
            let presenter=VulkanPresenter::new(&window,(size.width.max(1),size.height.max(1)))
                .map_err(|e|e.to_string())?;
            Ok((window,presenter))
        };
        match initialize() {
            Ok((window,presenter))=>{
                let device=presenter.shared_device();
                let title=self.system.title.as_ref().map(|title|title.program_id());
                if let Err(error)=self.system.gpu.enable_hardware_renderer(1,device.clone(),title) {
                    self.error=Some(error);events.exit();return;
                }
                self.system.config.device=device;
                self.system.config.hardware_renderer=true;
                self.presenter=Some(presenter);self.window=Some(window);
                if let Err(error)=self.resize() {self.error=Some(error);events.exit();}
            }
            Err(error)=>{self.error=Some(error);events.exit();}
        }
    }

    fn window_event(&mut self,events:&ActiveEventLoop,_id:WindowId,event:WindowEvent) {
        match event {
            WindowEvent::CloseRequested=>{self.result.stop="window-closed";events.exit();}
            WindowEvent::Resized(_)=>if let Err(error)=self.resize() {self.error=Some(error);events.exit();},
            WindowEvent::ScaleFactorChanged {..}=>if let Err(error)=self.resize() {self.error=Some(error);events.exit();},
            WindowEvent::Focused(on)=>{
                self.focused=on;
                if !on {self.input=InputState::default();self.circle=[false;4];self.pressed=false;}
            }
            WindowEvent::CursorMoved {position,..}=>{self.pointer=Some((position.x,position.y));self.touch();}
            WindowEvent::CursorLeft {..}=>{self.pointer=None;self.input.touch=None;}
            WindowEvent::MouseInput {button:MouseButton::Left,state,..}=>{self.pressed=state.is_pressed();self.touch();}
            WindowEvent::KeyboardInput {event,..}=>if let PhysicalKey::Code(code)=event.physical_key {
                let down=event.state==ElementState::Pressed;
                if down && !event.repeat {
                    match code {
                        KeyCode::Escape=>{self.result.stop="window-closed";events.exit();}
                        KeyCode::F6=>self.result.unified=!self.result.unified,
                        KeyCode::F7=>self.result.bottom_primary=!self.result.bottom_primary,
                        KeyCode::F11=>{
                            let window=self.window.as_ref().unwrap();
                            window.set_fullscreen(if window.fullscreen().is_some() {None} else {Some(Fullscreen::Borderless(None))});
                        }
                        _=>{}
                    }
                    if matches!(code,KeyCode::F6|KeyCode::F7) {
                        if let Err(error)=self.resize() {self.error=Some(error);events.exit();}
                    }
                }
                self.key(code,down);
            },
            WindowEvent::RedrawRequested=>match self.redraw() {
                Ok(Some(stop))=>{self.result.stop=stop;events.exit();}
                Ok(None)=>{}
                Err(error)=>{self.error=Some(error);events.exit();}
            },
            _=>{}
        }
    }

    fn about_to_wait(&mut self,events:&ActiveEventLoop) {
        if Instant::now()>=self.next_frame {
            if let Some(window)=&self.window {window.request_redraw();}
        }
        events.set_control_flow(ControlFlow::WaitUntil(self.next_frame.max(Instant::now()+Duration::from_millis(1))));
    }
}

pub fn run(system:&mut System,limit:Option<u64>,frame_limit:Option<u64>,unified:bool,bottom_primary:bool,mute:bool)->Result<Outcome,String> {
    let events=EventLoop::new().map_err(|e|e.to_string())?;
    let (audio,audio_error)=if mute {(None,None)} else {
        match super::audio::Audio::open(zakuro_core::AUDIO_SAMPLE_RATE) {
            Ok(audio)=>(Some(audio),None),Err(error)=>{
                eprintln!("3DS sound output unavailable: {error}");(None,Some(error))
            }
        }
    };
    let gamepads=super::gamepad::Gamepads::new();
    let controller_error=gamepads.error.clone();
    if let Some(error)=&controller_error {eprintln!("3DS controllers unavailable: {error}");}
    let mut host=Host {system,presenter:None,window:None,input:InputState::default(),pointer:None,
        pressed:false,circle:[false;4],focused:true,limit,frame_limit,next_frame:Instant::now(),error:None,
        result:Outcome {stop:"window-closed",presented:0,drawable:[0,0],unified,bottom_primary,
            audio_open:audio.is_some(),audio_frames:0,audio_error,controllers:gamepads.count(),controller_error},
        audio,gamepads};
    events.run_app(&mut host).map_err(|e|e.to_string())?;
    if let Some(error)=host.error.take() {return Err(error);}
    Ok(host.result)
}
