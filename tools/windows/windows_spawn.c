/* Windows CRT argument quoting. Host compatibility only; no compiler target changes. */
#include <process.h>
#include <stdlib.h>
#include <string.h>
#include <errno.h>
static int spawn_quoted(int search, int mode, const char *program, char **argv) {
  int n, i, result; char **quoted;
  for (n=0; argv[n]; ++n) {}
  quoted = (char **) calloc(n+1, sizeof(char *));
  if (!quoted) { errno=ENOMEM; return -1; }
  for (i=0; i<n; ++i) {
    const char *src=argv[i]; char *dst;
    quoted[i]=(char *)malloc(2*strlen(src)+3);
    if (!quoted[i]) { result=-1; errno=ENOMEM; goto done; }
    dst=quoted[i]; *dst++='"';
    while (*src) {
      int slashes=0;
      while (*src=='\\') { ++slashes; ++src; }
      if (*src=='"' || !*src) { slashes*=2; }
      while (slashes--) *dst++='\\';
      if (!*src) break;
      if (*src=='"') *dst++='\\';
      *dst++=*src++;
    }
    *dst++='"'; *dst=0;
  }
  result=(int)(search ? _spawnvp(mode,program,(const char *const *)quoted) : _spawnv(mode,program,(const char *const *)quoted));
done:
  for (i=0;i<n;++i) free(quoted[i]); free(quoted); return result;
}
int windows_spawnv(int mode,const char *program,char **argv){return spawn_quoted(0,mode,program,argv);}
int windows_spawnvp(int mode,const char *program,char **argv){return spawn_quoted(1,mode,program,argv);}
