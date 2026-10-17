#pragma once
// FCI: the subset of Xbox XBE Recomp's kernel/memory.h the vendored code uses, implemented on
// this runtime in fci_xbr_glue.cpp (see ../README.md).
#include <cstdint>

namespace mem {

constexpr uint32_t kPage = 0x1000;
constexpr uint32_t kContiguousBase = 0x80000000;  // guest VA = kContiguousBase | physical

uint32_t AllocContiguous(uint32_t size, uint32_t lowest, uint32_t highest, uint32_t align);
void FreeContiguous(uint32_t va);
uint32_t AllocSystem(uint32_t size, uint32_t align = 16);
void FreeSystem(uint32_t va);

// physical <-> guest virtual, in this runtime's convention (fci_nv2a.c): main RAM
// physical addresses carry 0x08000000, the contiguous window is 0x80000000 | physical
uint32_t PhysicalFromVirtual(uint32_t va);
uint32_t VirtualFromPhysical(uint32_t pa);

}  // namespace mem
