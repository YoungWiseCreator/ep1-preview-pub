#!/usr/bin/env python3
"""ep1-preview — minimal streaming proxy: serves ONE R2 object (Episode 1
hand-sketch v2 master) through this domain with full HTTP Range support so
phone browsers can play/seek it. Credentials come from env vars only."""
import hashlib
import hmac
import os
import datetime
import urllib.parse
import urllib.request
import urllib.error
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

AK = os.environ["R2_ACCESS_KEY"]
SK = os.environ["R2_SECRET_KEY"]
ACCT = os.environ["CF_ACCOUNT_ID"]
HOST = f"{ACCT}.r2.cloudflarestorage.com"
BUCKET = "repo-vault"
KEY = "previews/2026-11-21master_ep01_hs-v2.mp4"
SIZE = 541583373
PATH = "/" + BUCKET + "/" + "/".join(
    urllib.parse.quote(s, safe="") for s in KEY.split("/"))
URL = f"https://{HOST}{PATH}"


def signed_headers(method):
    now = datetime.datetime.now(datetime.timezone.utc)
    amzdate = now.strftime("%Y%m%dT%H%M%SZ")
    date = now.strftime("%Y%m%d")
    scope = f"{date}/auto/s3/aws4_request"
    payload_hash = hashlib.sha256(b"").hexdigest()
    headers = {"host": HOST, "x-amz-content-sha256": payload_hash,
               "x-amz-date": amzdate}
    signed = sorted(headers)
    canon_headers = "".join(f"{k}:{headers[k]}\n" for k in signed)
    canon = (f"{method}\n{PATH}\n\n{canon_headers}\n"
             f"{';'.join(signed)}\n{payload_hash}")
    sts = ("AWS4-HMAC-SHA256\n" + amzdate + "\n" + scope + "\n" +
           hashlib.sha256(canon.encode()).hexdigest())

    def derive(d):
        k = hmac.new(("AWS4" + SK).encode(), d.encode(), hashlib.sha256).digest()
        k = hmac.new(k, b"auto", hashlib.sha256).digest()
        k = hmac.new(k, b"s3", hashlib.sha256).digest()
        return hmac.new(k, b"aws4_request", hashlib.sha256).digest()

    sig = hmac.new(derive(date), sts.encode(), hashlib.sha256).hexdigest()
    auth = (f"AWS4-HMAC-SHA256 Credential={AK}/{scope}, "
            f"SignedHeaders={';'.join(signed)}, Signature={sig}")
    return {"Authorization": auth, "x-amz-date": amzdate,
            "x-amz-content-sha256": payload_hash}


def open_upstream(method, range_header=None):
    hdrs = signed_headers(method)
    if range_header:
        hdrs["Range"] = range_header
    req = urllib.request.Request(URL, headers=hdrs, method=method)
    try:
        return urllib.request.urlopen(req, timeout=120)
    except urllib.error.HTTPError as e:
        return e  # HTTPError is also a readable response object


PAGE = """<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Episode 1 — Hand-Sketch v2</title>
<style>body{margin:0;background:#111;color:#eee;font-family:system-ui,sans-serif;
text-align:center;padding:16px}video{width:100%;max-width:960px;background:#000}
a{color:#8ab4ff}</style></head><body>
<h2>Episode 1 — Hand-Sketch v2 Master</h2>
<video controls playsinline preload="metadata" src="/ep1"></video>
<p>Direct stream: <a href="/ep1">/ep1</a></p>
</body></html>"""


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):
        pass

    def _video_headers(self, status, content_length, content_range=None):
        self.send_response(status)
        self.send_header("Content-Type", "video/mp4")
        self.send_header("Content-Disposition", "inline")
        self.send_header("Accept-Ranges", "bytes")
        if content_range:
            self.send_header("Content-Range", content_range)
        self.send_header("Content-Length", str(content_length))
        self.end_headers()

    def do_HEAD(self):
        if self.path != "/ep1":
            self.send_response(404)
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        resp = open_upstream("HEAD")
        length = resp.headers.get("Content-Length") or str(SIZE)
        self._video_headers(200, int(length))

    def do_GET(self):
        if self.path == "/":
            body = PAGE.encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if self.path != "/ep1":
            body = b"not found"
            self.send_response(404)
            self.send_header("Content-Type", "text/plain")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        range_header = self.headers.get("Range")
        resp = open_upstream("GET", range_header)
        status = resp.getcode()
        if status not in (200, 206):
            body = b"upstream error"
            self.send_response(502)
            self.send_header("Content-Type", "text/plain")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        length = resp.headers.get("Content-Length")
        length = int(length) if length else SIZE
        self._video_headers(status, length, resp.headers.get("Content-Range"))
        try:
            while True:
                chunk = resp.read(262144)
                if not chunk:
                    break
                self.wfile.write(chunk)
        except (BrokenPipeError, ConnectionResetError):
            pass
        finally:
            resp.close()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8080"))
    ThreadingHTTPServer(("0.0.0.0", port), Handler).serve_forever()
