/* C++ language interfaces restored from GCC 2.95.3 (toplev.c, tree.c,
   libiberty/splay-tree.c) for the agbcc Thumb backend.
   Copyright (C) 1987-1999 Free Software Foundation, Inc.
   GNU GPL version 2 or later; see the packaged gcc/COPYING. */
#include "cpp-port.h"
#include "config.h"
#include "system.h"
#include "tree.h"
#include "rtl.h"
#include "flags.h"
#include "expr.h"
#include "toplev.h"
#include "output.h"
#include "dwarf2out.h"
extern int flag_keep_static_consts;
#include "cp/cp-tree.h"
#define TIMEVAR(var, body) do { body; } while (0)
int flag_signed_char = 0; /* agbcc's plain char is unsigned. */
int
wrapup_global_declarations (vec, len)
     tree *vec;
     int len;
{
  tree decl;
  int i;
  int reconsider;
  int output_something = 0;

  for (i = 0; i < len; i++)
    {
      decl = vec[i];

      /* We're not deferring this any longer.  */
      DECL_DEFER_OUTPUT (decl) = 0;

      if (TREE_CODE (decl) == VAR_DECL && DECL_SIZE (decl) == 0
	  && incomplete_decl_finalize_hook != 0)
	(*incomplete_decl_finalize_hook) (decl);
    }

  /* Now emit any global variables or functions that we have been
     putting off.  We need to loop in case one of the things emitted
     here references another one which comes earlier in the list.  */
  do
    {
      reconsider = 0;
      for (i = 0; i < len; i++)
	{
	  decl = vec[i];

	  if (TREE_ASM_WRITTEN (decl) || DECL_EXTERNAL (decl))
	    continue;

	  /* Don't write out static consts, unless we still need them.

	     We also keep static consts if not optimizing (for debugging),
	     unless the user specified -fno-keep-static-consts.
	     ??? They might be better written into the debug information.
	     This is possible when using DWARF.

	     A language processor that wants static constants to be always
	     written out (even if it is not used) is responsible for
	     calling rest_of_decl_compilation itself.  E.g. the C front-end
	     calls rest_of_decl_compilation from finish_decl.
	     One motivation for this is that is conventional in some
	     environments to write things like:
	     static const char rcsid[] = "... version string ...";
	     intending to force the string to be in the executable.

	     A language processor that would prefer to have unneeded
	     static constants "optimized away" would just defer writing
	     them out until here.  E.g. C++ does this, because static
	     constants are often defined in header files.

	     ??? A tempting alternative (for both C and C++) would be
	     to force a constant to be written if and only if it is
	     defined in a main file, as opposed to an include file.  */

	  if (TREE_CODE (decl) == VAR_DECL && TREE_STATIC (decl)
	      && (! TREE_READONLY (decl)
		  || TREE_PUBLIC (decl)
		  || (!optimize && flag_keep_static_consts)
		  || TREE_SYMBOL_REFERENCED (DECL_ASSEMBLER_NAME (decl))))
	    {
	      reconsider = 1;
	      rest_of_decl_compilation (decl, NULL_PTR, 1, 1);
	    }

	  if (TREE_CODE (decl) == FUNCTION_DECL
	      && DECL_INITIAL (decl) != 0
	      && DECL_SAVED_INSNS (decl) != 0
	      && (flag_keep_inline_functions
		  || (TREE_PUBLIC (decl) && !DECL_COMDAT (decl))
		  || TREE_SYMBOL_REFERENCED (DECL_ASSEMBLER_NAME (decl))))
	    {
	      reconsider = 1;
	      temporary_allocation ();
	      output_inline_function (decl);
	      permanent_allocation (1);
	    }
	}

      if (reconsider)
	output_something = 1;
    }
  while (reconsider);

  return output_something;
}

/* Issue appropriate warnings for the global declarations in VEC (of
   which there are LEN).  Output debugging information for them.  */
