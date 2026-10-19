
#define DECL_STATIC_CONSTRUCTOR(NODE) (DECL_CHECK(NODE)->decl.static_ctor_flag)
#define DECL_STATIC_DESTRUCTOR(NODE) (DECL_CHECK(NODE)->decl.static_dtor_flag)
#define DECL_COMDAT(NODE) (DECL_CHECK(NODE)->decl.comdat_flag)
extern int flag_signed_char;
extern int wrapup_global_declarations(tree *, int);
extern void check_global_declarations(tree *, int);
extern tree get_file_function_name(int);
extern tree get_file_function_name_long(const char *);
extern int supports_one_only(void);
extern void make_decl_one_only(tree);
extern void maybe_vlist_ctor_wrapper(tree, int);

extern int read_integral_parameter(const char *, const char *, int);
extern void assemble_constructor(char *);
extern void assemble_destructor(char *);
extern long get_run_time(void);

extern int quiet_flag, flag_no_ident, warn_unknown_pragmas;
extern int do_float_handler(void (*)(void *), void *);
