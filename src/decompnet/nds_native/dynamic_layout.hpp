// SPDX-License-Identifier: MIT. Original host window grouping and placement.
#pragma once
#include <algorithm>
#include <array>
#include <vector>
#include <cstdint>
#include <cstdlib>

namespace video::layout_detail {
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
    if(bottom>top)for(int y=0;y<192;++y) {
        int run=0,longest=0;
        for(int x=0;x<256;++x) {
            const auto p=pixels[y*256+x];const int r=(p>>16)&255,g=(p>>8)&255,b=p&255;
            if(std::min({r,g,b})>180&&std::max({r,g,b})-std::min({r,g,b})<25)longest=std::max(longest,++run);else run=0;
        }
        // Nested command/target lists can extend beyond the party rows.
        // Keep their full borders, contents and source touch coordinates too.
        if(longest>=24&&longest<252){top=std::min(top,y-2);bottom=std::max(bottom,y+3);}
    }
    return bottom>top?Box{0,std::max(0,top),256,std::min(192,bottom)-std::max(0,top)}:Box{};
}
inline void group_battle_messages(std::vector<Box>& boxes) {
    Box message{};
    for(size_t i=0;i<boxes.size();) {
        const auto b=boxes[i];
        if(b.y>=128||(b.w>=190&&b.y+b.h>=155)) {
            message=message.w?unite(message,b):b;boxes.erase(boxes.begin()+i);
        } else ++i;
    }
    if(message.w)boxes.push_back(message);
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
