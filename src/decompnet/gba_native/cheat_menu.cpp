// SPDX-License-Identifier: MIT
#include "cheat_menu.hpp"
#include "cheats.hpp"
#include "video.hpp"
#include <algorithm>
#include <cctype>
#include <string_view>

namespace gba_frontend {
namespace {
constexpr uint16_t rgb(unsigned r,unsigned g,unsigned b){return uint16_t(r|(g<<5)|(b<<10));}
constexpr auto background=rgb(3,7,10),panel=rgb(6,12,15),ink=rgb(29,31,29),muted=rgb(18,22,23),accent=rgb(5,19,15),selected=rgb(6,16,23),gold=rgb(31,26,10);
// Original compact uppercase bitmap font; five columns by seven rows.
constexpr uint8_t letters[][7]={
 {14,17,17,31,17,17,17},{30,17,17,30,17,17,30},{14,17,16,16,16,17,14},
 {30,17,17,17,17,17,30},{31,16,16,30,16,16,31},{31,16,16,30,16,16,16},
 {14,17,16,23,17,17,15},{17,17,17,31,17,17,17},{14,4,4,4,4,4,14},
 {7,2,2,2,18,18,12},{17,18,20,24,20,18,17},{16,16,16,16,16,16,31},
 {17,27,21,21,17,17,17},{17,25,21,19,17,17,17},{14,17,17,17,17,17,14},
 {30,17,17,30,16,16,16},{14,17,17,17,21,18,13},{30,17,17,30,20,18,17},
 {15,16,16,14,1,1,30},{31,4,4,4,4,4,4},{17,17,17,17,17,17,14},
 {17,17,17,17,17,10,4},{17,17,17,21,21,27,17},{17,17,10,4,10,17,17},
 {17,17,10,4,4,4,4},{31,1,2,4,8,16,31},
 {14,17,19,21,25,17,14},{4,12,4,4,4,4,14},{14,17,1,2,4,8,31},
 {30,1,1,14,1,1,30},{2,6,10,18,31,2,2},{31,16,16,30,1,1,30},
 {14,16,16,30,17,17,14},{31,1,2,4,8,8,8},{14,17,17,14,17,17,14},
 {14,17,17,15,1,1,14}};
uint8_t glyph(char ch,int row){
 ch=char(std::toupper(static_cast<unsigned char>(ch)));
 if(ch>='A'&&ch<='Z')return letters[ch-'A'][row];
 if(ch>='0'&&ch<='9')return letters[26+ch-'0'][row];
 switch(ch){
 case '-':return row==3?14:0;case '_':return row==6?31:0;
 case '.':return row==6?4:0;case ',':return row==5?4:row==6?8:0;
 case ':':return row==2||row==5?4:0;case '/':return uint8_t(1u<<std::min(4,6-row));
 case '(':return row==0||row==6?2:4;case ')':return row==0||row==6?8:4;
 case '[':return row==0||row==6?14:8;case ']':return row==0||row==6?14:2;
 case '<':return row==1||row==5?2:row==2||row==4?4:row==3?8:0;
 case '>':return row==1||row==5?8:row==2||row==4?4:row==3?2:0;
 case '!':return row<4||row==6?4:0;case '+':return row==3?14:row==2||row==4?4:0;
 case 39:return row<2?4:0;case '?':return row==0?14:row==1?17:row==2?2:row==3||row==6?4:0;
 default:return 0;}
}
void box(std::vector<uint16_t>& p,int x,int y,int w,int h,uint16_t color){
 for(int yy=std::max(0,y);yy<std::min(160,y+h);++yy)for(int xx=std::max(0,x);xx<std::min(240,x+w);++xx)p[yy*240+xx]=color;
}
void text(std::vector<uint16_t>& p,int x,int y,std::string_view s,uint16_t color=ink,int limit=39){
 for(char ch:s){if(--limit<0)break;for(int r=0;r<7;++r)for(int c=0;c<5;++c)if(glyph(ch,r)&(16>>c))box(p,x+c,y+r,1,1,color);x+=6;}
}
void wrap(std::vector<uint16_t>& p,int x,int y,std::string s,int width,int lines,uint16_t color=muted){
 while(!s.empty()&&lines-->0){size_t cut=std::min(s.size(),size_t(width));if(cut<s.size()){auto at=s.rfind(' ',cut);if(at!=s.npos&&at>0)cut=at;}
  text(p,x,y,s.substr(0,cut),color,width);s.erase(0,cut);while(!s.empty()&&s.front()==' ')s.erase(0,1);y+=9;}
}
}
void CheatBrowser::present_hint(gba_video::Display& display,std::span<const uint16_t> game){
 pixels_.assign(game.begin(),game.end());box(pixels_,169,149,71,11,background);text(pixels_,175,151,"W:CHEATS",gold);display.present_pixels(pixels_);
}
bool CheatBrowser::show(gba_video::Display& display,CheatCatalog& catalog,Cheats& custom,const std::string& status){
 display.pause(true);
 struct Resume {gba_video::Display& d;~Resume(){d.pause(false);}} resume{display};
 std::vector<std::string> categories{"All"};for(const auto& p:catalog.presets())if(std::find(categories.begin(),categories.end(),p.category)==categories.end())categories.push_back(p.category);
 if(category_>=categories.size())category_=0;
 std::string message=catalog.warning();
 uint16_t previous=0;if(!display.poll(previous))return false;
 unsigned hold=0;uint16_t last_direction=0;
 for(;;){
  std::vector<size_t> rows;for(size_t i=0;i<catalog.presets().size();++i)if(category_==0||catalog.presets()[i].category==categories[category_])rows.push_back(i);
  if(selection_>=rows.size())selection_=rows.empty()?0:rows.size()-1;
  pixels_.assign(240*160,background);box(pixels_,0,0,240,20,accent);text(pixels_,7,6,"CHEATS");text(pixels_,151,6,std::to_string(catalog.enabled_count()+custom.enabled())+" ENABLED",ink,14);
  text(pixels_,7,25,"< "+categories[category_]+" >",gold,27);text(pixels_,177,25,"Q/W PAGE",muted,10);
  if(rows.empty())wrap(pixels_,9,50,"No presets loaded. F2 opens custom code entry.",36,3);
  const size_t first=selection_/8*8;
  for(size_t i=first;i<std::min(rows.size(),first+8);++i){const auto& p=catalog.presets()[rows[i]];int y=39+int(i-first)*10;
   if(i==selection_)box(pixels_,4,y-1,232,9,selected);
   text(pixels_,8,y,p.name,p.unavailable.empty()?ink:muted,31);
   text(pixels_,204,y,!p.unavailable.empty()?"N/A":catalog.enabled(p.id)?"ON":"OFF",catalog.enabled(p.id)?gold:muted,5);
  }
  if(!rows.empty()){const auto& p=catalog.presets()[rows[selection_]];wrap(pixels_,8,122,p.name+(p.note.empty()?"":". "+p.note),37,2);text(pixels_,194,143,std::to_string(selection_+1)+"/"+std::to_string(rows.size()),muted,8);}
  else wrap(pixels_,8,122,status,37,2);
  box(pixels_,0,149,240,11,panel);text(pixels_,5,151,"X:TOGGLE Z:BACK BS:OFF F2:CODES",ink,39);
  if(!message.empty()){box(pixels_,9,43,222,99,panel);box(pixels_,9,43,222,2,gold);text(pixels_,17,51,"CHEAT INFO",gold);wrap(pixels_,17,65,message,34,6,ink);text(pixels_,17,131,"X/Z RETURN",gold);}
  display.present_pixels(pixels_);display.pace();
  uint16_t keys=0;bool close=false,advanced=false;
  if(!display.poll(keys,&close,nullptr,&advanced)){held_=keys;return false;}
  const uint16_t down=keys&~previous;previous=keys;
  if(close||((down&(2|8))&&message.empty())){held_=keys;return true;}
  if(!message.empty()){if(down&(1|2|8))message.clear();continue;}
#ifdef _WIN32
  if(advanced){show_settings(display.native_window(),custom,status);display.pause(true);previous=0;continue;}
#endif
  const uint16_t direction=keys&(16|32|64|128|256|512);
  if(direction!=last_direction){last_direction=direction;hold=0;}else ++hold;
  const auto action=uint16_t(down|((hold>=20&&hold%4==0)?direction:0));
  if(action&16){category_=(category_+1)%categories.size();selection_=0;}
  else if(action&32){category_=(category_+categories.size()-1)%categories.size();selection_=0;}
  else if(!rows.empty()){
   if(action&128)selection_=(selection_+1)%rows.size();else if(action&64)selection_=(selection_+rows.size()-1)%rows.size();
   else if(action&256)selection_=std::min(selection_+8,rows.size()-1);else if(action&512)selection_=selection_>=8?selection_-8:0;
   if(down&1){const auto& p=catalog.presets()[rows[selection_]];if(auto e=catalog.set_enabled(p.id,!catalog.enabled(p.id)))message=*e;}
  }
  if(down&4){
   auto manual=custom.list();for(size_t i=0;i<manual.cheats().size();++i)manual.set_enabled(i,false);
   if(auto e=custom.commit(std::move(manual)))message=*e;
   else if(auto e=catalog.all_off())message=*e;
  }
 }
}
}
