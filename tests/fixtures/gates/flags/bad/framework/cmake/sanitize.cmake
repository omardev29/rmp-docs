# The pair is gone: the gate cannot tell which flags the page has to list.
function(rmp_apply_debug_checks target)
  target_compile_definitions(${target} PRIVATE RMP_SANITIZE=1)
endfunction()
