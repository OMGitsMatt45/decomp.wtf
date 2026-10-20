/* Experimental i386 ELF/libc ABI host. Original guest instructions execute on
 * the x86 CPU. This program is NOT an emulator or a replacement GCC frontend.
 * No unsupported ABI operation may silently report success.
 */
#define __USE_MINGW_ANSI_STDIO 1
#include "getopt.h"
#include "obstack.h"
#include <ctype.h>
#include <errno.h>
#include <fcntl.h>
#include <io.h>
#include <locale.h>
#include <process.h>
#include <signal.h>
#include <stdarg.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <sys/timeb.h>
#include <sys/utime.h>
#include <time.h>
#include <windows.h>
extern int _obstack_allocated_p(struct obstack *, void *);

_Static_assert(sizeof(void *) == 4, "This host requires Win32 x86, not x64");
struct segment {
  unsigned address, offset, size, memory;
};
struct relocation {
  unsigned address, size, kind, local;
  const char *name;
  void (*missing)(void);
};
static void unsupported(const char *what);
extern const unsigned char payload_start[] __asm__("_binary_payload_elf_start");
extern const unsigned char payload_end[] __asm__("_binary_payload_elf_end");
#include "image.h"

/* Keep glibc's inline stdio fast paths empty. All IO crosses an ABI wrapper. */
typedef struct {
  unsigned flags;
  void *empty[15];
  FILE *host;
} guest_file;
static guest_file in_file, out_file, err_file;
static guest_file *guest_in = &in_file, *guest_out = &out_file,
                  *guest_err = &err_file;
static unsigned short ctype_storage[384], *ctype_table = ctype_storage + 128;
static int lower_storage[384], *lower_table = lower_storage + 128;
static int upper_storage[384], *upper_table = upper_storage + 128;
static char **guest_environ;
static char *default_dir = ".";
static unsigned zero;
static char **optarg_copy;

static int guest_getopt(int n, char **a, const char *opts,
                        const struct option *longs, int *index) {
  int r = getopt_long_only(n, a, opts, longs, index);
  if (optarg_copy)
    *optarg_copy = optarg;
  return r;
}

static void unsupported(const char *what) {
  fprintf(stderr, "ee-elf-host: unsupported ABI operation: %s\n", what);
  exit(126);
}
static void noop(void) {}
static void *rawmemchr(const void *p, int c) {
  const unsigned char *s = p;
  while (*s != (unsigned char)c)
    ++s;
  return (void *)s;
}
static char *stpcopy(char *d, const char *s) {
  size_t n = strlen(s);
  memcpy(d, s, n + 1);
  return d + n;
}
static void zero_bytes(void *p, size_t n) { memset(p, 0, n); }
static void copy_bytes(const void *a, void *b, size_t n) { memmove(b, a, n); }
static int cmp_bytes(const void *a, const void *b, size_t n) {
  return memcmp(a, b, n);
}
static char *domain(const char *s) { return (char *)s; }
static char *bind_domain(const char *a, const char *b) {
  (void)a;
  return (char *)b;
}
static char *dcgettext(const char *a, const char *b, int c) {
  (void)a;
  (void)c;
  return (char *)b;
}
static long strtol_internal(const char *s, char **end, int base, int group) {
  if (group)
    unsupported("strtol grouping");
  return strtol(s, end, base);
}
static unsigned long strtoul_internal(const char *s, char **end, int base,
                                      int group) {
  if (group)
    unsupported("strtoul grouping");
  return strtoul(s, end, base);
}
static long long strtoll_internal(const char *s, char **end, int base,
                                  int group) {
  if (group)
    unsupported("strtoll grouping");
  return strtoll(s, end, base);
}
static size_t argz_count(const char *a, size_t n) {
  size_t count = 0;
  for (size_t i = 0; i < n; i++)
    count += !a[i];
  return count;
}
static void argz_stringify(char *a, size_t n, int sep) {
  for (size_t i = 0; i + 1 < n; i++)
    if (!a[i])
      a[i] = sep;
}

