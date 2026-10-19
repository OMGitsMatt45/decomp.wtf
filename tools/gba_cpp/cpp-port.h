#define IN_GCC 1
#define HOST_PTR_PRINTF "%p"
#include "cpp-gansidecl.h"

#define GCCBUGURL "https://github.com/OMGitsMatt45/decomp.wtf/issues"
#define DEFAULT_INIT_PRIORITY 65535

#define BYTES_BIG_ENDIAN 0

#define HOST_BITS_PER_LONG (__SIZEOF_LONG__ * 8)

#define VARRAY_SIZE(VA) ((VA)->num_elements)

#include <unistd.h>
#ifdef _WIN32
#define bcopy(src, dst, n) memmove((dst), (src), (n))
#define bzero(dst, n) memset((dst), 0, (n))
#define bcmp(a, b, n) memcmp((a), (b), (n))
#endif
#define MAX_INIT_PRIORITY 65535
#define MAX_RESERVED_INIT_PRIORITY 100
