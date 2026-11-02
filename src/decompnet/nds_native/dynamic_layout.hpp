// SPDX-License-Identifier: MIT. Original host window grouping and placement.
#pragma once
#include <algorithm>
#include <array>
#include <vector>
#include <cstdint>
#include <cstdlib>

namespace video::layout_detail {
// Analyze a complete known 2D composition before LCD master brightness. A
// fade changes its displayed colors, not its borders or screen arrangement.
// Never substitute a partial/unsupported foreground for the native picture.
inline const uint32_t* classification_pixels(const uint32_t* pixels,const uint64_t* foreground,
    const uint8_t* brightness,std::array<uint32_t,256*192>& storage) {
    if(!foreground||!brightness||std::none_of(brightness,brightness+192,[](uint8_t b){return b!=0;}))return pixels;
    for(size_t i=0;i<storage.size();++i) {
        if((foreground[i]&(3ull<<32))!=(1ull<<32)||uint8_t(foreground[i]>>24)!=255)return pixels;
        storage[i]=uint32_t(foreground[i]);
    }
    return storage.data();
}
inline bool blank_screen(const uint32_t* pixels) {
    const auto black=[](uint32_t p){return ((p>>16)&255)<=8&&((p>>8)&255)<=8&&(p&255)<=8;};
    const auto white=[](uint32_t p){return ((p>>16)&255)>=247&&((p>>8)&255)>=247&&(p&255)>=247;};
    return black(pixels[0])?std::all_of(pixels,pixels+256*192,black):
        white(pixels[0])&&std::all_of(pixels,pixels+256*192,white);
}
inline bool low_contrast_fade(const uint32_t* pixels) {
    unsigned low=255,high=0;
    for(unsigned i=0;i<256*192;++i)for(unsigned shift:{16u,8u,0u}) {
        const auto value=(pixels[i]>>shift)&255;low=std::min(low,value);high=std::max(high,value);
        if(high-low>16)return false;
    }
    return high<=24||low>=231;
}
struct Box {int x=0,y=0,w=0,h=0;}; // Native top-left coordinates.
inline Box unite(Box a,Box b) {
    const int x=std::min(a.x,b.x),y=std::min(a.y,b.y);
    return {x,y,std::max(a.x+a.w,b.x+b.w)-x,std::max(a.y+a.h,b.y+b.h)-y};
}
inline void group(std::vector<Box>& boxes,int gap=3) {
    for(size_t i=0;i<boxes.size();++i)for(size_t j=i+1;j<boxes.size();) {
        const auto a=boxes[i],b=boxes[j];
        if(a.x<=b.x+b.w+gap&&b.x<=a.x+a.w+gap&&a.y<=b.y+b.h+gap&&b.y<=a.y+a.h+gap) {
            boxes[i]=unite(a,b);boxes.erase(boxes.begin()+j);i=size_t(-1);break;
        } else ++j;
    }
}
inline std::vector<Box> foreground_boxes(const uint64_t* foreground) {
    std::vector<Box> result;
    if(!foreground)return result;
    std::array<uint8_t,256*192> mask{};
    for(size_t i=0;i<mask.size();++i)mask[i]=uint8_t(foreground[i]>>24)!=0;
    std::vector<int> queue;queue.reserve(mask.size());
    for(int pixel=0;pixel<int(mask.size());++pixel)if(mask[pixel]) {
        queue.clear();queue.push_back(pixel);mask[pixel]=0;
        int left=pixel%256,right=left,top=pixel/256,bottom=top;
        for(size_t n=0;n<queue.size();++n) {
            const int p=queue[n],x=p%256,y=p/256;
            left=std::min(left,x);right=std::max(right,x);top=std::min(top,y);bottom=std::max(bottom,y);
            for(int adjacent:{x>0?p-1:-1,x<255?p+1:-1,y>0?p-256:-1,y<191?p+256:-1})
                if(adjacent>=0&&mask[adjacent]){mask[adjacent]=0;queue.push_back(adjacent);}
        }
        result.push_back({left,top,right-left+1,bottom-top+1});
    }
    group(result);
    return result;
}
// Find native party frames from long neutral border lines in the left half.
// Glyphs and command-window borders in the right half cannot create a panel.
// Preserve the whole source band when commands bridge several party frames.
inline Box party_band(const uint32_t* pixels) {
    if(!pixels)return {};
    std::vector<int> lines;
    for(int y=0;y<192;++y) {
        int run=0,longest=0;
        for(int x=5;x<120;++x) {
            const auto p=pixels[y*256+x];const int r=(p>>16)&255,g=(p>>8)&255,b=p&255;
            if(std::min({r,g,b})>180&&std::max({r,g,b})-std::min({r,g,b})<25)longest=std::max(longest,++run);else run=0;
        }
        if(longest>=70&&(lines.empty()||y-lines.back()>2))lines.push_back(y);
    }
    int top=192,bottom=0;
    for(size_t i=0;i+1<lines.size();) {
        const int distance=lines[i+1]-lines[i];
        // The acting member expands to a taller stats/command container.
        // Rejecting it leaves only the other members and crops every command.
        if(distance>=16&&distance<=96){top=std::min(top,lines[i]-2);bottom=std::max(bottom,lines[i+1]+3);i+=2;}
        else ++i;
    }
    int left=256,right=0;
    if(bottom>top)for(int y=0;y<192;++y) {
        int run=0,longest=0,start=0;
        for(int x=0;x<256;++x) {
            const auto p=pixels[y*256+x];const int r=(p>>16)&255,g=(p>>8)&255,b=p&255;
            if(std::min({r,g,b})>180&&std::max({r,g,b})-std::min({r,g,b})<25) {
                if(++run>longest){longest=run;start=x-run+1;}
            } else run=0;
        }
        // Nested command/target lists can extend beyond the party rows.
        // Keep their full borders, contents and source touch coordinates too.
        if(longest>=24&&longest<256){top=std::min(top,y-2);bottom=std::max(bottom,y+3);left=std::min(left,start-2);right=std::max(right,start+longest+2);}
    }
    left=std::max(0,left);right=std::min(256,right);
    if(left>=16&&right<=240&&right-left<224){++left;--right;top+=2;bottom-=2;}
    return bottom>top&&right>left?Box{left,std::max(0,top),right-left,std::min(192,bottom)-std::max(0,top)}:Box{};
}
// Remove only the solid backdrop reachable from a cropped panel's exterior.
// Matching text/interior colors remain enclosed by the original frame border.
inline std::vector<uint32_t> panel_pixels(const uint32_t* pixels,Box box) {
    std::vector<uint32_t> result(pixels,pixels+256*192);std::vector<int> queue;
    const auto background=pixels[0]&0xffffff;
    auto visit=[&](int x,int y){if(x<box.x||x>=box.x+box.w||y<box.y||y>=box.y+box.h)return;
        const int p=y*256+x;if((result[p]>>24)&&(result[p]&0xffffff)==background){result[p]=0;queue.push_back(p);}};
    for(int x=box.x;x<box.x+box.w;++x){visit(x,box.y);visit(x,box.y+box.h-1);}
    for(int y=box.y;y<box.y+box.h;++y){visit(box.x,y);visit(box.x+box.w-1,y);}
    for(size_t n=0;n<queue.size();++n){const int p=queue[n],x=p%256,y=p/256;visit(x-1,y);visit(x+1,y);visit(x,y-1);visit(x,y+1);}
    return result;
}
inline void group_battle_messages(std::vector<Box>& boxes) {
    Box message{};
    std::vector<Box> candidates;
    for(size_t i=0;i<boxes.size();) {
        const auto b=boxes[i];
        if(b.y>=140&&b.h<=32) {
            candidates.push_back(b);message=message.w?unite(message,b):b;boxes.erase(boxes.begin()+i);
        } else ++i;
    }
    if(message.w>=80)boxes.push_back(message);
    else boxes.insert(boxes.end(),candidates.begin(),candidates.end());
}
inline std::vector<Box> window_frames(const uint32_t* pixels) {
    if(!pixels||blank_screen(pixels))return {};
    struct Line {int y,x,end;};std::vector<Line> lines;std::vector<Box> frames;
    auto border=[&](int x,int y){const auto p=pixels[y*256+x];const int r=(p>>16)&255,g=(p>>8)&255,b=p&255;
        return std::min({r,g,b})>130&&std::max({r,g,b})-std::min({r,g,b})<25;};
    for(int y=0;y<192;++y) {
        int start=0;
        for(int x=0;x<=256;++x)if(x==256||!border(x,y)) {
            if(x-start>=64)lines.push_back({y,start,x-1});
            start=x+1;
        }
    }
    for(const auto a:lines)for(const auto b:lines)if(b.y-a.y>=12&&std::abs(a.x-b.x)<=6&&std::abs(a.end-b.end)<=6) {
        auto side=[&](int edge){int best=0;for(int x=std::max(0,edge-6);x<=std::min(255,edge+6);++x){int n=0;
            for(int y=a.y+4;y<=b.y-4;++y)n+=border(x,y);best=std::max(best,n);}return best;};
        const int left=side(std::min(a.x,b.x)),right=side(std::max(a.end,b.end)),h=b.y-a.y-7;
        if(std::max(left,right)*5>=h*4&&std::min(left,right)*2>=h)
            frames.push_back({std::min(a.x,b.x),a.y,std::max(a.end,b.end)-std::min(a.x,b.x)+1,b.y-a.y+1});
    }
    group(frames,0);return frames;
}
inline bool framed_box(const std::vector<Box>& frames,Box box) {
    // One overlay group can contain a dialogue frame, its shadow and a smaller
    // choice window. Find the actual contained frame rather than requiring
    // borders to coincide with the outermost group's transparent padding.
    return std::any_of(frames.begin(),frames.end(),[&](Box b){return b.x>=box.x-4&&b.y>=box.y-4&&
        b.x+b.w<=box.x+box.w+4&&b.y+b.h<=box.y+box.h+4;});
}
inline bool full_window(const uint32_t* pixels) {
    if(!pixels)return false;
    bool top=false,bottom=false;
    for(int y=0;y<192;++y) {
        int run=0,longest=0;
        for(int x=0;x<256;++x) {
            const auto p=pixels[y*256+x];const int r=(p>>16)&255,g=(p>>8)&255,b=p&255;
            if(std::min({r,g,b})>180&&std::max({r,g,b})-std::min({r,g,b})<25)longest=std::max(longest,++run);else run=0;
        }
        // Uniform white fades have no bounded window border.
        top|=y<32&&longest>=160&&longest<252;bottom|=y>=160&&longest>=160&&longest<252;
    }
    return top&&bottom;
}
// A bounded, neutral frame with two long horizontal edges and two vertical
// sides distinguishes static menu pages from synchronized movie pictures.
inline bool has_window(const uint32_t* pixels) {
    struct Line {int y,x,end;};std::vector<Line> lines;
    auto border=[&](int x,int y){const auto p=pixels[y*256+x];const int r=(p>>16)&255,g=(p>>8)&255,b=p&255;
        return std::min({r,g,b})>150&&std::max({r,g,b})-std::min({r,g,b})<25;};
    for(int y=0;y<192;++y) {
        int start=0;
        for(int x=0;x<=256;++x)if(x==256||!border(x,y)) {
            if(x-start>=80&&start>1&&x<254)lines.push_back({y,start,x-1});
            start=x+1;
        }
    }
    for(const auto a:lines)for(const auto b:lines)if(b.y-a.y>=12&&b.y-a.y<=180&&std::abs(a.x-b.x)<=6&&std::abs(a.end-b.end)<=6) {
        auto side=[&](int edge){int best=0;for(int x=std::max(0,edge-6);x<=std::min(255,edge+6);++x){int n=0;
            for(int y=a.y+4;y<=b.y-4;++y)n+=border(x,y);
            best=std::max(best,n);}return best;};
        const int left=side(std::min(a.x,b.x)),right=side(std::max(a.end,b.end)),height=b.y-a.y-7;
        // A selection cursor can cover part of one vertical edge. Keep two
        // aligned horizontal borders and one strong side, with at least half
        // the opposite side still present, throughout the cursor animation.
        if(std::max(left,right)*5>=height*4&&std::min(left,right)*2>=height)return true;
    }
    return false;
}
inline bool logo_background(const uint32_t* pixels,uint32_t& color,unsigned& ink) {
    color=pixels[0]&0xffffff;ink=0;std::vector<uint32_t> colors;colors.reserve(65);
    for(int y=0;y<192;++y)for(int x=0;x<256;++x) {
        const auto p=pixels[y*256+x]&0xffffff;
        if((x==0||x==255||y==0||y==191)&&p!=color)return false;
        ink+=p!=color;
        if(std::find(colors.begin(),colors.end(),p)==colors.end()){colors.push_back(p);if(colors.size()>64)return false;}
    }
    return ink<256*192/4;
}
}
