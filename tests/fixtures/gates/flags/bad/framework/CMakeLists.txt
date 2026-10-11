# Every way the page can fall behind the block: a flag it does not write
# (-fcf-protection, -Wl,-z,now), a value of a flag it does not write
# (_FORTIFY_SOURCE=2, float-cast-overflow in -fsanitize=), a flag no literal
# spells (-pie, keyed on RMP_RELEASE_PIE), and an option it never names.
cmake_minimum_required(VERSION 3.30)
project(fixture C CXX)

# BEGIN flags documented on rmp-docs framework/security.html
option(RMP_RELEASE_PIE "Link a release position-independent" ON)
option(RMP_RELEASE_SOMETHING_NEW "A switch nobody wrote a paragraph for" OFF)
list(APPEND RMP_RELEASE_C_FLAGS -fstack-protector-strong -fcf-protection)
if(RMP_HAS_DYNAMIC_OBJECT_SIZE)
  set(_level 3)
else()
  set(_level 2)
endif()
list(APPEND RMP_RELEASE_C_FLAGS -D_FORTIFY_SOURCE=${_level})
foreach(_flag -Wl,-z,relro -Wl,-z,now)
  list(APPEND RMP_RELEASE_LINK_FLAGS ${_flag})
endforeach()
set(_list ${names})
list(APPEND _list float-cast-overflow)
list(JOIN _list "," _joined)
set(RMP_SANITIZE_COMPILE_FLAGS -fsanitize=${_joined})
set(RMP_SANITIZE_LINK_FLAGS "-fsanitize-ignorelist=${SOMEWHERE}")
# END flags documented on rmp-docs framework/security.html
