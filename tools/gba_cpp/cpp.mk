
# Build only the restored C++ frontend and the original agbcc Thumb backend.
CPP_SRCS = call decl errfn expr pt sig typeck2 class decl2 error lex parse ptree rtti spew typeck cvt except friend init method search semantics tree xref repo
CPP_OBJS = $(addprefix cp/,$(addsuffix .o,$(CPP_SRCS)))
CPP_BACKEND = $(filter-out c-parse.o c-lex.o c-decl.o c-typeck.o c-convert.o c-aux-info.o c-iterate.o c-common.o,$(OBJS))
CPP_HELPERS = hash.o c-pragma.o cpp-glue.o cpp-common.o
CPP_INCLUDES = -Icp -I. -I@UPSTREAM@/include -I@UPSTREAM@/gcc
CPP_HEADERS = $(wildcard *.h cp/*.h)
cpp: CFLAGS = $(BASE_CFLAGS)
cpp: $(CPP_OBJS) $(CPP_BACKEND) $(CPP_HELPERS)
	$(CC) $(CFLAGS) -o agbcc-cpp $(CPP_OBJS) $(CPP_BACKEND) $(CPP_HELPERS) $(RTL_OBJS) $(PRINT_OBJS) $(RTLANAL_OBJS)
cp/%.o: cp/%.c $(GENERATED) $(CPP_HEADERS)
	$(CC) $(CFLAGS) -fgnu89-inline -include cpp-port.h $(CPP_INCLUDES) -c $< -o $@
$(CPP_HELPERS): %.o: %.c $(CPP_HEADERS)
	$(CC) $(CFLAGS) -fgnu89-inline -include cpp-port.h $(CPP_INCLUDES) -c $< -o $@
