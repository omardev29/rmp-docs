#pragma once
// ---------------------------------------------------------------------------
// rmp/a.h -- a fixture header.
// ---------------------------------------------------------------------------

#include <memory>

namespace rmp {

// Calls rmp::f() itself, and reads [window] width. <memory> is here for
// std::unique_ptr.
void f();

} // namespace rmp
