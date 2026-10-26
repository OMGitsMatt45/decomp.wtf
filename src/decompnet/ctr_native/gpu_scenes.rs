//! MIT. Original PICA command scenes, independent of all game/firmware data.
use zakuro_gpu::{Gpu, GpuMemory, SoftwareRenderer};
use zakuro_gpu::format::ColorFormat;
use zakuro_gpu::registers::*;

mod screens;
fn layouts()->Result<(),String> {
    use zakuro_gpu::ScreenLayout;
    use zakuro_gpu::backend::layout;
    for (w,h) in [(1920,1080),(3440,1440),(481,327),(320,1280),(1,1)] {
        let (top,bottom)=layout(w,h,ScreenLayout::Stacked,400.0,false);
        let top=top.ok_or("missing top picture")?;
        let bottom=bottom.ok_or("missing touch picture")?;
        for (v,aspect) in [(top,400.0/240.0),(bottom,320.0/240.0)] {
            if v.x<0.0 || v.y<0.0 || v.width<=0.0 || v.height<=0.0
                || v.x+v.width>w as f32+0.001 || v.y+v.height>h as f32+0.001
                || (v.width/v.height-aspect).abs()>0.001 {
                return Err("screen layout is outside the drawable or distorts an LCD".into());
            }
        }
        let mapped=screens::touch(Some(bottom),
            (bottom.x+bottom.width/2.0) as f64,(bottom.y+bottom.height/2.0) as f64);
        if mapped!=Some((160,120)) {return Err(format!("touch mapping differs: {mapped:?}"));}
        for (x,y) in [(-1.0,-1.0),((top.x+top.width/2.0) as f64,(top.y+top.height/2.0) as f64)] {
            if screens::touch(Some(bottom),x,y).is_some() {return Err("touch accepted outside the lower LCD".into());}
        }
    }
    if screens::touch(None,0.0,0.0).is_some() {return Err("missing lower LCD accepted touch".into());}
    Ok(())
}

