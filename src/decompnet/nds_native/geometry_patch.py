"""Reject invisible primitives before consuming the pinned geometry RAM."""
from pathlib import Path


def patch(root):
    path=Path(root)/'runtime/gpu3d/src/gpu3d.cpp'
    text=path.read_text(encoding='utf-8')
    changes={
        '    std::array<std::uint16_t, 4> primitive_vertices{};':
        '''    // Assembly lives outside geometry RAM. Rejected primitives must not
    // exhaust the finite polygon/vertex buffers before later visible objects.
    // Four rolling input slots also retain triangle/quad strip endpoints.
    std::array<Vertex, 4> assembly_vertices{};
    std::array<int, 4> assembly_stored{{-1, -1, -1, -1}};
    std::uint32_t assembly_cursor = 0;
    std::array<std::uint16_t, 4> primitive_vertices{};''',
        '''        if (polygon_count >= kPolygonLimit) {
            polygon_overflow = true;
            disp3d |= 1U << 13;
            return;
        }
        Polygon polygon{};''':
        '''        Polygon polygon{};''',
        '''        polygon.viewport = get32(0x04000580U);
        polygons[polygon_count++] = polygon;''':
        '''        polygon.viewport = get32(0x04000580U);
        std::array<ClipVertex, 16> clipped{};
        const auto clipped_count = clip_polygon(polygon, clipped, assembly_vertices.data());
        if (clipped_count < 3U) return;
        PreparedPolygon prepared{};
        prepared.count = clipped_count;
        if (!prepare_raster_polygon(polygon, clipped, prepared)) return;
        if (polygon_count >= kPolygonLimit) {
            polygon_overflow = true;
            disp3d |= 1U << 13;
            return;
        }
        std::size_t needed = 0;
        for (std::size_t i = 0; i < count; ++i)
            if (assembly_stored[indices[i]] < 0) ++needed;
        if (vertex_count + needed > kVertexLimit) {
            vertex_overflow = true;
            disp3d |= 1U << 13;
            return;
        }
        for (std::size_t i = 0; i < count; ++i) {
            const auto slot = indices[i];
            if (assembly_stored[slot] < 0) {
                assembly_stored[slot] = static_cast<int>(vertex_count);
                vertices[vertex_count++] = assembly_vertices[slot];
            }
            polygon.index[i] = static_cast<std::uint16_t>(assembly_stored[slot]);
        }
        polygons[polygon_count++] = polygon;''',
        '''        if (vertex_count >= kVertexLimit) {
            vertex_overflow = true;
            disp3d |= 1U << 13;
            return;
        }
        const std::array<std::int32_t, 4> position_vector''':
        '''        const std::array<std::int32_t, 4> position_vector''',
        '''        vertices[vertex_count] = vertex;
        const auto index = static_cast<std::uint16_t>(vertex_count);
        ++vertex_count;
        assemble_vertex(index);''':
        '''        const auto slot = static_cast<std::uint16_t>(assembly_cursor++ % 4U);
        assembly_vertices[slot] = vertex;
        assembly_stored[slot] = -1;
        assemble_vertex(slot);''',
        '''            primitive_mode = static_cast<std::uint8_t>(value & 3U);
            primitive_vertex_count = 0;''':
        '''            primitive_mode = static_cast<std::uint8_t>(value & 3U);
            primitive_vertex_count = 0;
            assembly_cursor = 0;
            assembly_stored.fill(-1);''',
        '''    std::size_t clip_polygon(const Polygon& polygon, std::array<ClipVertex, 16>& output_vertices) const {''':
        '''    std::size_t clip_polygon(const Polygon& polygon, std::array<ClipVertex, 16>& output_vertices,
                             const Vertex* source_vertices = nullptr) const {
        if (source_vertices == nullptr) source_vertices = render_vertices.data();''',
        '''            const auto& source = render_vertices[polygon.index[i]];
            input[i] = {source.clip, source.u, source.v, source.color};''':
        '''            const auto& source = source_vertices[polygon.index[i]];
            input[i] = {source.clip, source.u, source.v, source.color};''',
    }
    for before,after in changes.items():
        if text.count(before)!=1:
            raise ValueError('pinned DS geometry integration site differs')
        text=text.replace(before,after)
    path.write_text(text,encoding='utf-8')
