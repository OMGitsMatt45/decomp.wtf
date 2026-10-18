/* Temporary assembler input belongs in the user's writable Windows temp folder.
 * ISO tmpfile() in the legacy MSVCRT may otherwise use the drive root.
 * This host helper does not change assembly preprocessing or target encoding.
 */
#include <windows.h>
#include <stdio.h>
FILE *windows_tmpfile(void) {
    char directory[MAX_PATH + 1], filename[MAX_PATH + 1];
    DWORD length = GetTempPathA(sizeof(directory), directory);
    FILE *stream;
    if (length == 0 || length >= sizeof(directory)) return NULL;
    if (GetTempFileNameA(directory, "kmc", 0, filename) == 0) return NULL;
    /* D is the Microsoft CRT delete-on-close mode. GetTempFileName creates
       the unique file before returning; fopen opens that existing file. */
    stream = fopen(filename, "w+bD");
    if (stream == NULL) DeleteFileA(filename);
    return stream;
}