static guest_file *wrap_file(FILE *f) {
  if (!f)
    return NULL;
  guest_file *g = calloc(1, sizeof(*g));
  g->flags = 0xfbad0000;
  g->host = f;
  return g;
}
static guest_file *open_file(const char *p, const char *m) {
  char mode[16];
  snprintf(mode, sizeof(mode), "%s%s", m, strchr(m, 'b') ? "" : "b");
  return wrap_file(fopen(p, mode));
}
static guest_file *fdopen_file(int fd, const char *m) {
  return wrap_file(_fdopen(fd, m));
}
static int close_file(guest_file *f) {
  int r = fclose(f->host);
  free(f);
  return r;
}
static int print_file(guest_file *f, const char *fmt, ...) {
  va_list a;
  va_start(a, fmt);
  int r = vfprintf(f->host, fmt, a);
  va_end(a);
  return r;
}
static int vprint_file(guest_file *f, const char *fmt, va_list a) {
  return vfprintf(f->host, fmt, a);
}
static int put_string(const char *s, guest_file *f) {
  return fputs(s, f->host);
}
static int put_char(int c, guest_file *f) { return fputc(c, f->host); }
static int overflow(guest_file *f, int c) {
  return c == EOF ? fflush(f->host) : fputc(c, f->host);
}
static int get_char(guest_file *f) { return fgetc(f->host); }
static int unget_char(int c, guest_file *f) { return ungetc(c, f->host); }
static char *get_string(char *s, int n, guest_file *f) {
  return fgets(s, n, f->host);
}
static size_t read_file(void *p, size_t s, size_t n, guest_file *f) {
  return fread(p, s, n, f->host);
}
static size_t write_file(const void *p, size_t s, size_t n, guest_file *f) {
  return fwrite(p, s, n, f->host);
}
static int flush_file(guest_file *f) { return fflush(f ? f->host : NULL); }
static int eof_file(guest_file *f) { return feof(f->host); }
static int error_file(guest_file *f) { return ferror(f->host); }
static int number_file(guest_file *f) { return _fileno(f->host); }
static int seek_file(guest_file *f, long o, int w) {
  return fseek(f->host, o, w);
}
static long tell_file(guest_file *f) { return ftell(f->host); }
static void rewind_file(guest_file *f) { rewind(f->host); }
static int vformat_alloc(char **out, const char *fmt, va_list a) {
  va_list b;
  va_copy(b, a);
  int n = vsnprintf(NULL, 0, fmt, b);
  va_end(b);
  if (n < 0)
    return n;
  *out = malloc(n + 1);
  return vsnprintf(*out, n + 1, fmt, a);
}
static int format_alloc(char **out, const char *fmt, ...) {
  va_list a;
  va_start(a, fmt);
  int n = vformat_alloc(out, fmt, a);
  va_end(a);
  return n;
}

