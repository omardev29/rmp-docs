#pragma once
// ---------------------------------------------------------------------------
// rmp/a.h -- a fixture.
// ---------------------------------------------------------------------------

namespace rmp {

// A thing.
void f();

namespace behavior {
// Gravity and jumping.
struct Platformer {
    // On the ground this frame?
    bool grounded() const;
    // How fast.
    float speed = 1;
};
} // namespace behavior

} // namespace rmp