struct Memory(Vec<u8>);
impl GpuMemory for Memory {
    fn read(&mut self, at:u32, output:&mut [u8]) {
        output.copy_from_slice(&self.0[at as usize..at as usize+output.len()]);
    }
    fn write(&mut self, at:u32, data:&[u8]) {
        self.0[at as usize..at as usize+data.len()].copy_from_slice(data);
    }
}
fn float24(x:f32)->u32 {
    if x==0.0 {return 0;}
    let bits=x.to_bits();
    ((bits>>31)<<23)|((((bits>>23)&255)+63-127)<<16)|((bits>>7)&65535)
}
fn packed(v:[f32;4])->[u32;3] {
    let [x,y,z,w]=v.map(float24);
    [(w<<8)|(z>>16),((z&65535)<<16)|(y>>8),((y&255)<<24)|x]
}
fn commands(gpu:&mut Gpu,memory:&mut Memory,renderer:&mut SoftwareRenderer,rows:&[(usize,u32)]) {
    let mut bytes=Vec::new();
    for &(register,value) in rows {
        bytes.extend_from_slice(&value.to_le_bytes());
        bytes.extend_from_slice(&(register as u32|0xf0000).to_le_bytes());
    }
    memory.0[0x3000..0x3000+bytes.len()].copy_from_slice(&bytes);
    gpu.process_command_list(memory,renderer,0x3000,bytes.len() as u32);
}
fn setup(memory:&mut Memory,renderer:&mut SoftwareRenderer)->Gpu {
    let mut gpu=Gpu::new();
    let mov=0x13<<26;
    gpu.vertex_shader.program[..3].copy_from_slice(&[mov,mov|(1<<21)|(1<<12),0x22<<26]);
    gpu.vertex_shader.descriptors[0]=0xf|(0b00_01_10_11<<5)|(0b00_01_10_11<<14);
    commands(&mut gpu,memory,renderer,&[
        (REG_SHADER_OUTPUT_TOTAL,2),(REG_SHADER_OUTPUT_MAP,0x03020100),
        (REG_SHADER_OUTPUT_MAP+1,0x0b0a0908),(REG_VS_INPUT_REGISTER_MAP_LOW,0x10),
        (REG_VS_ATTRIBUTE_COUNT,1),(REG_VIEWPORT_WIDTH,float24(4.0)),
        (REG_VIEWPORT_HEIGHT,float24(4.0)),(REG_COLOR_BUFFER_ADDRESS,0x1000>>3),
        (REG_FRAMEBUFFER_DIMENSIONS,8|(7<<12)),(REG_COLOR_BUFFER_WRITE,0xf),
        (REG_DEPTH_COLOR_MASK,0xf<<8),(REG_LOGIC_OP,3)]);
    gpu
}
fn draw(gpu:&mut Gpu,memory:&mut Memory,renderer:&mut SoftwareRenderer,color:[f32;4],half:bool) {
    let mut rows=vec![(REG_FIXED_ATTRIBUTE_INDEX,0xf)];
    let far=if half {1.0} else {3.0};
    for position in [[-1.0,-1.0,0.0,1.0],[far,-1.0,0.0,1.0],[-1.0,far,0.0,1.0]] {
        for value in [position,color] {
            for (i,word) in packed(value).into_iter().enumerate() {
                rows.push((REG_FIXED_ATTRIBUTE_DATA+i,word));
            }
        }
    }
    rows.push((0x245,1));
    commands(gpu,memory,renderer,&rows);
    gpu.display_transfer(memory,0x1000,0x2000,8|(8<<16),8|(8<<16),0);
}
fn run()->Result<(),String> {
    let mut memory=Memory(vec![0;0x4000]);
    let mut renderer=SoftwareRenderer::default();
    let mut gpu=setup(&mut memory,&mut renderer);
    let device_info=gpu.enable_hardware_renderer(1,None,None)?;
    let device=gpu.hardware_device_name().ok_or("Vulkan device identity is missing")?.to_owned();
    if !gpu.draws_on_gpu() {return Err("geometry renderer was not enabled".into());}
    let mut scenes=0;
    for (scale,color) in [(1,[1.0,0.0,0.0,1.0]),(2,[0.0,1.0,0.0,1.0]),(3,[0.0,0.0,1.0,1.0]),(1,[1.0,1.0,0.0,1.0])] {
        let previous=scenes>0;
        gpu.retarget_scale(&mut memory,scale,None,None)?;
        if previous && memory.0[0x1000..0x1100].iter().all(|b|*b==0) {
            return Err("resize discarded GPU-owned framebuffer memory".into());
        }
        draw(&mut gpu,&mut memory,&mut renderer,color,false);
        let screen=gpu.scaled_screen(0x2000,(8,8),8,ColorFormat::Rgba8,&memory.0[0x2000..0x2100])
            .ok_or("GPU transfer did not leave a screen image")?;
        let (pixels,actual)=gpu.scaled_picture(screen).ok_or("GPU readback failed")?;
        if actual!=scale || pixels.len()!=8*8*4*scale as usize*scale as usize {
            return Err("geometry surface did not follow its render resolution".into());
        }
        let expected=color.map(|v|(v*255.0) as u8);
        if !pixels.chunks_exact(4).all(|p|p==expected) {return Err("GPU scene pixels differ".into());}
        let mut reference=Memory(vec![0;0x4000]);
        let mut cpu_renderer=SoftwareRenderer::default();
        let mut cpu=setup(&mut reference,&mut cpu_renderer);
        draw(&mut cpu,&mut reference,&mut cpu_renderer,color,false);
        if !reference.0[0x2000..0x2100].chunks_exact(4).all(|p|ColorFormat::Rgba8.decode(p)==expected) {
            return Err("independent software PICA scene differs".into());
        }
        scenes+=1;
    }
    println!("{}",serde_json::json!({"schema":"decomp.wtf.3ds-gpu-scenes/v1","scenes":scenes,
        "passed":true,"renderer":"vulkan","device":device,"device_info":device_info,"resized_scales":[1,2,3,1],
        "framebuffer_preserved":true,"retail_qualified":false,"physical_device_qualified":false}));
    Ok(())
}
fn main() {
    if let Err(error)=layouts() {eprintln!("3DS layout: {error}");std::process::exit(1);}
    if std::env::args().skip(1).any(|arg|arg=="--layout-only") {
        println!("{{\"schema\":\"decomp.wtf.3ds-layout-scenes/v1\",\"passed\":true,\"drawables\":5,\"touch\":true}}");
        return;
    }
    if let Err(error)=run() {eprintln!("3DS GPU scenes: {error}");std::process::exit(1);}
}