static void stat_copy(void *out, const struct _stat *s) {
  memset(out, 0, 88);
  unsigned *w = out;
  w[3] = s->st_ino;
  w[4] = s->st_mode;
  w[5] = s->st_nlink;
  w[6] = s->st_uid;
  w[7] = s->st_gid;
  w[11] = s->st_size;
  w[12] = 4096;
  w[13] = (s->st_size + 511) / 512;
  w[14] = s->st_atime;
  w[16] = s->st_mtime;
  w[18] = s->st_ctime;
}
static int xstat(int ver, const char *path, void *out) {
  if (ver != 3)
    unsupported("stat ABI version");
  struct _stat s;
  int r = _stat(path, &s);
  if (!r)
    stat_copy(out, &s);
  return r;
}
static int fxstat(int ver, int fd, void *out) {
  if (ver != 3)
    unsupported("fstat ABI version");
  struct _stat s;
  int r = _fstat(fd, &s);
  if (!r)
    stat_copy(out, &s);
  return r;
}
static int open_fd(const char *path, int flags, ...) {
  int out = 0;
  switch (flags & 3) {
  case 0:
    out = _O_RDONLY;
    break;
  case 1:
    out = _O_WRONLY;
    break;
  case 2:
    out = _O_RDWR;
    break;
  }
  if (flags & 64)
    out |= _O_CREAT;
  if (flags & 128)
    out |= _O_EXCL;
  if (flags & 512)
    out |= _O_TRUNC;
  if (flags & 1024)
    out |= _O_APPEND;
  if (flags & ~(3 | 64 | 128 | 256 | 512 | 1024 | 0x8000))
    unsupported("open flags");
  return _open(path, out | _O_BINARY, _S_IREAD | _S_IWRITE);
}
static void *map_memory(void *addr, size_t len, int prot, int flags, int fd,
                        long off) {
  if (addr || (flags & 16))
    unsupported("fixed mmap");
  void *p = VirtualAlloc(NULL, len, MEM_RESERVE | MEM_COMMIT, PAGE_READWRITE);
  if (!p) {
    errno = ENOMEM;
    return (void *)-1;
  }
  if (!(flags & 32)) {
    long pos = _lseek(fd, 0, SEEK_CUR);
    if (pos < 0 || _lseek(fd, off, SEEK_SET) < 0) {
      VirtualFree(p, 0, MEM_RELEASE);
      return (void *)-1;
    }
    size_t got = 0;
    while (got < len) {
      int n = _read(fd, (char *)p + got, len - got);
      if (n < 0) {
        VirtualFree(p, 0, MEM_RELEASE);
        _lseek(fd, pos, SEEK_SET);
        return (void *)-1;
      }
      if (!n)
        break;
      got += n;
    }
    _lseek(fd, pos, SEEK_SET);
  }
  (void)prot;
  return p;
}
static int unmap_memory(void *p, size_t n) {
  (void)n;
  return VirtualFree(p, 0, MEM_RELEASE) ? 0 : -1;
}
static void *program_break(int n) {
  static char *base;
  static size_t used;
  if (!base)
    base = VirtualAlloc(NULL, 64 * 1024 * 1024, MEM_RESERVE | MEM_COMMIT,
                        PAGE_READWRITE);
  if (!base || n < 0 || used + (unsigned)n > 64 * 1024 * 1024) {
    errno = ENOMEM;
    return (void *)-1;
  }
  void *p = base + used;
  used += n;
  return p;
}
static int pagesize(void) { return 4096; }
static long system_conf(int n) {
  if (n == 30)
    return 4096;
  unsupported("sysconf key");
  return -1;
}
static int time_of_day(int *t, void *tz) {
  struct _timeb b;
  _ftime(&b);
  t[0] = b.time;
  t[1] = b.millitm * 1000;
  (void)tz;
  return 0;
}
static int usage(int who, void *p) {
  typedef BOOL(WINAPI * times_fn)(HANDLE, LPFILETIME, LPFILETIME, LPFILETIME,
                                  LPFILETIME);
  times_fn query = (times_fn)GetProcAddress(GetModuleHandleA("kernel32.dll"),
                                            "GetProcessTimes");
  FILETIME created, ended, kernel, user;
  if (who || !query ||
      !query(GetCurrentProcess(), &created, &ended, &kernel, &user)) {
    errno = ENOSYS;
    return -1;
  }
  memset(p, 0, 72);
  uint64_t k = ((uint64_t)kernel.dwHighDateTime << 32) | kernel.dwLowDateTime;
  uint64_t u = ((uint64_t)user.dwHighDateTime << 32) | user.dwLowDateTime;
  int *out = p;
  out[0] = u / 10000000;
  out[1] = (u % 10000000) / 10;
  out[2] = k / 10000000;
  out[3] = (k % 10000000) / 10;
  return 0;
}
static long process_times(void *p) {
  int r[18];
  if (usage(0, r))
    return -1;
  long *t = p;
  t[0] = r[0] * 100 + r[1] / 10000;
  t[1] = r[2] * 100 + r[3] / 10000;
  t[2] = t[3] = 0;
  return GetTickCount() / 10;
}
static unsigned user_id(void) { return 0; }
static char *signal_string(int s) {
  (void)s;
  return "signal";
}
static unsigned sleep_seconds(unsigned s) {
  Sleep(s * 1000);
  return 0;
}
static char *temporary_name(char *p) { return _mktemp(p); }
static int change_mode(const char *p, int mode) { return _chmod(p, mode); }
static int mask_mode(int mode) { return _umask(mode); }
static int access_path(const char *p, int mode) {
  return _access(p, mode & ~1);
}

/* The original driver otherwise needs fork. Replace only libiberty's host
 * process boundary, retaining its option specs and all compiler algorithms. */
