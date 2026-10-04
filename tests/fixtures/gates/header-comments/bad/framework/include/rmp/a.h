#pragma once
// ---------------------------------------------------------------------------
// rmp/a.h -- a fixture header.
// ---------------------------------------------------------------------------

#include <memory>

namespace rmp {

// Read by src/rmp/gone.cpp, since phase 3. There is no <memory> in here.
// Calls rmp::nowhere(), and reads [window] widht.
// Part of this template.
void f();

} // namespace rmp