void
check_global_declarations (vec, len)
     tree *vec;
     int len;
{
  tree decl;
  int i;

  for (i = 0; i < len; i++)
    {
      decl = vec[i];

      if (TREE_CODE (decl) == VAR_DECL && TREE_STATIC (decl)
	  && ! TREE_ASM_WRITTEN (decl))
	/* Cancel the RTL for this decl so that, if debugging info
	   output for global variables is still to come,
	   this one will be omitted.  */
	DECL_RTL (decl) = NULL;

      /* Warn about any function
	 declared static but not defined.
	 We don't warn about variables,
	 because many programs have static variables
	 that exist only to get some text into the object file.  */
      if (TREE_CODE (decl) == FUNCTION_DECL
	  && (warn_unused
	      || TREE_SYMBOL_REFERENCED (DECL_ASSEMBLER_NAME (decl)))
	  && DECL_INITIAL (decl) == 0
	  && DECL_EXTERNAL (decl)
	  && ! DECL_ARTIFICIAL (decl)
	  && ! TREE_PUBLIC (decl))
	{
	  if (TREE_SYMBOL_REFERENCED (DECL_ASSEMBLER_NAME (decl)))
	    pedwarn_with_decl (decl,
			       "`%s' used but never defined");
	  else
	    warning_with_decl (decl,
			       "`%s' declared `static' but never defined");
	  /* This symbol is effectively an "extern" declaration now.  */
	  TREE_PUBLIC (decl) = 1;
	  assemble_external (decl);
	}

      /* Warn about static fns or vars defined but not used,
	 but not about inline functions or static consts
	 since defining those in header files is normal practice.  */
      if (warn_unused
	  && ((TREE_CODE (decl) == FUNCTION_DECL && ! DECL_INLINE (decl))
	      || (TREE_CODE (decl) == VAR_DECL && ! TREE_READONLY (decl)))
	  && ! DECL_IN_SYSTEM_HEADER (decl)
	  && ! DECL_EXTERNAL (decl)
	  && ! TREE_PUBLIC (decl)
	  && ! TREE_USED (decl)
	  && (TREE_CODE (decl) == FUNCTION_DECL || ! DECL_REGISTER (decl))
	  /* The TREE_USED bit for file-scope decls
	     is kept in the identifier, to handle multiple
	     external decls in different scopes.  */
	  && ! TREE_USED (DECL_NAME (decl)))
	warning_with_decl (decl, "`%s' defined but not used");

#ifdef SDB_DEBUGGING_INFO
      /* The COFF linker can move initialized global vars to the end.
	 And that can screw up the symbol ordering.
	 By putting the symbols in that order to begin with,
	 we avoid a problem.  mcsun!unido!fauern!tumuc!pes@uunet.uu.net.  */
      if (write_symbols == SDB_DEBUG && TREE_CODE (decl) == VAR_DECL
	  && TREE_PUBLIC (decl) && DECL_INITIAL (decl)
	  && ! DECL_EXTERNAL (decl)
	  && DECL_RTL (decl) != 0)
	TIMEVAR (symout_time, sdbout_symbol (decl, 0));

      /* Output COFF information for non-global
	 file-scope initialized variables.  */
      if (write_symbols == SDB_DEBUG
	  && TREE_CODE (decl) == VAR_DECL
	  && DECL_INITIAL (decl)
	  && ! DECL_EXTERNAL (decl)
	  && DECL_RTL (decl) != 0
	  && GET_CODE (DECL_RTL (decl)) == MEM)
	TIMEVAR (symout_time, sdbout_toplevel_data (decl));
#endif /* SDB_DEBUGGING_INFO */
#ifdef DWARF_DEBUGGING_INFO
      /* Output DWARF information for file-scope tentative data object
	 declarations, file-scope (extern) function declarations (which
	 had no corresponding body) and file-scope tagged type declarations
	 and definitions which have not yet been forced out.  */

      if (write_symbols == DWARF_DEBUG
	  && (TREE_CODE (decl) != FUNCTION_DECL || !DECL_INITIAL (decl)))
	TIMEVAR (symout_time, dwarfout_file_scope_decl (decl, 1));
#endif
#ifdef DWARF2_DEBUGGING_INFO
      /* Output DWARF2 information for file-scope tentative data object
	 declarations, file-scope (extern) function declarations (which
	 had no corresponding body) and file-scope tagged type declarations
	 and definitions which have not yet been forced out.  */

      if (write_symbols == DWARF2_DEBUG
	  && (TREE_CODE (decl) != FUNCTION_DECL || !DECL_INITIAL (decl)))
	TIMEVAR (symout_time, dwarf2out_decl (decl));
#endif
    }
}

