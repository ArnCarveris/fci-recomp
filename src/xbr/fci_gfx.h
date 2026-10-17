#pragma once
// Graphics options (RECOMP_FCI_XBR_*) from the arguments or fci.ini. fci_gfx_set changes one while the game
// runs and bumps the generation, so a reader that cached a value reads it again.
#include <cstdint>
#include <string>

namespace fci_gfx {
uint32_t Generation();
std::string Value(const char* name);   // empty when unset
float Number(const char* name, float fallback);
}   // namespace fci_gfx

extern "C" int fci_gfx_set(const char* key_value);   // "RECOMP_...=value"; 0 when refused
