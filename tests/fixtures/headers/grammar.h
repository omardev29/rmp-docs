#pragma once
// ---------------------------------------------------------------------------
// rmp/grammar.h -- every shape the reader has to understand.
//
// The file block: this text.
// ---------------------------------------------------------------------------

#include <utility>

#if defined(PLATFORM_WEB)
// The entry point, per platform.
#define RMP_ENTRY(X) web_entry(X)
#else
#define RMP_ENTRY(X) desktop_entry(X)
#endif

namespace rmp {

// ---------------------------------------------------------------------------
// A banner directly above a class is the class's doc.
// ---------------------------------------------------------------------------
class Widget {
public:
    Widget() = default;
    ~Widget();
    Widget(const Widget &) = delete;
    Widget &operator=(const Widget &) = delete;
    Widget(Widget &&other) noexcept;

    float size = 1.0f; // in design units
    Vector2 position{ 10, 20 };

    // -----------------------------------------------------------------------
    // Drawing. A banner inside a class opens a group.
    // -----------------------------------------------------------------------
    void draw() const;

    // One doc for a run.
    int width() const;
    int height() const;

    // An overload set, documented once.
    void move(float x, float y);
    void move(Vector2 to);

    template <class T>
        requires(sizeof(T) > 1)
    T &as();

    explicit operator bool() const { return size > 0; }
    bool operator==(const Widget &other) const;
    [[nodiscard]] static Widget &current();

    void detail_tick(float delta);

    virtual void _ready() {}

    // ---- sizes ---------------------------------------------------------
    float margin = 0;

private:
    int _hidden = 0;
};

enum class Mode {
    FAST, // as fast as it goes
    // Slowly, with care.
    SLOW,
    OFF = 4,
};

enum class Flat { A, B, C };

struct Options {
    int count = 3; // how many
    const char *name = "a; b { c }"; // braces and semicolons in a string
};

class Outer {
public:
    class Inner;
};

// The inner class, defined outside.
class Outer::Inner {
public:
    // Its one method.
    void go();
};

namespace detail {
// Not for games.
struct Secret {
    int x;
};
} // namespace detail

// An alias.
using Number = double;

constexpr int LIMIT = 8; // the most there can be

template <class T> T &Widget::as() { return *static_cast<T *>(nullptr); }

} // namespace rmp