int
read_integral_parameter (p, pname, defval)
     const char *p;
     const char *pname;
     const int  defval;
{
  const char *endp = p;

  while (*endp)
    {
      if (*endp >= '0' && *endp <= '9')
	endp++;
      else
	break;
    }

  if (*endp != 0)
    {
      if (pname != 0)
	error ("Invalid option `%s'", pname);
      return defval;
    }

  return atoi (p);
}



#include "splay-tree.h"
int
splay_tree_compare_ints (k1, k2)
     splay_tree_key k1;
     splay_tree_key k2;
{
  if ((int) k1 < (int) k2)
    return -1;
  else if ((int) k1 > (int) k2)
    return 1;
  else
    return 0;
}

/* Splay-tree comparison function, treating the keys as pointers.  */

int
splay_tree_compare_pointers (k1, k2)
     splay_tree_key k1;
     splay_tree_key k2;
{
  if ((char*) k1 < (char*) k2)
    return -1;
  else if ((char*) k1 > (char*) k2)
    return 1;
  else
    return 0;
}

int supports_one_only(void) { return 1; }
void make_decl_one_only(tree decl) {
    if (TREE_CODE(decl) != VAR_DECL && TREE_CODE(decl) != FUNCTION_DECL) abort();
    TREE_PUBLIC(decl) = 1;
    if (TREE_CODE(decl) == VAR_DECL && (!DECL_INITIAL(decl) || DECL_INITIAL(decl) == error_mark_node))
        DECL_COMMON(decl) = 1;
    else DECL_WEAK(decl) = 1;
}
void assemble_constructor(char *name) {
    fprintf(asm_out_file, "\t.pushsection\t.ctors,\"aw\"\n\t.align\t2\n\t.word\t");
    assemble_name(asm_out_file,name); fputs("\n\t.popsection\n",asm_out_file);
}
void assemble_destructor(char *name) {
    fprintf(asm_out_file, "\t.pushsection\t.dtors,\"aw\"\n\t.align\t2\n\t.word\t");
    assemble_name(asm_out_file,name); fputs("\n\t.popsection\n",asm_out_file);
}

#include <unistd.h>
#ifndef NO_DOLLAR_IN_LABEL
#define FILE_FUNCTION_FORMAT "_GLOBAL_$%s$%s"
#else /* NO_DOLLAR_IN_LABEL */
#ifndef NO_DOT_IN_LABEL
#define FILE_FUNCTION_FORMAT "_GLOBAL_.%s.%s"
#else /* NO_DOT_IN_LABEL */
#define FILE_FUNCTION_FORMAT "_GLOBAL__%s_%s"
#endif	/* NO_DOT_IN_LABEL */
#endif	/* NO_DOLLAR_IN_LABEL */

char * first_global_object_name;
char * weak_global_object_name;

/* Appends 6 random characters to TEMPLATE to (hopefully) avoid name
   clashes in cases where we can't reliably choose a unique name.

   Derived from mkstemp.c in libiberty.  */