static int child_status, child_serial = 100;
static char *quote_argument(const char *s) {
  char *out = malloc(2 * strlen(s) + 3), *p = out;
  *p++ = '"';
  while (*s) {
    unsigned slash = 0;
    while (*s == '\\') {
      slash++;
      s++;
    }
    unsigned copies = (*s == '"' || !*s) ? slash * 2 : slash;
    while (copies--)
      *p++ = '\\';
    if (!*s)
      break;
    if (*s == '"')
      *p++ = '\\';
    *p++ = *s++;
  }
  *p++ = '"';
  *p = 0;
  return out;
}
static int execute_child(const char *program, char *const *argv,
                         const char *name, const char *temp, char **fmt,
                         char **arg, int flags) {
  (void)name;
  (void)temp;
  if ((flags & 3) != 3)
    unsupported("compiler process pipelines (-pipe)");
  char exe[MAX_PATH * 4];
  if (snprintf(exe, sizeof(exe), "%s.exe", program) >= (int)sizeof(exe)) {
    errno = ENAMETOOLONG;
    return -1;
  }
  unsigned count = 0;
  while (argv[count])
    count++;
  char **quoted = calloc(count + 1, sizeof(*quoted));
  for (unsigned i = 0; i < count; i++)
    quoted[i] = quote_argument(argv[i]);
  intptr_t result = (flags & 4)
                        ? _spawnvp(_P_WAIT, exe, (const char *const *)quoted)
                        : _spawnv(_P_WAIT, exe, (const char *const *)quoted);
  for (unsigned i = 0; i < count; i++)
    free(quoted[i]);
  free(quoted);
  if (result < 0) {
    *fmt = "cannot execute %s";
    *arg = (char *)program;
    return -1;
  }
  if (result > 255)
    unsupported("child exit status outside POSIX range");
  child_status = (int)result << 8;
  return ++child_serial;
}
static int wait_child(int pid, int *status, int flags) {
  (void)flags;
  if (pid != child_serial)
    unsupported("unknown child process");
  *status = child_status;
  return pid;
}
static void detour(unsigned address, void *target) {
  unsigned char *p = (void *)address;
  p[0] = 0xe9;
  *(uint32_t *)(p + 1) = (uintptr_t)target - address - 5;
}

/* Original glibc i386 jmp_buf saves EBX, ESI, EDI, EBP, ESP and EIP. */
__attribute__((naked, returns_twice)) static int save_jump(void *buf,
                                                           int signals) {
  __asm__(
      "mov 4(%esp),%eax; mov %ebx,0(%eax); mov %esi,4(%eax); mov %edi,8(%eax); "
      "mov %ebp,12(%eax); lea 4(%esp),%edx; mov %edx,16(%eax); mov "
      "(%esp),%edx; mov %edx,20(%eax); movl $0,24(%eax); xor %eax,%eax; ret");
}
__attribute__((naked, noreturn)) static void restore_jump(void *buf,
                                                          int value) {
  __asm__("mov 4(%esp),%edx; mov 8(%esp),%eax; test %eax,%eax; jnz 1f; inc "
          "%eax; 1: mov 0(%edx),%ebx; mov 4(%edx),%esi; mov 8(%edx),%edi; mov "
          "12(%edx),%ebp; mov 16(%edx),%esp; jmp *20(%edx)");
}

static void init_ctype(void) {
  for (int i = -128; i < 256; i++) {
    int c = (unsigned char)i;
    unsigned short bits = 0;
    if (isupper(c))
      bits |= 1 << 8;
    if (islower(c))
      bits |= 1 << 9;
    if (isalpha(c))
      bits |= 1 << 10;
    if (isdigit(c))
      bits |= 1 << 11;
    if (isxdigit(c))
      bits |= 1 << 12;
    if (isspace(c))
      bits |= 1 << 13;
    if (isprint(c))
      bits |= 1 << 14;
    if (isgraph(c))
      bits |= 1 << 15;
    if (c == ' ' || c == '\t')
      bits |= 1;
    if (iscntrl(c))
      bits |= 2;
    if (ispunct(c))
      bits |= 4;
    if (isalnum(c))
      bits |= 8;
    ctype_table[i] = bits;
    lower_table[i] = tolower(c);
    upper_table[i] = toupper(c);
  }
  ctype_table[-1] = 0;
  lower_table[-1] = -1;
  upper_table[-1] = -1;
}

