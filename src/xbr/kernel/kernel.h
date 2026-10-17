#pragma once
// FCI: the subset of Xbox XBE Recomp's kernel/kernel.h the vendored D3D8/GPU code uses,
// implemented on this runtime in fci_xbr_glue.cpp (see ../README.md).
#include <cstdint>
#include <cstring>
#include <functional>
#include <initializer_list>
#include <memory>
#include <string>
#include <vector>

#include "core/log.h"
#include "cpu/x86_ops.h"
#include "kernel/memory.h"

// FCI: a guest thread's host wait gives the guest CPU up, as a kernel wait does (patches/runtime)
extern "C" int fci_guest_cpu_release(void);
extern "C" void fci_guest_cpu_reacquire(int released);

namespace kernel {

// For the length of a host wait (the GPU, a frame, the vertical blank) on the game's thread, so that
// interrupt-level guest code can preempt it instead of running beside it.
struct GuestCpuFree {
    int released = fci_guest_cpu_release();
    GuestCpuFree() = default;
    GuestCpuFree(const GuestCpuFree&) = delete;
    GuestCpuFree& operator=(const GuestCpuFree&) = delete;
    ~GuestCpuFree() { fci_guest_cpu_reacquire(released); }
};

// A host lock guest threads take: waiting for it gives the guest CPU up, so a holder blocked in a host wait
// (which gave it up) can take the guest CPU back without the two locks deadlocking.
template <class M>
struct GuestLock {
    M& m;
    explicit GuestLock(M& mutex) : m(mutex) {
        if (!m.try_lock()) {
            GuestCpuFree free;
            m.lock();
        }
    }
    GuestLock(const GuestLock&) = delete;
    GuestLock& operator=(const GuestLock&) = delete;
    ~GuestLock() { m.unlock(); }
};

extern uint8_t* g_base;  // host address of guest address 0

inline uint8_t R8(uint32_t va) { return g_base[va]; }
inline void W8(uint32_t va, uint8_t v) { g_base[va] = v; }
inline uint16_t R16(uint32_t va) {
    uint16_t v;
    std::memcpy(&v, g_base + va, 2);
    return v;
}
inline void W16(uint32_t va, uint16_t v) { std::memcpy(g_base + va, &v, 2); }
inline uint32_t R32(uint32_t va) {
    uint32_t v;
    std::memcpy(&v, g_base + va, 4);
    return v;
}
inline void W32(uint32_t va, uint32_t v) { std::memcpy(g_base + va, &v, 4); }
inline uint64_t R64(uint32_t va) {
    uint64_t v;
    std::memcpy(&v, g_base + va, 8);
    return v;
}
inline void W64(uint32_t va, uint64_t v) { std::memcpy(g_base + va, &v, 8); }
inline void* HostPtr(uint32_t va) { return g_base + va; }
template <typename T>
inline T& G(uint32_t va) {
    return *reinterpret_cast<T*>(g_base + va);
}
// a zero terminated string in guest memory
std::string ReadCString(uint32_t va, size_t max = 4096);
// a file of the title's disc (D:\ or a path relative to it), from the game folder this runtime serves
bool ReadGameFile(const std::string& xbox_path, std::vector<uint8_t>& out);

// stdcall argument access for host implementations of guest functions
struct Args {
    X86Context& ctx;
    uint32_t operator[](int i) const { return R32(ctx.esp + 4 + 4 * uint32_t(i)); }
};
inline void Return(X86Context& ctx, uint32_t value, int stack_args) {
    ctx.eax = value;
    ctx.esp += 4 + 4 * uint32_t(stack_args);
}

// runs guest code from the host on the current thread (pushes args right to left, a return address,
// calls the lifted function, restores esp: correct for cdecl and stdcall alike)
uint32_t CallGuest(X86Context& ctx, uint32_t fn, const uint32_t* args, size_t count);
inline uint32_t CallGuest(X86Context& ctx, uint32_t fn, std::initializer_list<uint32_t> args) {
    return CallGuest(ctx, fn, args.begin(), args.size());
}

// a KEVENT in guest memory, set and reset through this runtime's KeSetEvent/KeResetEvent bridges, or an event
// handle the title holds (NtSetEvent)
struct Object {
    uint32_t guest = 0;
    uint32_t handle = 0;
};
using ObjectRef = std::shared_ptr<Object>;
ObjectRef FromPointer(uint32_t guest);
ObjectRef FromHandle(uint32_t handle);
int32_t SetEvent(Object& o);
int32_t ResetEvent(Object& o);

// a host thread that can run guest code (worker stack, TIB; guest calls take the guest CPU)
void StartHostThread(const char* name, std::function<void(X86Context&)> fn);

// D3DDevice_PersistDisplay: not carried across a reboot here
void SetSavedDataAddress(uint32_t surface);
void SavePersistedDisplay(uint32_t common, uint32_t format, uint32_t size, const void* pixels, uint32_t bytes);

}  // namespace kernel
