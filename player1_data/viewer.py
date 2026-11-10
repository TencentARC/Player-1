"""A local, read-only Viewer for final datasets through the shared Dataset reader."""

from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from player1.datasets.dataset import Dataset

PAGE = """<!doctype html><html lang="en"><meta charset="utf-8">
<title>Player-1 Data</title><style>
body{font:16px system-ui;margin:24px;background:#f6f7f9;color:#19232e}
header{display:flex;gap:12px;align-items:center;flex-wrap:wrap;margin-bottom:20px}
select{max-width:65vw}button,select,input{padding:8px;font:inherit}main{display:grid;grid-template-columns:3fr 2fr;gap:20px}
img{width:100%;background:#14171a}pre{white-space:pre-wrap;overflow-wrap:anywhere;background:white;padding:16px;border-radius:8px}
#error{color:#a11}h2{font-size:16px}@media(max-width:800px){main{grid-template-columns:1fr}}
</style><header><strong>Player-1 Data</strong><select id="trajectory"></select>
<button id="previous">Previous</button><label>Turn <input id="turn" type="number" min="0" value="0" style="width:70px"></label>
<button id="next">Next</button><span id="count"></span></header><p id="error"></p>
<main><section><img id="frame" alt="Current recorded observation"></section><section>
<h2>Task and game instructions</h2><pre id="task"></pre><h2>Reasoning</h2><pre id="reasoning"></pre>
<h2>Recorded action</h2><pre id="action"></pre></section></main><script>
const select=document.querySelector('#trajectory'), turn=document.querySelector('#turn');let rows=[];
async function show(){try{const id=select.value, item=rows.find(r=>r.id===id);if(!item)return;
turn.max=item.turns-1;turn.value=Math.max(0,Math.min(Number(turn.value)||0,item.turns-1));
const query=new URLSearchParams({trajectory:id,turn:turn.value});const response=await fetch('/api/turn?'+query);
const data=await response.json();if(!response.ok)throw Error(data.error);
document.querySelector('#frame').src='/image?'+query;
for(const key of ['task','reasoning','action'])document.querySelector('#'+key).textContent=data[key];
document.querySelector('#count').textContent=`${Number(turn.value)+1} / ${item.turns}`;document.querySelector('#error').textContent='';
}catch(error){document.querySelector('#error').textContent=error.message}}
select.onchange=()=>{turn.value=0;show()};turn.onchange=show;
document.querySelector('#previous').onclick=()=>{turn.value=Number(turn.value)-1;show()};
document.querySelector('#next').onclick=()=>{turn.value=Number(turn.value)+1;show()};
fetch('/api/trajectories').then(r=>r.json()).then(data=>{rows=data;for(const row of rows)
select.add(new Option(`${row.source} · ${row.id} · ${row.turns} turns`,row.id));show()}).catch(e=>document.querySelector('#error').textContent=e.message);
</script></html>"""


def make_server(root: Path, *, port=8765):
    root = Path(root).resolve(strict=True)
    datasets = Dataset.open_splits(root)
    trajectories = {}
    for split, data in datasets.items():
        for ordinal, group in enumerate(data.groups):
            offset = data.offsets[ordinal]
            key = f"{split}-{ordinal}"
            trajectories[key] = {
                "id": key,
                "turns": group["rows"],
                "source": group["source"]["adapter_id"],
                "split": split,
                "offset": offset,
            }

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def send(self, payload, status=200, kind="application/json"):
            self.send_response(status)
            self.send_header("Content-Type", kind)
            self.send_header("Content-Length", str(len(payload)))
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            self.wfile.write(payload)

        def do_GET(self):
            try:
                url = urlsplit(self.path)
                if url.path == "/":
                    self.send(PAGE.encode(), kind="text/html; charset=utf-8")
                    return
                if url.path == "/api/trajectories":
                    self.send(
                        json.dumps(
                            [
                                {k: v for k, v in row.items() if k not in {"split", "offset"}}
                                for row in trajectories.values()
                            ]
                        ).encode()
                    )
                    return
                if url.path not in {"/api/turn", "/image"}:
                    self.send(b'{"error":"not found"}', 404)
                    return
                query = parse_qs(url.query)
                selected = trajectories[query["trajectory"][0]]
                turn = int(query["turn"][0])
                if not 0 <= turn < selected["turns"]:
                    raise ValueError("Turn is outside its trajectory")
                data = datasets[selected["split"]]
                row = data.stored_row(selected["offset"] + turn)
                if url.path == "/image":
                    payload = data.images.read(row["images"][0])
                    self.send(payload, kind="image/jpeg")
                else:
                    target = row["messages"][-1]["content"]
                    reasoning = target[len("<think>\n") :].split("\n</think>\n\n", 1)[0]
                    self.send(
                        json.dumps(
                            {
                                "task": row["messages"][1]["content"],
                                "reasoning": reasoning,
                                "action": row["canonical_action"],
                            },
                            ensure_ascii=False,
                        ).encode()
                    )
            except (ValueError, KeyError, IndexError, OSError) as error:
                self.send(json.dumps({"error": str(error)}).encode(), 400)

    server = HTTPServer(("127.0.0.1", port), Handler)
    server.datasets = datasets
    return server


def serve(root: Path, *, port=8765):
    server = make_server(root, port=port)
    print(f"http://127.0.0.1:{server.server_port}", flush=True)
    try:
        server.serve_forever()
    finally:
        server.server_close()
        for data in server.datasets.values():
            data.close()
