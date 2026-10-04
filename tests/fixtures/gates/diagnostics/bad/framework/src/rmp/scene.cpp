void pop() {
    TraceLog(LOG_WARNING, "SCENE: pop() with only one scene on the stack; "
             "call rmp::app::quit() to leave");
    TraceLog(LOG_INFO, "AUDIO: %d voices", 8);
}
