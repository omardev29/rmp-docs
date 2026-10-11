// The block is a header of the framework's own, include/rmp/snippet.h, included
// after every public header: where the checks that hold the framework's headers
// look -- clang-tidy's header filter, the query that wants `inline constexpr`,
// and tools/pointer_check.py, which reads that header on its own.
// {{includes}}
// {{given}}
#include <rmp/snippet.h>
