/* Display options for the kernel's EEPROM and the host renderer: RECOMP_FCI_ASPECT=16:9 is the console's
 * widescreen setting (re/notes/DISPLAY.md); RECOMP_FCI_WINDOW=<w>x<h> the window size. */
#include <stdint.h>
#include <stdlib.h>
#include <string.h>

int fci_aspect_wide(void)
{
    static int wide = -1;
    if (wide < 0) {
        const char *e = getenv("RECOMP_FCI_ASPECT");
        wide = e && (!strcmp(e, "16:9") || !strcmp(e, "16x9") || !strcmp(e, "16/9"));
    }
    return wide;
}

/* EEPROM XC_VIDEO as the dashboard stores it: video flags in the high word (0x00010000 widescreen,
 * 0x00400000 60 Hz) */
uint32_t fci_video_flags(void) { return 0x00400000u | (fci_aspect_wide() ? 0x00010000u : 0u); }

/* RECOMP_FCI_WINDOW: 1 with the size, 0 when unset or unreadable */
int fci_window_size(uint32_t *w, uint32_t *h)
{
    const char *e = getenv("RECOMP_FCI_WINDOW");
    char *x;
    unsigned long a, b;
    if (!e || !*e)
        return 0;
    a = strtoul(e, &x, 10);
    if (*x != 'x' && *x != 'X')
        return 0;
    b = strtoul(x + 1, NULL, 10);
    if (a < 320 || b < 240 || a > 7680 || b > 4320)
        return 0;
    *w = (uint32_t)a;
    *h = (uint32_t)b;
    return 1;
}
