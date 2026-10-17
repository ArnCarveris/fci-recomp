/* Port I/O (tools/compile.py turns in/out into these calls). Only port 0x80C0 (MCPX ACPI, written by
 * D3D's hardware init at 0050EA10) is modeled; any other port stops (exit 90). */
#include <stdint.h>
#include <stdio.h>
#include <windows.h>

static uint32_t latch_80c0;
static unsigned writes_80c0;

static void port_stop(const char *dir, uint32_t port, uint32_t value, unsigned size, uint32_t va)
{
    fprintf(stderr, "[FCI] STOP 90 unregistered port %s port=%04X size=%u value=%08X va=%08X\n", dir, port,
            size, value, va);
    fflush(stderr);
    TerminateProcess(GetCurrentProcess(), 90);
}

void fci_port_out(uint32_t port, uint32_t value, unsigned size, uint32_t va)
{
    port &= 0xFFFFu;
    if (port == 0x80C0u && size == 1) {
        latch_80c0 = value & 0xFFu;
        if (writes_80c0++ < 8)
            fprintf(stderr, "  [FCI] port 80C0 <- %02X (va %08X, latched)\n", latch_80c0, va);
        return;
    }
    port_stop("out", port, value, size, va);
}

/* 0x80C0 read by D3D's vblank interrupt (0050DAFD): bit 5 is the interlaced field, alternating at
 * 59.94 Hz of host time; the other bits return the latch */
static uint32_t field_bit(void)
{
    LARGE_INTEGER now, freq;
    QueryPerformanceCounter(&now);
    QueryPerformanceFrequency(&freq);
    return (uint32_t)((now.QuadPart * 5994 / (freq.QuadPart * 100)) & 1) << 5;
}

uint32_t fci_port_in(uint32_t port, unsigned size, uint32_t va)
{
    static unsigned reads_80c0;
    port &= 0xFFFFu;
    if (port == 0x80C0u && size == 1) {
        uint32_t value = (latch_80c0 & ~0x20u) | field_bit();
        if (reads_80c0++ < 4)
            fprintf(stderr, "  [FCI] port 80C0 -> %02X (va %08X, field bit)\n", value, va);
        return value;
    }
    port_stop("in", port, 0, size, va);
    return 0;
}

/* WBINVD: host memory is coherent for every device model here, so only its ordering remains: a full
 * barrier */
void fci_wbinvd(uint32_t va)
{
    static unsigned seen;
    MemoryBarrier();
    if (seen++ < 4)
        fprintf(stderr, "  [FCI] wbinvd at %08X (full barrier)\n", va);
}
