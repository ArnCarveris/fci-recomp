#pragma once
// FCI: replaces upstream cpu/x86_ops.h. The lifted code keeps guest registers in thread-local globals, so
// X86_FUNC defines xbr_sub_X() to copy them into an X86Context, run the upstream body and copy them back.
#include <cstdint>

#include "cpu/x86_context.h"

extern "C" void xbr_ctx_load(X86Context& ctx);         // globals -> ctx
extern "C" void xbr_ctx_store(const X86Context& ctx);  // ctx -> globals
uint8_t* xbr_base();
[[noreturn]] void x86_trap(X86Context& ctx, uint32_t va, const char* why);

#define X86_FUNC(name)                                                      \
    static void name##_xbr(X86Context& __restrict ctx, uint8_t* base);     \
    extern "C" void xbr_##name(void) {                                      \
        X86Context ctx_{};                                                  \
        xbr_ctx_load(ctx_);                                                 \
        name##_xbr(ctx_, xbr_base());                                       \
        xbr_ctx_store(ctx_);                                                \
    }                                                                       \
    static void name##_xbr(X86Context& __restrict ctx, uint8_t* base)

// FCI: the lifted body of a wrapped function (HLE_WRAP), renamed by tools/compile.py to
// `xbr_orig_sub_X_c(void)`; called with the context written back first.
#define X86_EXTERN_FUNC(name)                                               \
    extern "C" void name##_c(void);                                         \
    static inline void name(X86Context& ctx, uint8_t*) {                    \
        xbr_ctx_store(ctx);                                                 \
        name##_c();                                                         \
        xbr_ctx_load(ctx);                                                  \
    }
