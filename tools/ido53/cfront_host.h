/* Host-only utilities invoked by the unchanged IRIX 5.3 CC driver.
 * Deliberately accept only its observed grep/sort/rm forms. No shell is used.
 * Compiler/frontend/optimizer algorithms remain in the original programs.
 */
#include <dirent.h>
#include <regex.h>

static int classic_remove(const char *path, bool recursive) {
    struct stat st;
    if (lstat(path, &st)) return errno == ENOENT ? 0 : -1;
    if (!S_ISDIR(st.st_mode)) return unlink(path);
    if (!recursive) { errno = EISDIR; return -1; }
    DIR *directory = opendir(path);
    if (!directory) return -1;
    int result = 0;
    struct dirent *entry;
    while ((entry = readdir(directory))) {
        if (!strcmp(entry->d_name, ".") || !strcmp(entry->d_name, "..")) continue;
        char child[PATH_MAX + 1];
        int n = snprintf(child, sizeof child, "%s/%s", path, entry->d_name);
        if (n < 0 || n >= (int)sizeof child || classic_remove(child, true)) { result = -1; break; }
    }
    closedir(directory);
    return result ? result : rmdir(path);
}

static int classic_compare_lines(const void *a, const void *b) {
    return strcmp(*(const char *const *)a, *(const char *const *)b);
}

/* -1 means this is a compiler program rather than one of our utilities. */
static int classic_utility(const char *file, char **argv) {
    const char *name = strrchr(file, '/');
    name = name ? name + 1 : file;
    if (!strcmp(name, "rm")) {
        int i = 1;
        bool recursive = false;
        if (argv[i] && !strcmp(argv[i], "-rf")) { recursive = true; i++; }
        for (; argv[i]; i++) if (classic_remove(argv[i], recursive)) { perror(argv[i]); return 1; }
        return 0;
    }
    if (!strcmp(name, "grep")) {
        int i = 1;
        bool invert = false;
        if (argv[i] && !strcmp(argv[i], "-v")) { invert = true; i++; }
        if (!argv[i] || !argv[i + 1] || argv[i + 2]) return 2;
        regex_t regex;
        if (regcomp(&regex, argv[i], REG_NOSUB)) return 2;
        FILE *input = fopen(argv[i + 1], "rb");
        if (!input) { regfree(&regex); return 2; }
        char *line = NULL;
        size_t capacity = 0;
        bool matched = false;
        while (getline(&line, &capacity, input) != -1) {
            if ((regexec(&regex, line, 0, NULL, 0) == 0) != invert) {
                if (fputs(line, stdout) == EOF) { free(line); fclose(input); regfree(&regex); return 2; }
                matched = true;
            }
        }
        int error = ferror(input);
        free(line); fclose(input); regfree(&regex);
        return error ? 2 : matched ? 0 : 1;
    }
    if (!strcmp(name, "sort")) {
        bool unique = false;
        const char *output = NULL, *input_path = NULL;
        for (int i = 1; argv[i]; i++) {
            if (!strcmp(argv[i], "-u")) unique = true;
            else if (!strncmp(argv[i], "-o", 2) && argv[i][2]) output = argv[i] + 2;
            else if (argv[i][0] != '-' && !input_path) input_path = argv[i];
            else return 2;
        }
        if (!input_path || !output) return 2;
        FILE *input = fopen(input_path, "rb");
        if (!input) return 2;
        char **lines = NULL, *line = NULL;
        size_t count = 0, capacity = 0;
        while (getline(&line, &capacity, input) != -1) {
            char **next = realloc(lines, (count + 1) * sizeof *lines);
            if (!next) { fclose(input); free(line); return 2; }
            lines = next; lines[count++] = line; line = NULL; capacity = 0;
        }
        int result = ferror(input) ? 2 : 0;
        free(line); fclose(input);
        if (count > 1) qsort(lines, count, sizeof *lines, classic_compare_lines);
        FILE *out = result ? NULL : fopen(output, "wb");
        if (!out) result = 2;
        else {
            for (size_t i = 0; i < count; i++) {
                if ((!unique || !i || strcmp(lines[i], lines[i - 1])) && fputs(lines[i], out) == EOF) result = 2;
            }
            if (fclose(out)) result = 2;
        }
        for (size_t i = 0; i < count; i++) free(lines[i]);
        free(lines);
        return result;
    }
    return -1;
}

static void classic_exec_utility(const char *file, char **argv) {
    int result = classic_utility(file, argv);
    if (result >= 0) {
        if (fflush(stdout)) result = 2;
        _exit(result);
    }
}
