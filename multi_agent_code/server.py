"""
server.py — Flask server that bridges the pipeline to the browser UI.

Endpoints:
  GET  /              → serves ui/index.html
  GET  /output/<file> → serves generated .pptx files for download
  POST /start         → starts the pipeline with {"reference_date": "2025-03-01"}
  POST /respond       → sends user checkpoint input {"text": "..."}
  GET  /stream        → SSE stream of pipeline events
"""

import asyncio
import json
import os
import queue
import threading
from pathlib import Path

from flask import Flask, Response, jsonify, request, send_from_directory
from dotenv import load_dotenv

load_dotenv()

BASE_DIR   = Path(__file__).resolve().parent
UI_DIR     = BASE_DIR / "ui"
OUTPUT_DIR = BASE_DIR.parent / "output"

app = Flask(__name__)

# ── Broadcast state ───────────────────────────────────────────────────────────
# Each SSE connection gets its own queue.
# _push() writes every event to ALL queues simultaneously so two connections
# (e.g. a reconnect or two tabs) both see the complete event stream.

_subscribers: list[queue.Queue] = []
_subscribers_lock = threading.Lock()

_input_event  = threading.Event()
_input_value  = {"text": ""}
_pipeline_running = False


def _push(event_type: str, data: dict):
    """Broadcast an SSE event to every active connection."""
    if event_type == "chart":
        print(f"[server] emitting chart: {data.get('chart_type')} — {data.get('title')}")
    payload = {"type": event_type, "data": data}
    with _subscribers_lock:
        for q in list(_subscribers):
            q.put(payload)


def _wait_for_input():
    """Called by the pipeline when it needs user input (checkpoint)."""
    _input_event.clear()
    _input_event.wait()
    return _input_value["text"]


# ── Routes ────────────────────────────────────────────────────────────────────

@app.route("/")
def index():
    return send_from_directory(UI_DIR.resolve(), "index.html")


@app.route("/output/<path:filename>")
def download(filename):
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    return send_from_directory(str(OUTPUT_DIR), filename, as_attachment=True)


@app.route("/start", methods=["POST"])
def start():
    global _pipeline_running
    if _pipeline_running:
        return jsonify({"error": "Pipeline already running"}), 409

    body = request.get_json(force=True)
    reference_date = body.get("reference_date", "").strip()

    import re
    if not re.fullmatch(r"\d{4}-(0[1-9]|1[0-2])-01", reference_date):
        return jsonify({"error": "Invalid date. Use YYYY-MM-01 format."}), 400

    _pipeline_running = True

    def run_pipeline():
        global _pipeline_running
        try:
            # Import here so tools.init() is called fresh each run
            from pipeline import run
            asyncio.run(run(_push, _wait_for_input, reference_date=reference_date))
        except Exception as e:
            _push("error", {"text": str(e)})
        finally:
            _pipeline_running = False
            _push("pipeline_complete", {})

    thread = threading.Thread(target=run_pipeline, daemon=True)
    thread.start()

    return jsonify({"status": "started"})


@app.route("/respond", methods=["POST"])
def respond():
    body = request.get_json(force=True)
    _input_value["text"] = body.get("text", "").strip()
    _input_event.set()
    return jsonify({"status": "ok"})


@app.route("/stream")
def stream():
    # Each connection gets its own queue registered in _subscribers
    my_queue: queue.Queue = queue.Queue()
    with _subscribers_lock:
        _subscribers.append(my_queue)

    def generate():
        try:
            while True:
                try:
                    event = my_queue.get(timeout=30)
                    yield f"data: {json.dumps(event)}\n\n"
                except queue.Empty:
                    yield ": heartbeat\n\n"
        finally:
            with _subscribers_lock:
                if my_queue in _subscribers:
                    _subscribers.remove(my_queue)

    return Response(generate(), mimetype="text/event-stream",
                    headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    UI_DIR.mkdir(exist_ok=True)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    port = int(os.environ.get("PORT", 8080))
    print(f"\n  Analytics UI → http://localhost:{port}\n")
    app.run(debug=False, threaded=True, port=port)