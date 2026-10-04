void pop() {
    TraceLog(LOG_WARNING, "SCENE: pop() with only one scene on the stack; "
             "call rmp::app::quit() to leave");
    TraceLog(LOG_INFO, "AUDIO: %d voices", 8);
}
void empty() { TraceLog(LOG_WARNING, "SCENE: nothing to pop — the stack is empty"); }
void dash() { TraceLog(LOG_WARNING, "SCENE: a dash — written as itself"); }
void probe() { TraceLog(LOG_WARNING, "AUDIO: no sound called \"%s\" in resources/ (looked for %s)", a, b); }
