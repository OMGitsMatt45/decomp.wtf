use ash::vk;

use super::images::ImageKey;
use super::present_filter_shader::{FRAGMENT, VERTEX};

pub(super) struct PresentFilter {
    device: ash::Device,
    set_layout: vk::DescriptorSetLayout,
    layout: vk::PipelineLayout,
    pipeline: vk::Pipeline,
    views: Vec<vk::ImageView>,
    logged: bool,
}

pub(super) fn rgba8(format: vk::Format) -> bool {
    matches!(
        format,
        vk::Format::R8G8B8A8_UNORM | vk::Format::B8G8R8A8_UNORM
            | vk::Format::R8G8B8A8_SRGB | vk::Format::B8G8R8A8_SRGB
    )
}

pub(super) fn color_view(device: &ash::Device, image: vk::Image, format: vk::Format) -> Result<vk::ImageView, vk::Result> {
    let range = vk::ImageSubresourceRange::default()
        .aspect_mask(vk::ImageAspectFlags::COLOR)
        .level_count(1)
        .layer_count(1);
    let info = vk::ImageViewCreateInfo::default().image(image).view_type(vk::ImageViewType::TYPE_2D).format(format).subresource_range(range);
    unsafe { device.create_image_view(&info, None) }
}

pub(super) fn transform(source: ImageKey, visible: [u32; 2], output: vk::Extent2D, flip: [bool; 2]) -> Option<[f32; 4]> {
    let [w, h] = visible;
    if !rgba8(source.format) || visible != [source.width, source.height] || w == 0 || h == 0
        || output.width < w || output.height < h || (output.width, output.height) == (w, h)
    {
        return None;
    }
    let (sx, sy) = (w as f32 / output.width as f32, h as f32 / output.height as f32);
    let (sx, ox) = if flip[0] { (-sx, w as f32) } else { (sx, 0.0) };
    let (sy, oy) = if flip[1] { (-sy, h as f32) } else { (sy, 0.0) };
    Some([sx, sy, ox, oy])
}

impl PresentFilter {
    pub(super) fn new(device: &ash::Device, format: vk::Format, images: &[vk::Image]) -> Result<Self, vk::Result> {
        let mut filter = Self {
            device: device.clone(),
            set_layout: vk::DescriptorSetLayout::null(),
            layout: vk::PipelineLayout::null(),
            pipeline: vk::Pipeline::null(),
            views: Vec::with_capacity(images.len()),
            logged: false,
        };
        let bindings = [vk::DescriptorSetLayoutBinding::default()
            .binding(0)
            .descriptor_type(vk::DescriptorType::SAMPLED_IMAGE)
            .descriptor_count(1)
            .stage_flags(vk::ShaderStageFlags::FRAGMENT)];
        let set = vk::DescriptorSetLayoutCreateInfo::default()
            .flags(vk::DescriptorSetLayoutCreateFlags::PUSH_DESCRIPTOR_KHR)
            .bindings(&bindings);
        filter.set_layout = unsafe { device.create_descriptor_set_layout(&set, None)? };
        let layouts = [filter.set_layout];
        let constants = [vk::PushConstantRange::default().stage_flags(vk::ShaderStageFlags::FRAGMENT).size(16)];
        let layout = vk::PipelineLayoutCreateInfo::default().set_layouts(&layouts).push_constant_ranges(&constants);
        filter.layout = unsafe { device.create_pipeline_layout(&layout, None)? };
        filter.pipeline = create_pipeline(device, filter.layout, format)?;
        for &image in images {
            filter.views.push(color_view(device, image, format)?);
        }
        Ok(filter)
    }

    pub(super) fn record(
        &mut self,
        push: &ash::khr::push_descriptor::Device,
        cmd: vk::CommandBuffer,
        index: usize,
        extent: vk::Extent2D,
        source: vk::ImageView,
        source_size: [u32; 2],
        transform: [f32; 4],
    ) {
        let rect = vk::Rect2D::default().extent(extent);
        let attachments = [vk::RenderingAttachmentInfo::default()
            .image_view(self.views[index])
            .image_layout(vk::ImageLayout::COLOR_ATTACHMENT_OPTIMAL)
            .load_op(vk::AttachmentLoadOp::DONT_CARE)
            .store_op(vk::AttachmentStoreOp::STORE)];
        let rendering = vk::RenderingInfo::default().render_area(rect).layer_count(1).color_attachments(&attachments);
        let view = [vk::Viewport::default().width(extent.width as f32).height(extent.height as f32).max_depth(1.0)];
        let source_info = [vk::DescriptorImageInfo::default().image_view(source).image_layout(vk::ImageLayout::GENERAL)];
        let writes = [vk::WriteDescriptorSet::default()
            .dst_binding(0)
            .descriptor_type(vk::DescriptorType::SAMPLED_IMAGE)
            .image_info(&source_info)];
        let constants = transform.map(f32::to_ne_bytes);
        let device = &self.device;
        unsafe {
            device.cmd_begin_rendering(cmd, &rendering);
            device.cmd_bind_pipeline(cmd, vk::PipelineBindPoint::GRAPHICS, self.pipeline);
            device.cmd_set_viewport(cmd, 0, &view);
            device.cmd_set_scissor(cmd, 0, &[rect]);
            push.cmd_push_descriptor_set(cmd, vk::PipelineBindPoint::GRAPHICS, self.layout, 0, &writes);
            device.cmd_push_constants(cmd, self.layout, vk::ShaderStageFlags::FRAGMENT, 0, constants.as_flattened());
            device.cmd_draw(cmd, 3, 1, 0, 0);
            device.cmd_end_rendering(cmd);
        }
        if !self.logged {
            self.logged = true;
            eprintln!("kirikae: cubic presentation filter ({}x{} -> {}x{})", source_size[0], source_size[1], extent.width, extent.height);
        }
    }
}

