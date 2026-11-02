#pragma once
#include <SDL.h>
inline SDL_Window* ds_test_create_window(const char* title,int x,int y,int w,int h,Uint32 flags) {
    return SDL_CreateWindow(title,x,y,w,h,(flags&~SDL_WINDOW_SHOWN)|SDL_WINDOW_HIDDEN);
}
#define SDL_CreateWindow ds_test_create_window