static void *resolve(const char *name, int data) {
#define BIND(n, f)                                                             \
  if (!strcmp(name, n))                                                        \
  return (void *)(f)
  if (data) {
    BIND("stdin", &guest_in);
    BIND("stdout", &guest_out);
    BIND("stderr", &guest_err);
    BIND("optarg", &optarg);
    BIND("optind", &optind);
    BIND("opterr", &opterr);
    BIND("optopt", &optopt);
    BIND("__ctype_b", &ctype_table);
    BIND("__ctype_tolower", &lower_table);
    BIND("__ctype_toupper", &upper_table);
    BIND("environ", &guest_environ);
    BIND("__environ", &guest_environ);
    BIND("_environ", &guest_environ);
    BIND("_nl_default_dirname", &default_dir);
    if (!strncmp(name, "_nl_", 4))
      return &zero;
    fprintf(stderr, "ee-elf-host: unknown data import %s\n", name);
    exit(126);
  }
  BIND("__gmon_start__", noop);
  BIND("__rawmemchr", rawmemchr);
  BIND("__stpcpy", stpcopy);
  BIND("__strdup", strdup);
  BIND("__bzero", zero_bytes);
  BIND("bzero", zero_bytes);
  BIND("bcopy", copy_bytes);
  BIND("bcmp", cmp_bytes);
  BIND("index", strchr);
  BIND("rindex", strrchr);
  BIND("strcasecmp", stricmp);
  BIND("strncasecmp", strnicmp);
  BIND("__strtol_internal", strtol_internal);
  BIND("__strtoul_internal", strtoul_internal);
  BIND("__strtoll_internal", strtoll_internal);
  BIND("__argz_count", argz_count);
  BIND("__argz_stringify", argz_stringify);
  BIND("textdomain", domain);
  BIND("bindtextdomain", bind_domain);
  BIND("__dcgettext", dcgettext);
  BIND("fopen", open_file);
  BIND("fdopen", fdopen_file);
  BIND("fclose", close_file);
  BIND("fprintf", print_file);
  BIND("vfprintf", vprint_file);
  BIND("fputs", put_string);
  BIND("fputs_unlocked", put_string);
  BIND("fputc", put_char);
  BIND("_IO_putc", put_char);
  BIND("__overflow", overflow);
  BIND("_IO_getc", get_char);
  BIND("fgetc", get_char);
  BIND("ungetc", unget_char);
  BIND("fgets", get_string);
  BIND("fread", read_file);
  BIND("fwrite", write_file);
  BIND("fflush", flush_file);
  BIND("feof", eof_file);
  BIND("ferror", error_file);
  BIND("fileno", number_file);
  BIND("fseek", seek_file);
  BIND("ftell", tell_file);
  BIND("rewind", rewind_file);
  BIND("asprintf", format_alloc);
  BIND("vasprintf", vformat_alloc);
  BIND("_obstack_begin", _obstack_begin);
  BIND("_obstack_newchunk", _obstack_newchunk);
  BIND("obstack_free", _obstack_free);
  BIND("_obstack_allocated_p", _obstack_allocated_p);
  BIND("__xstat", xstat);
  BIND("__fxstat", fxstat);
  BIND("__errno_location", _errno);
  BIND("open", open_fd);
  BIND("close", _close);
  BIND("read", _read);
  BIND("lseek", _lseek);
  BIND("access", access_path);
  BIND("getcwd", _getcwd);
  BIND("getpid", _getpid);
  BIND("unlink", _unlink);
  BIND("isatty", _isatty);
  BIND("getopt_long_only", guest_getopt);
  BIND("mmap", map_memory);
  BIND("munmap", unmap_memory);
  BIND("sbrk", program_break);
  BIND("getpagesize", pagesize);
  BIND("sysconf", system_conf);
  BIND("gettimeofday", time_of_day);
  BIND("getrusage", usage);
  BIND("times", process_times);
  BIND("getuid", user_id);
  BIND("getgid", user_id);
  BIND("strsignal", signal_string);
  BIND("sleep", sleep_seconds);
  BIND("__sigsetjmp", save_jump);
  BIND("longjmp", restore_jump);
  BIND("mktemp", temporary_name);
  BIND("chmod", change_mode);
  BIND("umask", mask_mode);
  /* Binding host functions explicitly keeps their calling convention cdecl. */
  BIND("malloc", malloc);
  BIND("calloc", calloc);
  BIND("realloc", realloc);
  BIND("free", free);
  BIND("memcpy", memcpy);
  BIND("memmove", memmove);
  BIND("memset", memset);
  BIND("memchr", memchr);
  BIND("strcpy", strcpy);
  BIND("strncpy", strncpy);
  BIND("strcat", strcat);
  BIND("strchr", strchr);
  BIND("strrchr", strrchr);
  BIND("strcmp", strcmp);
  BIND("strncmp", strncmp);
  BIND("strstr", strstr);
  BIND("strcspn", strcspn);
  BIND("qsort", qsort);
  BIND("bsearch", bsearch);
  BIND("getenv", getenv);
  BIND("putenv", putenv);
  BIND("strerror", strerror);
  BIND("perror", perror);
  BIND("printf", printf);
  BIND("sprintf", sprintf);
  BIND("vsprintf", vsprintf);
  BIND("exit", exit);
  BIND("abort", abort);
  BIND("signal", signal);
  BIND("time", _time32);
  BIND("localtime", _localtime32);
  BIND("utime", _utime32);
  BIND("setlocale", setlocale);
  return NULL;
#undef BIND
}

