#ifndef FCI_LAUNCH_H
#define FCI_LAUNCH_H
#include <stddef.h>
/* Only the two independently recompiled disc programs are supported. */
const char *fci_launch_target(const char *guest_path);
int fci_quote_arg(char *out, size_t capacity, size_t *used, const char *arg);
#endif
