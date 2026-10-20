#ifndef __cplusplus
#error C++ frontend required
#endif

typedef unsigned int u32;
typedef unsigned long long u64;
extern int callback(int);
extern volatile int global_value;

int ex_add(int a,int b) { return a+b; }
int ex_mix(int a,int b) { return (a*7)^(b+17); }
int ex_abs(int a) { return a<0?-a:a; }
int ex_clamp(int a,int lo,int hi) { return a<lo?lo:(a>hi?hi:a); }
int ex_call(int a) { return callback(a)+global_value; }
int ex_loop(const int *p,int n) { int v=0; for(int i=0;i<n;++i) v+=p[i]; return v; }
u32 ex_bits(u32 a,u32 b) { return ((a<<5)|(a>>27))^(b&0xabcdef01u); }
u64 ex_wide(u64 a,u64 b) { return (a<<19)+(b>>7); }
int ex_div(int a,int b) { return a/b; }
int ex_mod(int a,int b) { return a%b; }
float ex_fadd(float a,float b) { return a+b; }
float ex_fmul(float a,float b) { return a*b; }
float ex_fdiv(float a,float b) { return a/b; }
float ex_fconst(float a) { return a*2.5f+1.25f; }
float ex_fneg(float a) { return -a; }
int ex_ftoi(float a) { return (int)a; }
float ex_itof(int a) { return (float)a; }
int ex_fcompare(float a,float b) { return a<b; }
const char *ex_string() { return "EE reconstruction"; }
int ex_table(int i) { static const int t[]={13,29,47,71}; return t[i&3]; }
int ex_small() { static volatile int v=7; return v++; }
int ex_switch(int x) { switch(x) {case 0:return 5;case 1:return 17;case 2:return 23;case 3:return 59;default:return -1;} }
struct Pair { int a; int b; };
int ex_pair(const Pair &p) { return p.a+p.b; }
Pair ex_return_pair(int a,int b) { Pair p={a,b}; return p; }
void ex_copy(Pair *out,const Pair *in) { *out=*in; }
template<class T> T twice(T x) { return x+x; }
int ex_template(int a) { return twice(a)+3; }
class Cell { int n; public: Cell(int x):n(x) {} int get() const { return n; } };
int ex_class(int a) { Cell c(a); return c.get()+3; }
extern "C++" int ex_overload(int a) { return a+11; }
extern "C++" int ex_overload(int *a) { return *a+13; }
