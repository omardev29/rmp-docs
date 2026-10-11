# The release hardening, in the shape the framework writes it. A flag outside
# the markers is not the page's business, and neither is one in a comment.
cmake_minimum_required(VERSION 3.30)
project(fixture C CXX)
add_compile_options(-fno-exceptions-outside-the-block)

# BEGIN flags documented on rmp-docs framework/security.html
set(RMP_RELEASE_C_FLAGS "")
set(RMP_RELEASE_LINK_FLAGS "")
option(RMP_RELEASE_PIE "Link a release position-independent (+5.5% somewhere)" ON)
if(PRODUCTION_BUILD AND NOT MSVC)
  # -fcomment-is-not-a-flag: comments are skipped.
  list(APPEND RMP_RELEASE_C_FLAGS -fstack-protector-strong)
  list(APPEND RMP_RELEASE_CXX_FLAGS -D_GLIBCXX_ASSERTIONS
       -D_LIBCPP_HARDENING_MODE=_LIBCPP_HARDENING_MODE_FAST)
  if(RMP_LIBC_IS_GLIBC)
    if(RMP_HAS_DYNAMIC_OBJECT_SIZE)
      set(_level 3)
    else()
      set(_level 2)
    endif()
    list(APPEND RMP_RELEASE_C_FLAGS -U_FORTIFY_SOURCE -D_FORTIFY_SOURCE=${_level})
  endif()
  foreach(_flag -Wl,-z,relro -Wl,-z,now)
    list(APPEND RMP_RELEASE_LINK_FLAGS ${_flag})
  endforeach()
  if(RMP_RELEASE_PIE)
    include(CheckPIESupported)
    check_pie_supported(OUTPUT_VARIABLE _pie_why LANGUAGES C CXX)
  endif()
  message(STATUS "=== a message is not a flag: -fmessage-is-not-a-flag ===")
endif()
# END flags documented on rmp-docs framework/security.html

add_link_options(-Wl,--after-the-block)
