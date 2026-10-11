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

// ---------------------------------------------------------------------------
// The pointer. Mouse and finger are the same pointer, which is what lets the
// same code work on every target.
// ---------------------------------------------------------------------------
void g();

} // namespace rmp
