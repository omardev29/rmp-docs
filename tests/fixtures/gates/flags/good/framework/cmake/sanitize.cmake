# The debug checks, in the shape the framework writes them.
set(RMP_SANITIZE_IGNORELIST "${CMAKE_CURRENT_LIST_DIR}/sanitize_ignore.txt")

# BEGIN flags documented on rmp-docs framework/security.html
function(_rmp_sanitize_flags names out_compile out_link)
  if(MSVC)
    set(_compile /fsanitize=address)
    set(_link /INCREMENTAL:NO)
  elseif(CMAKE_CXX_COMPILER_ID STREQUAL "GNU")
    set(_list ${names})
    list(APPEND _list float-cast-overflow)
    list(JOIN _list "," _joined)
    set(_compile -fsanitize=${_joined} -fno-omit-frame-pointer)
  else()
    list(JOIN names "," _joined)
    set(_compile -fsanitize=${_joined} "-fsanitize-ignorelist=${RMP_SANITIZE_IGNORELIST}")
  endif()
  set(${out_compile} "${_compile}" PARENT_SCOPE)
endfunction()

function(rmp_apply_debug_checks target)
  target_compile_definitions(${target} PRIVATE
    $<$<COMPILE_LANGUAGE:CXX>:_LIBCPP_HARDENING_MODE=_LIBCPP_HARDENING_MODE_EXTENSIVE>)
  target_compile_options(${target} PRIVATE $<$<COMPILE_LANGUAGE:C>:-ftrivial-auto-var-init=pattern>)
  target_compile_definitions(${target} PRIVATE RMP_SANITIZE=1)
endfunction()
# END flags documented on rmp-docs framework/security.html
