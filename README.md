# Concept Test: Trio Web Monitor

This module is a hack / concept test for Python Trio monitoring in browser.

![Screenshot](https://raw.githubusercontent.com/Tronic/trio-web-monitor/master/triowebmon.png)

Displays in real time all tasks running and where the execution is going, even
if the main application is stuck in a busy loop with no scheduling points, or
blocked in a synchronous system call.

## Bugs

- The code is NOT SECURE (no HTML escaping, no auth, probably crashes). Written in
a day.
- Displays last codeline of nursery blocks that have already completed; should notice
this state and display a message saying that it is waiting for running tasks
even though the body has ended.

## Try it

1. Put somewhere in your program: `nursery.start_soon(triowebmon.Monitor().run)`
2. Open http://localhost:8040/ to find out what your code is doing

## Debugging for Humans

There are a number of attempts at improving Python and Trio debugging via the
use of browser UI. Currently such efforts are quite scattered.

- https://github.com/darrenburns/python-debugger
- https://github.com/syncrypt/trio-inspector
- [Nice tracebacks notebook](https://colab.research.google.com/drive/1Gx16MfcgkqMCuFn8fAgm7YWGytypmtwE)

I would like to see some of the above projects unified, as they have similar
and overlapping goals, and probably none of the developers involved actually
have enough time to maintain these.

One could easily implement killing of any running task by simply clicking ❌ on
it, or control of Trio clock, step-by-step scheduling and what not.

This project is published only in the hopes that someone might pick up on the
idea or benefit of the things I've experimented with (in particular, running a
separate thread for the HTTP server, which doesn't seem to crash even when it
examines the stack frames running in the main thread).

Please contact me (post an issue here) if you wish to take this development
forward in any way.
