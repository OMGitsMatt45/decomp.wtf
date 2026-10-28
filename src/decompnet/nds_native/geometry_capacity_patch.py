"""Opt-in geometry storage for customized, expanded host presentations."""
from pathlib import Path
from .capture_patch import replace


def patch(root):
    root=Path(root)
    p=root/'runtime/include/dsr/gpu3d.h'
    s=replace(p.read_text(), '    void reset();', '''    void reset();
    // Host customization only: larger view frusta can submit more geometry
    // than one DS LCD. Native 6144/2048 limits remain the default. Configure
    // on the owner thread before command submission or immediately after reset;
    // this invalidates borrowed geometry pointers. Capacity survives reset.
    void set_host_geometry_expansion(bool enabled);''')
    p.write_text(s)
    p=root/'runtime/gpu3d/src/gpu3d.cpp'
    s=p.read_text()
    s=replace(s,'#include <memory>','#include <memory>\n#include <stdexcept>')
    s=replace(s,'constexpr std::size_t kPolygonLimit = 2048;', '''constexpr std::size_t kPolygonLimit = 2048;
constexpr std::size_t kHostVertexLimit = 32768;
constexpr std::size_t kHostPolygonLimit = 8192;''')
    for typ,name,count in [('Vertex','vertices','kVertexLimit'),('Polygon','polygons','kPolygonLimit'),('Vertex','render_vertices','kVertexLimit'),('Polygon','render_polygons','kPolygonLimit'),('std::uint16_t','render_opaque_order','kPolygonLimit'),('std::uint16_t','render_translucent_order','kPolygonLimit')]:
        s=replace(s,f'    std::array<{typ}, {count}> {name}{{}};',f'    std::vector<{typ}> {name} = std::vector<{typ}>({count});')
    s=replace(s,'        vertices.fill({});','        std::fill(vertices.begin(), vertices.end(), Vertex{});')
    s=replace(s,'        polygons.fill({});','        std::fill(polygons.begin(), polygons.end(), Polygon{});')
    s=replace(s,'if (polygon_count >= kPolygonLimit)','if (polygon_count >= polygons.size())')
    s=replace(s,'if (vertex_count + needed > kVertexLimit)','if (vertex_count + needed > vertices.size())')
    s=replace(s,'std::unique_ptr<std::array<PreparedPolygon, kPolygonLimit>> band_polygons;', 'std::unique_ptr<std::vector<PreparedPolygon>> band_polygons;')
    s=replace(s,'std::make_unique<std::array<PreparedPolygon, kPolygonLimit>>()','std::make_unique<std::vector<PreparedPolygon>>(render_polygons.size())')
    s=replace(s,'std::array<std::array<std::uint32_t, kPolygonLimit>, kRenderBands> polygon_touches{};', 'std::array<std::array<std::uint32_t, kHostPolygonLimit>, kRenderBands> polygon_touches{};')
    s=replace(s,'std::array<std::uint32_t, kPolygonLimit> polygon_totals{};', 'std::array<std::uint32_t, kHostPolygonLimit> polygon_totals{};')
    s=replace(s,'std::array<std::array<float, 2>, kPolygonLimit> y_range{};', 'std::vector<std::array<float, 2>> y_range(render_polygon_count);')
    s=replace(s,'void Gpu3D::reset() { impl_->reset(); }', '''void Gpu3D::reset() { impl_->reset(); }
void Gpu3D::set_host_geometry_expansion(bool enabled) {
    auto& s=*impl_;
    const auto vertices=enabled?kHostVertexLimit:kVertexLimit;
    const auto polygons=enabled?kHostPolygonLimit:kPolygonLimit;
    if(s.vertices.size()==vertices)return;
    if(s.vertex_count||s.polygon_count||s.render_vertex_count||s.render_polygon_count||s.fifo_size||s.pipe_size)
        throw std::logic_error("Configure host geometry capacity before submission or after reset");
    s.vertices.resize(vertices);s.render_vertices.resize(vertices);
    s.polygons.resize(polygons);s.render_polygons.resize(polygons);
    s.render_opaque_order.resize(polygons);s.render_translucent_order.resize(polygons);
    s.band_polygons.reset();
}''')
    p.write_text(s)
