"""Original, optional host frustum observation; native geometry RAM stays intact."""
from pathlib import Path
from .capture_patch import replace


def patch(root):
    root = Path(root)
    p = root/'runtime/include/dsr/gpu3d.h'
    text = replace(p.read_text(encoding='utf-8'), '    void set_host_geometry_expansion(bool enabled);', '''    void set_host_geometry_expansion(bool enabled);
    // Optional host observation before native clipping. Aspect 0 disables it;
    // [4:3,4:1] otherwise. Independent bounded buffers never consume geometry
    // RAM or change native overflow flags. Configuration survives reset.
    // Visibility expansion is a separate opt-in guest behavior change: BOX_TEST
    // uses the wider horizontal frustum for perspective projections only.
    void set_host_widescreen(float aspect, bool expand_visibility = false);
    float host_widescreen_aspect() const;
    Gpu3DGeometryView widescreen_geometry_view() const;''')
    p.write_text(text, encoding='utf-8')
    p = root/'runtime/gpu3d/src/gpu3d.cpp'
    text = p.read_text(encoding='utf-8')
    text = replace(text, '    std::uint64_t render_generation = 0;', '''    std::uint64_t render_generation = 0;
    float host_aspect = 0;
    bool host_visibility = false;
    std::vector<Vertex> host_vertices, host_render_vertices;
    std::vector<Polygon> host_polygons, host_render_polygons;
    bool host_overflow = false, host_render_overflow = false;''')
    text = replace(text, '        render_generation = 0;', '''        render_generation = 0;
        host_vertices.clear(); host_render_vertices.clear();
        host_polygons.clear(); host_render_polygons.clear();
        host_overflow = host_render_overflow = false;''')
    text = replace(text, '    void emit_polygon(const std::uint16_t* indices, std::uint8_t count) {', '''    void observe_host_polygon(Polygon polygon) {
        if (host_aspect == 0) return;
        auto expanded = assembly_vertices;
        if (polygon.perspective)
            for (auto& vertex : expanded) vertex.clip[0] *= (4.0F/3.0F)/host_aspect;
        std::array<ClipVertex,16> clipped{};
        PreparedPolygon prepared{};
        prepared.count = clip_polygon(polygon, clipped, expanded.data());
        if (prepared.count < 3 || !prepare_raster_polygon(polygon, clipped, prepared)) return;
        // Four indices are uint16_t. Explicit caps also bound malicious streams.
        if (host_vertices.size()+polygon.count > 65532 || host_polygons.size() >= 16383) {
            host_overflow = true; return;
        }
        for (unsigned i=0;i<polygon.count;++i) {
            const auto vertex = assembly_vertices[polygon.index[i]];
            polygon.index[i] = static_cast<std::uint16_t>(host_vertices.size());
            host_vertices.push_back(vertex);
        }
        host_polygons.push_back(polygon);
    }

    void emit_polygon(const std::uint16_t* indices, std::uint8_t count) {''')
    text = replace(text, '        polygon.projection_scale = {projection[0],projection[5]};', '''        polygon.projection_scale = {projection[0],projection[5]};
        observe_host_polygon(polygon);''')
    text = replace(text, '            corners[corner].clip = transform_test_vector(projection, view);', '''            corners[corner].clip = transform_test_vector(projection, view);
            if (host_visibility && host_aspect > 0 &&
                (projection[3] != 0 || projection[7] != 0 || projection[11] != 0))
                corners[corner].clip[0] *= (4.0F/3.0F)/host_aspect;''')
    text = replace(text, '            ++render_generation;', '''            ++render_generation;
            host_render_vertices.swap(host_vertices); host_vertices.clear();
            host_render_polygons.swap(host_polygons); host_polygons.clear();
            host_render_overflow = host_overflow; host_overflow = false;''')
    text = replace(text, 'Gpu3DGeometryView Gpu3D::geometry_view() const {', '''void Gpu3D::set_host_widescreen(float aspect, bool expand_visibility) {
    auto& s=*impl_;
    const float next=std::isfinite(aspect) && aspect > 0 ? std::clamp(aspect,4.0F/3.0F,4.0F) : 0;
    // Resizes retain the current completed scene; only subsequent submissions
    // use the new frustum. Enabling/disabling invalidates the optional view.
    if ((s.host_aspect == 0) != (next == 0)) {
        s.host_vertices.clear(); s.host_polygons.clear();
        s.host_render_vertices.clear(); s.host_render_polygons.clear();
        s.host_overflow = s.host_render_overflow = false;
    }
    s.host_aspect=next; s.host_visibility=expand_visibility && next>0;
}
float Gpu3D::host_widescreen_aspect() const { return impl_->host_aspect; }
Gpu3DGeometryView Gpu3D::widescreen_geometry_view() const {
    const auto& s=*impl_;
    return {s.host_render_vertices.data(),s.host_render_vertices.size(),
            s.host_render_polygons.data(),s.host_render_polygons.size(),
            s.render_generation,s.swap_mode,s.host_render_overflow,s.host_render_overflow};
}

Gpu3DGeometryView Gpu3D::geometry_view() const {''')
    p.write_text(text, encoding='utf-8')