impl Drop for PresentFilter {
    fn drop(&mut self) {
        unsafe {
            for &view in &self.views {
                self.device.destroy_image_view(view, None);
            }
            self.device.destroy_pipeline(self.pipeline, None);
            self.device.destroy_pipeline_layout(self.layout, None);
            self.device.destroy_descriptor_set_layout(self.set_layout, None);
        }
    }
}

fn create_pipeline(device: &ash::Device, layout: vk::PipelineLayout, format: vk::Format) -> Result<vk::Pipeline, vk::Result> {
    let shader = |code| unsafe { device.create_shader_module(&vk::ShaderModuleCreateInfo::default().code(code), None) };
    let vertex = shader(VERTEX)?;
    let fragment = match shader(FRAGMENT) {
        Ok(module) => module,
        Err(error) => {
            unsafe { device.destroy_shader_module(vertex, None) };
            return Err(error);
        }
    };
    let stages = [
        vk::PipelineShaderStageCreateInfo::default().stage(vk::ShaderStageFlags::VERTEX).module(vertex).name(c"main"),
        vk::PipelineShaderStageCreateInfo::default().stage(vk::ShaderStageFlags::FRAGMENT).module(fragment).name(c"main"),
    ];
    let vertex_input = vk::PipelineVertexInputStateCreateInfo::default();
    let assembly = vk::PipelineInputAssemblyStateCreateInfo::default().topology(vk::PrimitiveTopology::TRIANGLE_LIST);
    let viewport = vk::PipelineViewportStateCreateInfo::default().viewport_count(1).scissor_count(1);
    let raster = vk::PipelineRasterizationStateCreateInfo::default().polygon_mode(vk::PolygonMode::FILL).line_width(1.0);
    let samples = vk::PipelineMultisampleStateCreateInfo::default().rasterization_samples(vk::SampleCountFlags::TYPE_1);
    let mask = vk::ColorComponentFlags::R | vk::ColorComponentFlags::G | vk::ColorComponentFlags::B | vk::ColorComponentFlags::A;
    let attachments = [vk::PipelineColorBlendAttachmentState::default().color_write_mask(mask)];
    let blend = vk::PipelineColorBlendStateCreateInfo::default().attachments(&attachments);
    let states = [vk::DynamicState::VIEWPORT, vk::DynamicState::SCISSOR];
    let dynamic = vk::PipelineDynamicStateCreateInfo::default().dynamic_states(&states);
    let formats = [format];
    let mut rendering = vk::PipelineRenderingCreateInfo::default().color_attachment_formats(&formats);
    let info = vk::GraphicsPipelineCreateInfo::default()
        .stages(&stages)
        .vertex_input_state(&vertex_input)
        .input_assembly_state(&assembly)
        .viewport_state(&viewport)
        .rasterization_state(&raster)
        .multisample_state(&samples)
        .color_blend_state(&blend)
        .dynamic_state(&dynamic)
        .layout(layout)
        .push_next(&mut rendering);
    let result = unsafe { device.create_graphics_pipelines(vk::PipelineCache::null(), &[info], None) };
    unsafe {
        device.destroy_shader_module(fragment, None);
        device.destroy_shader_module(vertex, None);
    }
    result.map(|pipelines| pipelines[0]).map_err(|(pipelines, error)| {
        for pipeline in pipelines {
            unsafe { device.destroy_pipeline(pipeline, None) };
        }
        error
    })
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn presentation_filter_requires_a_complete_supported_source_and_upscale() {
        let source = ImageKey { cpu: 0, format: vk::Format::B8G8R8A8_UNORM, width: 1920, height: 1080 };
        let hd = vk::Extent2D { width: 1920, height: 1080 };
        let qhd = vk::Extent2D { width: 2560, height: 1440 };
        let smaller = vk::Extent2D { width: 2560, height: 900 };
        let visible = [1920, 1080];
        assert_eq!(transform(source, visible, hd, [false, false]), None);
        assert_eq!(transform(source, visible, smaller, [false, false]), None);
        assert_eq!(transform(source, [1920, 1040], qhd, [false, false]), None);
        let unsupported = ImageKey { format: vk::Format::R32_UINT, ..source };
        assert_eq!(transform(unsupported, visible, qhd, [false, false]), None);
        assert_eq!(transform(source, visible, qhd, [false, false]), Some([0.75, 0.75, 0.0, 0.0]));
    }

    #[test]
    fn presentation_transform_maps_centers_with_independent_flips() {
        let source = ImageKey { cpu: 0, format: vk::Format::R8G8B8A8_SRGB, width: 3, height: 2 };
        let output = vk::Extent2D { width: 6, height: 4 };
        for (flip, corner) in [
            ([false, false], [-0.25, -0.25]),
            ([true, false], [2.25, -0.25]),
            ([false, true], [-0.25, 1.25]),
            ([true, true], [2.25, 1.25]),
        ] {
            let [sx, sy, ox, oy] = transform(source, [3, 2], output, flip).unwrap();
            assert_eq!([0.5 * sx + ox - 0.5, 0.5 * sy + oy - 0.5], corner);
            assert_eq!([5.5 * sx + ox - 0.5, 3.5 * sy + oy - 0.5], [2.0 - corner[0], 1.0 - corner[1]]);
        }
    }
}
