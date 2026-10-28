// Original geometry-RAM regressions. No game data or code.
#include <dsr/gpu3d.h>
#include <array>
#include <cstdint>
#include <iostream>
#include <memory>

using dsr::Gpu3D;
bool require(bool value, const char* message) {
    if (!value) std::cerr << message << '\n';
    return value;
}
void send(Gpu3D& gpu, unsigned code, std::uint32_t value) {
    gpu.io_write(0x04000400u + code * 4, value, 32);
    gpu.run(10000);
}
void vertex(Gpu3D& gpu, int x, int y) {
    send(gpu, 0x23, std::uint16_t(x) | (std::uint32_t(std::uint16_t(y)) << 16));
    send(gpu, 0x23, 0);
}
void begin(Gpu3D& gpu, unsigned mode=0, unsigned faces=0xc0) {
    send(gpu, 0x20, 0x1f);
    send(gpu, 0x29, (31u << 16) | faces);
    send(gpu, 0x40, mode);
}
void triangle(Gpu3D& gpu, int offset=0) {
    vertex(gpu, offset-1024, -1024);
    vertex(gpu, offset+1024, -1024);
    vertex(gpu, offset, 1024);
}
void frame(Gpu3D& gpu) {
    send(gpu, 0x50, 0);
    gpu.vblank_start();
    gpu.render_start();
}
bool visible(Gpu3D& gpu) {
    const auto pixel=gpu.line(96)[128];
    return require((pixel & 63u)==63u && (pixel >> 24)==31u,
                   "visible triangle survives rejected geometry");
}
int main() {
    auto storage=std::make_unique<Gpu3D>();
    auto& gpu=*storage;
    begin(gpu);
    // More than both hardware RAM capacities, entirely outside the right plane.
    for (int i=0;i<10000;++i) triangle(gpu, 16384);
    triangle(gpu);
    frame(gpu);
    auto geometry=gpu.geometry_view();
    if (!require(geometry.polygon_count==1 && geometry.vertex_count==3 &&
                 !geometry.vertex_overflow && !geometry.polygon_overflow,
                 "clipped-away primitives consume no geometry RAM") || !visible(gpu)) return 1;

    gpu.reset();
    // Determine which face is culled, then fill that face repeatedly.
    begin(gpu,0,0x40);triangle(gpu);
    const auto back_rejected=(gpu.io_read(0x04000604,32)&0xfff)==0;
    gpu.reset();begin(gpu,0,back_rejected ? 0x40 : 0x80);
    for(int i=0;i<2500;++i)triangle(gpu);
    begin(gpu);triangle(gpu);frame(gpu);geometry=gpu.geometry_view();
    if(!require(geometry.polygon_count==1 && geometry.vertex_count==3 &&
                !geometry.vertex_overflow && !geometry.polygon_overflow,
                "culled faces consume no geometry RAM") || !visible(gpu))return 2;

    gpu.reset();begin(gpu);
    vertex(gpu,-8192,-1024);vertex(gpu,1024,-1024);vertex(gpu,0,1024);
    frame(gpu);geometry=gpu.geometry_view();
    if(!require(geometry.polygon_count==1,"partially clipped primitive remains") || !visible(gpu))return 3;

    for(unsigned mode : {2u,3u}) {
        gpu.reset();begin(gpu,mode);
        for(int x : {-3000,-1000,1000,3000}) {
            vertex(gpu,x,-1000);vertex(gpu,x,1000);
        }
        frame(gpu);geometry=gpu.geometry_view();
        if(!require(geometry.vertex_count==8 && geometry.polygon_count==(mode==2 ? 6u : 3u),
                    "rolling input slots preserve shared strip vertices"))return 4;
        for(std::size_t i=0;i<geometry.polygon_count;++i) {
            const auto& polygon=geometry.polygons[i];
            for(unsigned j=0;j<polygon.count;++j)
                if(!require(polygon.index[j]<geometry.vertex_count,"valid retained strip index"))return 5;
        }
    }

    gpu.reset();begin(gpu,3);
    // Rejected strip vertices must still feed the first visible clipped quad.
    for(int x : {-16000,-12000,-8000,-3000,1000,3000}) {
        vertex(gpu,x,-1000);vertex(gpu,x,1000);
    }
    frame(gpu);geometry=gpu.geometry_view();
    if(!require(geometry.polygon_count==3 && geometry.vertex_count==8,
                "strip recovers retained endpoints after rejected quads"))return 6;

    gpu.reset();begin(gpu,1);
    for(int i=0;i<1537;++i) {
        vertex(gpu,-1024,-1024);vertex(gpu,1024,-1024);
        vertex(gpu,1024,1024);vertex(gpu,-1024,1024);
    }
    frame(gpu);geometry=gpu.geometry_view();
    if(!require(geometry.vertex_count==6144 && geometry.polygon_count==1536 &&
                geometry.vertex_overflow,"visible vertex RAM remains bounded"))return 7;
    gpu.reset();begin(gpu,2);
    for(int i=0;i<2052;++i) {
        switch(i%3) {
        case 0:vertex(gpu,-1024,-1024);break;
        case 1:vertex(gpu,1024,-1024);break;
        case 2:vertex(gpu,0,1024);break;
        }
    }
    frame(gpu);geometry=gpu.geometry_view();
    if(!require(geometry.polygon_count==2048 && geometry.polygon_overflow &&
                geometry.vertex_count<=6144,"visible polygon RAM remains bounded"))return 8;
    // Projection metadata is captured at geometry submission, not inferred
    // from W variation or sampled later from the current matrix registers.
    gpu.reset();begin(gpu);triangle(gpu);frame(gpu);geometry=gpu.geometry_view();
    if(!require(geometry.polygon_count==1&&!geometry.polygons[0].perspective,
                "identity projection is orthographic"))return 9;
    gpu.reset();send(gpu,0x10,0);
    std::array<std::int32_t,16> projection{};
    projection[0]=projection[5]=projection[10]=projection[15]=4096;projection[11]=4096;
    for(auto value:projection)send(gpu,0x16,std::uint32_t(value));
    begin(gpu);triangle(gpu);frame(gpu);geometry=gpu.geometry_view();
    if(!require(geometry.polygon_count==1&&geometry.polygons[0].perspective,
                "perspective classification survives a constant-depth planar mesh"))return 10;
    for(std::size_t i=0;i<geometry.vertex_count;++i)
        if(!require(geometry.vertices[i].clip[3]==1.f,"classification is independent of identical vertex W"))return 11;
    if(!visible(gpu))return 12;
    send(gpu,0x10,0);send(gpu,0x15,0);
    if(!require(gpu.geometry_view().polygons[0].perspective,"later matrix changes do not rewrite rendered projection metadata"))return 13;
    begin(gpu);triangle(gpu);frame(gpu);
    if(!require(!gpu.geometry_view().polygons[0].perspective,"next geometry records its own projection type"))return 14;
    gpu.reset();send(gpu,0x10,0);
    projection.fill(0);projection[0]=12;projection[5]=-21;projection[10]=4096;projection[15]=4096;
    for(auto value:projection)send(gpu,0x16,std::uint32_t(value));
    begin(gpu);triangle(gpu);frame(gpu);
    if(!require(gpu.geometry_view().polygon_count==1 &&
                gpu.geometry_view().polygons[0].projection_scale==std::array<std::int32_t,2>{12,-21},
                "orthographic scale records the submitted view"))return 16;
    send(gpu,0x10,0);send(gpu,0x15,0);
    if(!require(gpu.geometry_view().polygons[0].projection_scale==std::array<std::int32_t,2>{12,-21},
                "later projection writes do not change latched scale"))return 17;
    // The native raster confirms the depth contract used by host GPU replay.
    gpu.reset();begin(gpu);
    for(const auto point:std::array<std::array<int,2>,3>{{{-1024,-1024},{1024,-1024},{0,1024}}}) {
        send(gpu,0x23,std::uint16_t(point[0])|(std::uint32_t(std::uint16_t(point[1]))<<16));
        send(gpu,0x23,4096);
    }
    frame(gpu);
    if(!require(gpu.geometry_view().polygon_count==1,"native far-plane triangle remains visible")||!visible(gpu))return 15;
    std::cout << "Geometry rejection, clipping, strips and finite RAM passed\n";
}