static void
append_random_chars (template)
     char *template;
{
  static const char letters[]
    = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789";
  static HOST_WIDE_UINT value;
  HOST_WIDE_UINT v;

#ifdef HAVE_GETTIMEOFDAY
  struct timeval tv;
#endif

  template += strlen (template);

#ifdef HAVE_GETTIMEOFDAY
  /* Get some more or less random data.  */
  gettimeofday (&tv, NULL);
  value += ((HOST_WIDE_UINT) tv.tv_usec << 16) ^ tv.tv_sec ^ getpid ();
#else
  value += getpid ();
#endif

  v = value;

  /* Fill in the random bits.  */
  template[0] = letters[v % 62];
  v /= 62;
  template[1] = letters[v % 62];
  v /= 62;
  template[2] = letters[v % 62];
  v /= 62;
  template[3] = letters[v % 62];
  v /= 62;
  template[4] = letters[v % 62];
  v /= 62;
  template[5] = letters[v % 62];

  template[6] = '\0';
}

/* Generate a name for a function unique to this translation unit.
   TYPE is some string to identify the purpose of this function to the
   linker or collect2.  */

tree
get_file_function_name_long (type)
     const char *type;
{
  char *buf;
  register char *p;

  if (first_global_object_name)
    p = first_global_object_name;
  else
    {
      /* We don't have anything that we know to be unique to this translation
	 unit, so use what we do have and throw in some randomness.  */

      const char *name = weak_global_object_name;
      const char *file = main_input_filename;

      if (! name)
	name = "";
      if (! file)
	file = input_filename;

      p = (char *) alloca (7 + strlen (name) + strlen (file));

      sprintf (p, "%s%s", name, file);
      append_random_chars (p);
    }

  buf = (char *) alloca (sizeof (FILE_FUNCTION_FORMAT) + strlen (p)
			 + strlen (type));

  /* Set up the name of the file-level functions we may need.  */
  /* Use a global object (which is already required to be unique over
     the program) rather than the file name (which imposes extra
     constraints).  -- Raeburn@MIT.EDU, 10 Jan 1990.  */
  sprintf (buf, FILE_FUNCTION_FORMAT, type, p);

  /* Don't need to pull weird characters out of global names.  */
  if (p != first_global_object_name)
    {
      for (p = buf+11; *p; p++)
	if (! ((*p >= '0' && *p <= '9')
#if 0 /* we always want labels, which are valid C++ identifiers (+ `$') */
#ifndef ASM_IDENTIFY_GCC	/* this is required if `.' is invalid -- k. raeburn */
	       || *p == '.'
#endif
#endif
#ifndef NO_DOLLAR_IN_LABEL	/* this for `$'; unlikely, but... -- kr */
	       || *p == '$'
#endif
#ifndef NO_DOT_IN_LABEL		/* this for `.'; unlikely, but...  */
	       || *p == '.'
#endif
	       || (*p >= 'A' && *p <= 'Z')
	       || (*p >= 'a' && *p <= 'z')))
	  *p = '_';
    }

  return get_identifier (buf);
}

/* If KIND=='I', return a suitable global initializer (constructor) name.
   If KIND=='D', return a suitable global clean-up (destructor) name.  */

tree
get_file_function_name (kind)
     int kind;
{
  char p[2];
  p[0] = kind;
  p[1] = 0;

  return get_file_function_name_long (p);
}

#include <setjmp.h>
extern void set_float_handler(jmp_buf);
int quiet_flag = 1;
int flag_no_ident = 0;
extern int lang_decode_option(int,char **);
extern void lang_init(void);
char *decl_name(tree node,int verbosity) { return lang_printable_name(node,verbosity); }
void check_line_directive(void) { lang_init(); }
int c_decode_option(char *arg) { return lang_decode_option(1,&arg); }
int
do_float_handler (fn, data)
  void (*fn) PROTO ((PTR));
  PTR data;
{
  jmp_buf buf;

  if (setjmp (buf))
    {
      /* We got here via longjmp() caused by an exception in function fn() */
      set_float_handler (NULL);
      return 0;
    }

  set_float_handler (buf);
  (*fn)(data);
  set_float_handler (NULL);
  return 1;
}
