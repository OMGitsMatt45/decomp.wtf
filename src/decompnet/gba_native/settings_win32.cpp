// SPDX-License-Identifier: MIT
#include "cheats.hpp"
#ifndef NOMINMAX
#define NOMINMAX
#endif
#ifndef WIN32_LEAN_AND_MEAN
#define WIN32_LEAN_AND_MEAN
#endif
#include <windows.h>
#include <shellapi.h>
#include <algorithm>
#include <vector>

namespace gba_frontend {
namespace {
using anygba::cheats::Format;
constexpr Format formats[]={Format::Auto,Format::ActionReplay,Format::GameShark,Format::CodeBreaker,
    Format::Raw,Format::ActionReplayRaw,Format::GameSharkRaw};
enum { Codes=100,Toggle,Remove,Name,Device,Body,Add,Status,Folder };
std::wstring wide(const std::string& text){
    const int n=MultiByteToWideChar(CP_UTF8,MB_ERR_INVALID_CHARS,text.data(),int(text.size()),nullptr,0);
    std::wstring result(n,L' ');
    if(n)MultiByteToWideChar(CP_UTF8,0,text.data(),int(text.size()),result.data(),n);
    return result;
}
std::string narrow(const std::wstring& text){
    const int n=WideCharToMultiByte(CP_UTF8,0,text.data(),int(text.size()),nullptr,0,nullptr,nullptr);
    std::string result(n,' ');
    if(n)WideCharToMultiByte(CP_UTF8,0,text.data(),int(text.size()),result.data(),n,nullptr,nullptr);
    return result;
}
std::string text(HWND control){
    std::wstring value(GetWindowTextLengthW(control)+1,L'\0');
    value.resize(GetWindowTextW(control,value.data(),int(value.size())));
    return narrow(value);
}
struct Dialog {
    Cheats& owner;
    anygba::cheats::CheatList draft;
    std::string customization;
    HWND window=nullptr,parent=nullptr,list=nullptr,name=nullptr,format=nullptr,body=nullptr,status=nullptr;
    HFONT font=nullptr;
    float scale=1;
    int px(int value)const{return int(value*scale);}
    HWND control(const wchar_t* type,const std::wstring& caption,DWORD style,int id,int x,int y,int w,int h){
        auto child=CreateWindowExW(type==std::wstring_view(L"EDIT")?WS_EX_CLIENTEDGE:0,type,caption.c_str(),
            WS_CHILD|WS_VISIBLE|style,px(x),px(y),px(w),px(h),window,reinterpret_cast<HMENU>(INT_PTR(id)),GetModuleHandleW(nullptr),nullptr);
        if(!child)throw std::runtime_error("Cannot create settings control");
        SendMessageW(child,WM_SETFONT,reinterpret_cast<WPARAM>(font),TRUE);
        return child;
    }
    void say(const std::string& value){SetWindowTextW(status,wide(value).c_str());}
    void refresh(int selected=-1){
        SendMessageW(list,LB_RESETCONTENT,0,0);
        for(const auto& c:draft.cheats()){
            const auto label=wide(std::string(c.enabled?"[On] ":"[Off] ")+c.name+"  ("+anygba::cheats::format_label(c.format)+")");
            SendMessageW(list,LB_ADDSTRING,0,reinterpret_cast<LPARAM>(label.c_str()));
        }
        if(selected>=0)SendMessageW(list,LB_SETCURSEL,selected,0);
    }
    int selected()const{return int(SendMessageW(list,LB_GETCURSEL,0,0));}
    void toggle(){
        const int i=selected();if(i<0)return;
        const bool enable=!draft.cheats()[i].enabled;
        if(auto error=draft.set_enabled(i,enable)){say(*error);return;}
        if(enable)if(auto error=native_cheat_error(draft.cheats()[i].program)){
            draft.set_enabled(i,false);say(*error);refresh(i);return;
        }
        say("Changes take effect when you choose Save and close.");refresh(i);
    }
    void add(){
        try{
            const auto lines=anygba::cheats::split_lines(text(body));
            if(lines.empty())throw std::runtime_error("Paste or type a cheat code first.");
            const int f=int(SendMessageW(format,CB_GETCURSEL,0,0));
            const auto parsed=anygba::cheats::compile(formats[f>=0&&f<7?f:0],lines);
            if(auto error=native_cheat_error(parsed))throw std::runtime_error(*error);
            auto title=text(name);if(title.empty())title="Code "+std::to_string(draft.cheats().size()+1);
            const auto index=draft.add_custom(title,formats[f>=0&&f<7?f:0],lines);
            if(auto error=draft.set_enabled(index,true)){draft.remove(index);throw std::runtime_error(*error);}
            refresh(int(index));SetWindowTextW(body,L"");
            say("Code added. Choose Save and close to apply it.");
        }catch(const std::exception& e){say(e.what());}
    }
    void command(int id){
        if(id==IDCANCEL){DestroyWindow(window);return;}
        if(id==IDOK){
            if(auto error=owner.commit(draft)){say(*error);return;}
            DestroyWindow(window);return;
        }
        if(id==Toggle)toggle();
        else if(id==Remove){int i=selected();if(i>=0){draft.remove(i);refresh(std::min(i,int(draft.cheats().size())-1));say("Code removed. Choose Save and close to apply.");}}
        else if(id==Add)add();
        else if(id==Folder){
            std::error_code error;
            auto folder=std::filesystem::absolute(owner.path()).parent_path();
            std::filesystem::create_directories(folder,error);
            if(error){say("Cannot open save folder: "+error.message());return;}
            if(reinterpret_cast<INT_PTR>(ShellExecuteW(window,L"open",folder.c_str(),nullptr,nullptr,SW_SHOWNORMAL))<=32)
                say("Windows could not open the save folder.");
        }
    }
    void create(){
        MONITORINFO monitor{};monitor.cbSize=sizeof(monitor);
        GetMonitorInfoW(MonitorFromWindow(parent,MONITOR_DEFAULTTONEAREST),&monitor);
        const auto& work=monitor.rcWork;
        scale=std::min({float(GetDpiForWindow(parent))/96.f,float(work.right-work.left-24)/780.f,float(work.bottom-work.top-24)/660.f});
        font=CreateFontW(-px(14),0,0,0,FW_NORMAL,FALSE,FALSE,FALSE,DEFAULT_CHARSET,OUT_DEFAULT_PRECIS,
            CLIP_DEFAULT_PRECIS,CLEARTYPE_QUALITY,DEFAULT_PITCH|FF_DONTCARE,L"Segoe UI");
        RECT origin{};GetWindowRect(parent,&origin);
        const int x=std::clamp(int((origin.left+origin.right-px(780))/2),int(work.left+8),int(work.right-px(780)-8));
        const int y=std::clamp(int((origin.top+origin.bottom-px(660))/2),int(work.top+8),int(work.bottom-px(660)-8));
        window=CreateWindowExW(WS_EX_DLGMODALFRAME|WS_EX_CONTROLPARENT,L"GbaNativeSettings",L"Game settings — Cheats and saves",
            WS_POPUP|WS_CAPTION|WS_SYSMENU|WS_CLIPCHILDREN,x,y,px(780),px(660),parent,nullptr,GetModuleHandleW(nullptr),this);
        if(!window)throw std::runtime_error("Cannot open game settings");
        control(L"STATIC",L"Cheat codes",0,0,18,14,600,24);
        list=control(L"LISTBOX",L"",WS_BORDER|WS_TABSTOP|WS_VSCROLL|LBS_NOTIFY|LBS_NOINTEGRALHEIGHT,Codes,18,42,730,140);
        control(L"BUTTON",L"Enable / disable",WS_TABSTOP,Toggle,18,190,145,29);
        control(L"BUTTON",L"Remove",WS_TABSTOP,Remove,174,190,100,29);
        control(L"STATIC",L"Name",0,0,18,231,75,20);
        name=control(L"EDIT",L"",WS_TABSTOP|ES_AUTOHSCROLL,Name,18,253,385,26);SendMessageW(name,EM_SETLIMITTEXT,128,0);
        control(L"STATIC",L"Format",0,0,417,231,100,20);
        format=control(L"COMBOBOX",L"",WS_TABSTOP|CBS_DROPDOWNLIST|WS_VSCROLL,Device,417,253,331,220);
        for(auto f:formats){const auto label=wide(anygba::cheats::format_label(f));SendMessageW(format,CB_ADDSTRING,0,reinterpret_cast<LPARAM>(label.c_str()));}
        SendMessageW(format,CB_SETCURSEL,0,0);
        control(L"STATIC",L"Code — paste multiple lines; auto-detect accepts Action Replay, GameShark and CodeBreaker",0,0,18,290,730,22);
        body=control(L"EDIT",L"",WS_TABSTOP|WS_VSCROLL|ES_MULTILINE|ES_AUTOVSCROLL|ES_WANTRETURN,Body,18,315,730,83);
        SendMessageW(body,EM_SETLIMITTEXT,32768,0);
        control(L"BUTTON",L"Add and enable",WS_TABSTOP,Add,18,407,145,29);
        status=control(L"STATIC",L"Changes apply when saved. The game is paused while this window is open.",0,Status,178,407,570,47);
        control(L"STATIC",wide(customization.empty()?"Game modifications: none.":customization),0,0,18,462,730,38);
        control(L"STATIC",L"PKHeX: close the game, edit the .sav file, then reopen the game and choose Continue.\nCheat preferences are stored separately and do not change the save format.",0,0,18,507,565,48);
        control(L"BUTTON",L"Open save folder",WS_TABSTOP,Folder,597,510,151,29);
        control(L"BUTTON",L"Save and close",WS_TABSTOP|BS_DEFPUSHBUTTON,IDOK,484,575,130,32);
        control(L"BUTTON",L"Cancel",WS_TABSTOP,IDCANCEL,627,575,121,32);
        refresh();EnableWindow(parent,FALSE);ShowWindow(window,SW_SHOW);SetForegroundWindow(window);SetFocus(list);
    }
    ~Dialog(){if(window)DestroyWindow(window);if(parent){EnableWindow(parent,TRUE);SetForegroundWindow(parent);}if(font)DeleteObject(font);}
};
LRESULT CALLBACK procedure(HWND window,UINT message,WPARAM w,LPARAM l){
    auto* dialog=reinterpret_cast<Dialog*>(GetWindowLongPtrW(window,GWLP_USERDATA));
    if(message==WM_NCCREATE){dialog=static_cast<Dialog*>(reinterpret_cast<CREATESTRUCTW*>(l)->lpCreateParams);SetWindowLongPtrW(window,GWLP_USERDATA,reinterpret_cast<LONG_PTR>(dialog));}
    if(dialog){
        if(message==WM_CLOSE){DestroyWindow(window);return 0;}
        if(message==WM_COMMAND){
            try{if(LOWORD(w)==Codes&&HIWORD(w)==LBN_DBLCLK)dialog->toggle();else dialog->command(LOWORD(w));}
            catch(const std::exception& e){dialog->say(e.what());}
            return 0;
        }
        if(message==WM_NCDESTROY){dialog->window=nullptr;SetWindowLongPtrW(window,GWLP_USERDATA,0);}
    }
    return DefWindowProcW(window,message,w,l);
}
}
void show_settings(void* parent,Cheats& cheats,const std::string& customization){
    WNDCLASSW cls{};cls.lpfnWndProc=procedure;cls.hInstance=GetModuleHandleW(nullptr);
    cls.hCursor=LoadCursorW(nullptr,MAKEINTRESOURCEW(32512));cls.hbrBackground=reinterpret_cast<HBRUSH>(COLOR_BTNFACE+1);cls.lpszClassName=L"GbaNativeSettings";
    if(!RegisterClassW(&cls)&&GetLastError()!=ERROR_CLASS_ALREADY_EXISTS)throw std::runtime_error("Cannot register settings window");
    Dialog dialog{cheats,cheats.list(),customization};dialog.parent=static_cast<HWND>(parent);dialog.create();
    MSG message{};
    while(dialog.window){
        int result=GetMessageW(&message,nullptr,0,0);
        if(result<=0){if(result==0)PostQuitMessage(int(message.wParam));break;}
        if(!IsDialogMessageW(dialog.window,&message)){TranslateMessage(&message);DispatchMessageW(&message);}
    }
}
}
