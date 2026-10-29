// SPDX-License-Identifier: MIT. Exclusive ownership of an exported game's save.
#pragma once
#include <filesystem>
#include <stdexcept>
#include <string>
#ifdef _WIN32
#ifndef NOMINMAX
#define NOMINMAX
#endif
#ifndef WIN32_LEAN_AND_MEAN
#define WIN32_LEAN_AND_MEAN
#endif
#include <windows.h>
#else
#include <cerrno>
#include <fcntl.h>
#include <sys/file.h>
#include <unistd.h>
#endif

namespace ds_host {
// Lock a stable sidecar, not the save inode: atomic replacement changes that
// inode. Keep the sidecar after closing so competing processes cannot obtain
// locks on two different inodes. OS ownership expires on normal or crash exit.
class SaveLock {
public:
    explicit SaveLock(const std::filesystem::path& save) {
        auto path=std::filesystem::weakly_canonical(save);path+=".lock";
#ifdef _WIN32
        handle_=CreateFileW(path.c_str(),GENERIC_READ|GENERIC_WRITE,0,nullptr,
                            OPEN_ALWAYS,FILE_ATTRIBUTE_NORMAL,nullptr);
        if(handle_==INVALID_HANDLE_VALUE)fail();
#else
        handle_=::open(path.c_str(),O_RDWR|O_CREAT|O_CLOEXEC|O_NOFOLLOW,0600);
        if(handle_<0)fail();
        int result;
        do {result=::flock(handle_,LOCK_EX|LOCK_NB);}while(result<0&&errno==EINTR);
        if(result<0){::close(handle_);handle_=-1;fail();}
#endif
    }
    ~SaveLock() {
#ifdef _WIN32
        if(handle_!=INVALID_HANDLE_VALUE)CloseHandle(handle_);
#else
        if(handle_>=0)::close(handle_);
#endif
    }
    SaveLock(const SaveLock&)=delete;
    SaveLock& operator=(const SaveLock&)=delete;
private:
    [[noreturn]] static void fail() {
        throw std::runtime_error("Cannot lock cartridge save: it is already in use or its directory is not writable");
    }
#ifdef _WIN32
    HANDLE handle_=INVALID_HANDLE_VALUE;
#else
    int handle_=-1;
#endif
};
}
