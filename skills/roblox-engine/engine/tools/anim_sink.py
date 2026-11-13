"""Tiny local sink: Studio Luau HttpService:PostAsync('http://127.0.0.1:8765/<name>', json) -> assets/anims/_raw/<name>.json
(avoids the truncated Studio log). Run: python tools/anim_sink.py"""
import http.server, pathlib
OUT = pathlib.Path(__file__).resolve().parent.parent / 'assets' / 'anims' / '_raw'
class H(http.server.BaseHTTPRequestHandler):
    def do_POST(self):
        b = self.rfile.read(int(self.headers['Content-Length']))
        (OUT / (self.path.strip('/') + '.json')).write_bytes(b)
        self.send_response(200); self.end_headers(); self.wfile.write(b'ok')
    def log_message(self, *a): pass
http.server.HTTPServer(('127.0.0.1', 8765), H).serve_forever()