int main(int argc, char **argv, char **envp) {
  char payload[MAX_PATH * 4];
  if (!GetModuleFileNameA(NULL, payload, sizeof(payload)))
    return 2;
  size_t n = strlen(payload);
  if (n < 4 || stricmp(payload + n - 4, ".exe"))
    return 2;
  payload[n - 4] = 0;
  for (char *p = payload; *p; p++)
    if (*p == '\\')
      *p = '/';
  argv[0] = payload;
  unsigned lo = ~0u, hi = 0;
  for (unsigned i = 0; i < sizeof(segments) / sizeof(*segments); i++) {
    const struct segment *s = segments + i;
    if (s->address < lo)
      lo = s->address;
    if (s->address + s->memory > hi)
      hi = s->address + s->memory;
  }
  lo &= ~65535u;
  hi = (hi + 65535u) & ~65535u;
  void *image = VirtualAlloc((void *)lo, hi - lo, MEM_RESERVE | MEM_COMMIT,
                             PAGE_EXECUTE_READWRITE);
  if (image != (void *)lo) {
    fprintf(stderr, "ee-elf-host: cannot reserve original ELF address range\n");
    return 2;
  }
  for (unsigned i = 0; i < sizeof(segments) / sizeof(*segments); i++) {
    const struct segment *s = segments + i;
    if (s->offset + s->size > (unsigned)(payload_end - payload_start)) {
      fprintf(stderr, "ee-elf-host: truncated embedded ELF\n");
      return 2;
    }
    memcpy((void *)s->address, payload_start + s->offset, s->size);
  }
  guest_environ = envp;
  init_ctype();
  in_file.flags = out_file.flags = err_file.flags = 0xfbad0000;
  in_file.host = stdin;
  out_file.host = stdout;
  err_file.host = stderr;
  _setmode(_fileno(stdin), _O_BINARY);
  _setmode(_fileno(stdout), _O_BINARY);
  for (unsigned i = 0; i < sizeof(relocations) / sizeof(*relocations); i++) {
    const struct relocation *r = relocations + i;
    if (r->kind == 5 && !strcmp(r->name, "optarg"))
      optarg_copy = (char **)r->address;
    void *p = (r->kind != 5 && r->local) ? (void *)r->local
                                         : resolve(r->name, r->kind == 5);
    if (r->kind == 5)
      memcpy((void *)r->address, p, r->size);
    else
      *(void **)r->address = p ? p : (void *)r->missing;
  }
  if (pexecute_address)
    detour(pexecute_address, execute_child);
  if (pwait_address)
    detour(pwait_address, wait_child);
  /* x86 has coherent instruction/data caches. Flush when the host exposes
   * the Windows API; minimal development runners may omit this export. */
  typedef BOOL(WINAPI * flush_fn)(HANDLE, LPCVOID, SIZE_T);
  flush_fn flush = (flush_fn)GetProcAddress(GetModuleHandleA("kernel32.dll"),
                                            "FlushInstructionCache");
  if (flush)
    flush(GetCurrentProcess(), image, hi - lo);
  /* Preserve Linux i386's extended x87 precision. Windows CRT startup may
   * select 53-bit precision, which can change host floating-point arithmetic. */
  __asm__ volatile("fninit");
  int result =
      ((int (*)(int, char **, char **))original_main)(argc, argv, envp);
  return result;
}
