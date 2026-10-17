/* Original-disc launch routing and Windows argv quoting; no shell execution. */
#include "fci_launch.h"
#include <string.h>
#include <ctype.h>

static int equal(const char *a, const char *b)
{
    while (*a && *b && tolower((unsigned char)*a) == tolower((unsigned char)*b)) {
        a++;
        b++;
    }
    return !*a && !*b;
}
const char *fci_launch_target(const char *path)
{
    const char *prefix = "\\Device\\CdRom0";
    size_t n = strlen(prefix);
    if (strlen(path) <= n)
        return NULL;
    for (size_t i = 0; i < n; i++)
        if (tolower((unsigned char)path[i]) != tolower((unsigned char)prefix[i]))
            return NULL;
    if (path[n] != ';' && path[n] != '\\')
        return NULL;
    path += n + 1;
    if (equal(path, "default.xbe"))
        return "default.xbe";
    if (equal(path, "ige.xbe"))
        return "ige.xbe";
    return NULL;
}
static int put(char *out, size_t cap, size_t *n, char c)
{
    if (*n + 1 >= cap)
        return 0;
    out[(*n)++] = c;
    out[*n] = 0;
    return 1;
}
int fci_quote_arg(char *out, size_t cap, size_t *n, const char *arg)
{
    if (*n && !put(out, cap, n, ' '))
        return 0;
    if (!put(out, cap, n, '"'))
        return 0;
    for (;;) {
        size_t slashes = 0;
        while (*arg == '\\') {
            slashes++;
            arg++;
        }
        size_t count = (*arg == '"' || !*arg) ? slashes * 2 : slashes;
        while (count--)
            if (!put(out, cap, n, '\\'))
                return 0;
        if (!*arg)
            break;
        if (*arg == '"' && !put(out, cap, n, '\\'))
            return 0;
        if (!put(out, cap, n, *arg++))
            return 0;
    }
    return put(out, cap, n, '"');
}
