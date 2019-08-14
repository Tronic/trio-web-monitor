import json
import inspect
import time
import threading
from collections import defaultdict
import sys

import trio

class Monitor(trio.abc.Instrument):
    async def run(self):
        rootiter = trio.hazmat.current_root_task().child_nurseries[0].child_tasks
        # Get function run by trio.run instead of Trio internals
        self.root = next(task for task in rootiter if not "run_sync_soon" in task.name)
        self.tasks = defaultdict(dict)
        self.mainthread = threading.get_ident()
        self.monitor_task = trio.hazmat.current_task()
        trio.hazmat.add_instrument(self)
        try:
            await trio.to_thread.run_sync(trio.run, self.runserver, cancellable=True)
        finally:
            self.nursery.cancel_scope.cancel()
            # TODO: join the thread?


    async def runserver(self):
        async with trio.open_nursery() as self.nursery:
            await self.nursery.start(trio.serve_tcp, self.httpserve, 8040)

    async def httpserve(self, stream):
        req = bytearray()
        async for data in stream:
            req += data
            if b"\r\n\r\n" in req: break
        try:
            path = req.split(b" ", 2)[1]
            code, mimetype, body = 200, b"text/plain", b""
            if path == b"/":
                mimetype, body = b"text/html", index_html
            elif path == b"/info.json":
                body = self.get_traceback()
            else:
                code = 404
        except Exception as e:
            code, mimetype, body = 500, b"text/plain", repr(e).encode()
        finally:
            if isinstance(body, dict): mimetype, body = b"application/json", json.dumps(body)
            if isinstance(body, str): body = body.encode()
            await stream.send_all(b"HTTP/1.1 %d\r\ncontent-type: %b;charset=utf-8\r\ncontent-length: %d\r\n\r\n%b" % (code, mimetype, len(body), body))

    def extract_task(self, task):
        code = location = ""
        try:
            # This is likely to fail in many ways
            coro = task.coro
            while coro:
                if hasattr(coro, "gi_frame"):
                    frame = coro.gi_frame
                    coro = coro.gi_yieldfrom
                else:
                    frame = coro.cr_frame
                    coro = coro.cr_await
                if not frame: break
                if code and "/trio/_" in frame.f_code.co_filename: break
                codelines, lineno = inspect.getsourcelines(frame)
                code = codelines[frame.f_lineno - lineno].strip()
                location = f"{frame.f_code.co_filename}:{frame.f_lineno}"
        except Exception as e:
            if (sys.flags.debug): print(f"Monitor bug: {e!r}")
        return dict(
            id=id(task),
            name=task.name or "Unnamed Task",
            location=location,
            code=code,
            times=self.tasks[id(task)],
            child_tasks=[
                self.extract_task(t) for t in task.child_nurseries[0].child_tasks if t is not self.monitor_task
            ] if task.child_nurseries else None
        )

    def extract_stack(self):
        frame = sys._current_frames()[self.mainthread]
        code, lineno = inspect.getsourcelines(frame)
        lineno = frame.f_lineno - lineno
        code = code[lineno - 5 : lineno + 1]
        calls = []
        while frame:
            c = frame.f_code
            if c.co_filename.endswith("/runpy.py"): break  # Omit Python internals
            n = c.co_name
            if n == "<module>": n = c.co_filename.split("/")[-1]
            calls.append(dict(name=n, location=f"{c.co_filename}:{frame.f_lineno}"))
            frame = frame.f_back
        return dict(stack=list(reversed(calls)), code=code)

    def get_traceback(self):
        return dict(
            current_statistics=repr(trio.hazmat.current_statistics()),
            current_time=time.monotonic(),
            current_execution=self.extract_stack(),
            root_task=self.extract_task(self.root),
        )

    def task_scheduled(self, task):
        self.tasks[id(task)]["scheduled"] = time.monotonic()

    def before_task_step(self, task):
        self.tasks[id(task)]["run"] = time.monotonic()
        self.tasks[id(task)]["runtime"] = None


    def after_task_step(self, task):
        times = self.tasks[id(task)]
        if times and "run" in times:
            times["runtime"] = time.monotonic() - times["run"]

index_html = """<!DOCTYPE html>
<title>Trio Web Monitor</title>
<style>
html { font-size: 10px; }
div { white-space: pre-wrap; word-wrap: break-word; }
li { background: #0001; padding: 0.5em; box-shadow: 0 0 0.2em #0008 inset; margin: 0.2em; list-style: none; border-radius: 0.5em; }
li.scheduled { background: blue; }
li.running > div code { background: #ff06; }
li.hung > div code { background: red; }
ul { display: flex; justify-content: space-evenly; flex-wrap: wrap; padding: 0; margin: 0; }
li.no-children { width: 50ch; }
#traceback code:last-child { font-weight: bold; }
</style>
<h1>Trio Web Monitor</h1>
<h2>Overview</h2>
<p id=stats></p>
<h2>Current execution</h2>
<div id=traceback></div>
<h2>Tasks and nurseries</h2>
<ul id=tasks></ul>
<script>
const garbage = new Set()
let info = null

const ensure_element = (parent, tag, id) => {
    let elem = document.getElementById(id)
    if (elem) {
        garbage.delete(elem)
        elem.classList.remove("new")
    } else {
        elem = document.createElement(tag)
        elem.id = id
        elem.classList.add("new")
        parent.appendChild(elem)
    }
    return elem
}

const do_task = (task, elem) => {
    const li = ensure_element(elem, "li", `task-${task.id}`)
    const div = ensure_element(li, "div", `task-${task.id}-status`)
    div.innerHTML = `<b>${task.name}</b> <a href="vscode://file/${task.location}">${task.location}</a><div><code>${task.code}</code></div>`
    if (task.times.runtime) li.className = undefined
    else if (task.times.run) li.className = "running"
    else if (task.times.scheduled) li.className = "scheduled"
    else li.className = undefined
    if (!task.times.runtime && info.current_time - task.times.run > 0.5) li.classList.add("hung")
    if (task.child_tasks && task.child_tasks.length > 0) {
        li.classList.remove("no-children")
        const ul = ensure_element(li, "ul", `children-of-${task.id}`)
        for (const t of task.child_tasks) do_task(t, ul)
    } else {
        li.classList.add("no-children")
    }
}

async function update() {
    info = await fetch("info.json").then(res => res.json())
    const stats = document.getElementById("stats")
    stats.textContent = info.current_statistics
    const ul = document.getElementById("tasks")
    for (const e of ul.querySelectorAll("li, ul")) garbage.add(e)
    do_task(info.root_task, ul)
    for (e of garbage) e.remove()
    const traceback = document.getElementById("traceback")
    html = "<p>"
    for (const f of info.current_execution.stack) {
        html += ` » <a href="vscode://file/${f.location}">${f.name}</a>`
    }
    html += "</p>"
    for (const line of info.current_execution.code) {
        html += `<code>${line}</code>`

    }
    traceback.innerHTML = html
}

setInterval(update, 200)

</script>
""".encode()
