#!/usr/bin/env python3
"""reelforge run helper.

The AI orchestrator (Claude Code / Codex) makes the judgement calls.
This script does the deterministic work: HTTP, files, run state.

    rf.py new <slug> --request "..."          create a run
    rf.py refs <slug> --query "..."           pull Pinterest references
    rf.py routing [genre]                     read the routing table
    rf.py route <slug> --genre <id>           pick the backend that can actually run
    rf.py gen <slug> --prompt-file <path>     generate via Gemini REST
    rf.py adopt <slug> <url|path>             take an image made elsewhere (Higgsfield MCP)
    rf.py set <slug> <dotted.path=json> ...   patch run.json
    rf.py show <slug>                         print run.json
    rf.py index                               rebuild viewer/data.js
"""
from __future__ import annotations

import argparse
import base64
import gzip
import io
import json
import os
import re
import shutil
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from http.cookiejar import CookieJar
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
RUNS = ROOT / "runs"
ROUTING = ROOT / "config" / "routing.yaml"
VIEWER = ROOT / "viewer"

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")


def load_dotenv():
    """Read repo-root .env so keys survive between tool calls and shells.

    Real environment variables win — .env is the fallback, not an override.
    """
    f = ROOT / ".env"
    if not f.exists():
        return
    for line in f.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip().strip("'\""))


load_dotenv()


def die(msg: str, code: int = 1):
    print(f"error: {msg}", file=sys.stderr)
    sys.exit(code)


def now() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def load_routing() -> dict:
    return yaml.safe_load(ROUTING.read_text(encoding="utf-8"))


def run_dir(slug: str) -> Path:
    return RUNS / slug


def load_run(slug: str) -> dict:
    p = run_dir(slug) / "run.json"
    if not p.exists():
        die(f"no such run: {slug}. create it with: rf.py new {slug} --request ...")
    return json.loads(p.read_text(encoding="utf-8"))


def save_run(slug: str, data: dict):
    p = run_dir(slug) / "run.json"
    p.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


# --------------------------------------------------------------------------- #
# Pinterest
# --------------------------------------------------------------------------- #

class Pinterest:
    """Unauthenticated Pinterest search.

    Two things make it work: a cookie bootstrap from the home page, and the
    app version pulled out of that page's __PWS_DATA__ blob. Without the
    matching x-app-version the resource endpoint answers 'Invalid Resource
    Request'.
    """

    HOME = "https://www.pinterest.com/"
    ENDPOINT = "https://www.pinterest.com/resource/BaseSearchResource/get/"

    def __init__(self):
        self.jar = CookieJar()
        self.opener = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(self.jar))
        self.app_version = None
        self.csrf = None

    def _open(self, req, timeout=30) -> bytes:
        with self.opener.open(req, timeout=timeout) as r:
            body = r.read()
        if body[:2] == b"\x1f\x8b":
            body = gzip.decompress(body)
        return body

    def bootstrap(self):
        req = urllib.request.Request(self.HOME, headers={"User-Agent": UA})
        html = self._open(req).decode("utf-8", "replace")
        m = re.search(r'id="__PWS_DATA__"[^>]*>(.*?)</script>', html, re.S)
        if m:
            try:
                self.app_version = json.loads(m.group(1)).get("appVersion")
            except json.JSONDecodeError:
                pass
        if not self.app_version:
            m = re.search(r'"appVersion"\s*:\s*"([^"]+)"', html)
            self.app_version = m.group(1) if m else None
        for c in self.jar:
            if c.name == "csrftoken":
                self.csrf = c.value
        if not (self.app_version and self.csrf):
            die("pinterest bootstrap failed (no appVersion/csrftoken). "
                "site layout may have changed")

    def search(self, query: str, page_size: int = 25) -> list[dict]:
        if not self.app_version:
            self.bootstrap()
        source_url = "/search/pins/?q=" + urllib.parse.quote(query) + "&rs=typed"
        data = {
            "options": {
                "query": query, "scope": "pins", "rs": "typed",
                "bookmarks": [""], "page_size": page_size,
                "redux_normalize_feed": True,
                "auto_correction_disabled": False,
                "filters": None, "corpus": None, "article": None,
                "appliedProductFilters": "---", "applied_unified_filters": None,
                "customized_rerank_type": None, "query_pin_sigs": None,
                "seoDynamicFilters": None, "source_id": None, "top_pin_id": None,
            },
            "context": {},
        }
        url = self.ENDPOINT + "?" + urllib.parse.urlencode({
            "source_url": source_url,
            "data": json.dumps(data, separators=(",", ":")),
            "_": str(int(time.time() * 1000)),
        })
        req = urllib.request.Request(url, headers={
            "User-Agent": UA,
            "accept": "application/json, text/javascript, */*, q=0.01",
            "x-csrftoken": self.csrf,
            "x-app-version": self.app_version,
            "x-pinterest-appstate": "active",
            "x-pinterest-source-url": source_url,
            "x-pinterest-pws-handler": "www/search/[scope].js",
            "x-requested-with": "XMLHttpRequest",
            "referer": "https://www.pinterest.com" + source_url,
        })
        payload = json.loads(self._open(req))
        results = payload.get("resource_response", {}).get("data", {})
        if isinstance(results, dict):
            results = results.get("results", [])
        return [p for p in results if p.get("type") == "pin" or "images" in p]


# Pinterest hands back several renditions; take the biggest real one.
SIZE_ORDER = ["orig", "originals", "736x", "564x", "474x", "236x", "170x"]


def best_image(pin: dict) -> str | None:
    imgs = pin.get("images") or {}
    for key in SIZE_ORDER:
        if key in imgs and imgs[key].get("url"):
            return imgs[key]["url"]
    for v in imgs.values():
        if isinstance(v, dict) and v.get("url"):
            return v["url"]
    return None


def download(url: str, dest: Path) -> int:
    req = urllib.request.Request(url, headers={"User-Agent": UA,
                                               "referer": "https://www.pinterest.com/"})
    with urllib.request.urlopen(req, timeout=45) as r:
        blob = r.read()
    dest.write_bytes(blob)
    return len(blob)


# --------------------------------------------------------------------------- #
# Commands
# --------------------------------------------------------------------------- #

def cmd_new(a):
    d = run_dir(a.slug)
    if d.exists() and not a.force:
        die(f"run already exists: {d}. pass --force to overwrite")
    (d / "refs").mkdir(parents=True, exist_ok=True)
    (d / "out").mkdir(parents=True, exist_ok=True)
    save_run(a.slug, {
        "slug": a.slug,
        "created_at": now(),
        "brief": {"request": a.request, "aspect": a.aspect},
        "genre": None, "references": [], "moodboard": None,
        "route": None, "attempts": [], "final": None,
        "status": "brief",
    })
    print(json.dumps({"ok": True, "dir": str(d)}, ensure_ascii=False))


def cmd_refs(a):
    run = load_run(a.slug)
    routing = load_routing()
    suffix = ""
    if a.genre:
        g = routing["genres"].get(a.genre)
        if not g:
            die(f"unknown genre: {a.genre}")
        suffix = g.get("pinterest_suffix", "")
    query = f"{a.query} {suffix}".strip()

    pins = Pinterest().search(query, page_size=max(a.n * 3, 25))
    refs_dir = run_dir(a.slug) / "refs"
    refs, i = [], 0
    seen = set()
    for pin in pins:
        if len(refs) >= a.n:
            break
        url = best_image(pin)
        if not url or url in seen:
            continue
        seen.add(url)
        i += 1
        ext = Path(urllib.parse.urlparse(url).path).suffix or ".jpg"
        name = f"ref-{i:02d}{ext}"
        try:
            size = download(url, refs_dir / name)
        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError) as e:
            print(f"  skip {url}: {e}", file=sys.stderr)
            continue
        if size < 3000:          # placeholder / error image
            (refs_dir / name).unlink(missing_ok=True)
            continue
        refs.append({
            "file": f"refs/{name}",
            "pin_id": pin.get("id"),
            "source": f"https://www.pinterest.com/pin/{pin.get('id')}/",
            "dominant_color": pin.get("dominant_color"),
            "alt": (pin.get("grid_title") or pin.get("title")
                    or pin.get("seo_alt_text") or pin.get("description") or "").strip(),
            "bytes": size,
        })

    run["references"] = refs
    run["reference_query"] = query
    run["status"] = "reference"
    save_run(a.slug, run)
    if not refs:
        die("pinterest returned no usable images. "
            "try a different query, or drop your own files into "
            f"{refs_dir} and record them with rf.py set")
    print(json.dumps({"ok": True, "query": query, "count": len(refs),
                      "files": [r["file"] for r in refs]},
                     ensure_ascii=False, indent=2))


def cmd_routing(a):
    routing = load_routing()
    if a.genre:
        g = routing["genres"].get(a.genre)
        if not g:
            die(f"unknown genre: {a.genre}. known: {', '.join(routing['genres'])}")
        out = dict(g)
        out["id"] = a.genre
        out["defaults"] = routing["defaults"]
    else:
        out = {gid: {"label": g["label"], "match": g["match"],
                     "primary_model": g["primary"]["model"]}
               for gid, g in routing["genres"].items()}
    print(json.dumps(out, ensure_ascii=False, indent=2))


def backend_available(backend: str) -> tuple[bool, str]:
    if backend == "gemini":
        key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
        return (bool(key), "GEMINI_API_KEY set" if key else "GEMINI_API_KEY not set")
    if backend == "higgsfield":
        # Credits live behind the MCP server; the orchestrator checks with
        # the `balance` tool and records the answer here.
        state = os.environ.get("RF_HIGGSFIELD_READY", "")
        return (state == "1", "RF_HIGGSFIELD_READY=1" if state == "1"
                else "higgsfield credits unconfirmed (set RF_HIGGSFIELD_READY=1 "
                     "after checking the MCP balance tool)")
    return (False, f"unknown backend: {backend}")


def cmd_route(a):
    run = load_run(a.slug)
    routing = load_routing()
    gid = a.genre or (run.get("genre") or {}).get("id")
    if not gid:
        die("no genre. pass --genre or set run.genre first")
    g = routing["genres"].get(gid)
    if not g:
        die(f"unknown genre: {gid}")

    tried = []
    chosen = None
    for slot in ("primary", "fallback"):
        cand = g.get(slot)
        if not cand:
            continue
        ok, why = backend_available(cand["backend"])
        tried.append({"slot": slot, "backend": cand["backend"],
                      "model": cand["model"], "available": ok, "why": why})
        if ok and not chosen:
            chosen = {**cand, "slot": slot}

    run["genre"] = {**(run.get("genre") or {}), "id": gid,
                    "label": g["label"]}
    run["route"] = {"chosen": chosen, "candidates": tried,
                    "negative": g["negative"],
                    "prompt_template": g["prompt_template"],
                    "upscale": g.get("upscale") or routing["defaults"].get("upscale")}
    run["status"] = "route" if chosen else "blocked_no_backend"
    save_run(a.slug, run)
    print(json.dumps(run["route"], ensure_ascii=False, indent=2))
    if not chosen:
        die("no generation backend is usable right now — see candidates above", 2)


GEMINI_DEFAULT_MODEL = os.environ.get("RF_GEMINI_MODEL", "gemini-3-pro-image")


def gemini_key() -> str:
    key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
    if not key:
        die("GEMINI_API_KEY not set. get one at https://aistudio.google.com/apikey")
    return key


def gemini_image_models(key: str) -> list[str]:
    """Image-capable models this key can actually reach, newest-looking first."""
    req = urllib.request.Request(
        "https://generativelanguage.googleapis.com/v1beta/models?pageSize=200",
        headers={"x-goog-api-key": key})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            payload = json.loads(r.read())
    except urllib.error.HTTPError as e:
        die(f"gemini ListModels HTTP {e.code}: {e.read().decode('utf-8', 'replace')[:300]}")
    names = [m["name"].split("/")[-1] for m in payload.get("models", [])
             if "generateContent" in m.get("supportedGenerationMethods", [])
             and "image" in m["name"].lower()]
    # "-image" models that are not the deprecated preview line come first.
    names.sort(key=lambda n: ("preview" in n, n), reverse=False)
    names.sort(key=lambda n: ("pro" not in n, "preview" in n))
    return names


def _gemini_call(model: str, prompt: str, aspect: str, key: str):
    url = (f"https://generativelanguage.googleapis.com/v1beta/models/"
           f"{model}:generateContent")
    body = json.dumps({
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"responseModalities": ["IMAGE"],
                             "imageConfig": {"aspectRatio": aspect}},
    }).encode()
    req = urllib.request.Request(url, data=body, headers={
        "content-type": "application/json", "x-goog-api-key": key})
    with urllib.request.urlopen(req, timeout=300) as r:
        return json.loads(r.read())


def gemini_generate(prompt: str, aspect: str, model: str) -> tuple[bytes, str]:
    key = gemini_key()
    if model in (None, "", "default"):
        model = GEMINI_DEFAULT_MODEL

    # A wrong or retired model id is the most common failure here, so ask the
    # API which image models the key can reach rather than guessing again.
    try:
        payload = _gemini_call(model, prompt, aspect, key)
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", "replace")
        if e.code == 429 and "limit: 0" in detail:
            die("gemini image models have no free-tier quota on this key "
                "(limit: 0). enable billing on the key's Google Cloud project "
                "at https://aistudio.google.com/apikey — image generation is "
                "billed per image. text models still work on the free tier.")
        if e.code not in (400, 404):
            die(f"gemini HTTP {e.code}: {detail[:600]}")
        available = gemini_image_models(key)
        alt = next((m for m in available if m != model), None)
        if not alt:
            die(f"gemini rejected '{model}' ({e.code}) and this key has no other "
                f"image model. detail: {detail[:400]}")
        print(f"  '{model}' rejected ({e.code}); falling back to '{alt}'", file=sys.stderr)
        model = alt
        try:
            payload = _gemini_call(model, prompt, aspect, key)
        except urllib.error.HTTPError as e2:
            die(f"gemini HTTP {e2.code} on '{model}': "
                f"{e2.read().decode('utf-8', 'replace')[:600]}\n"
                f"image models on this key: {', '.join(available)}")

    for cand in payload.get("candidates", []):
        for part in cand.get("content", {}).get("parts", []):
            inline = part.get("inlineData") or part.get("inline_data")
            if inline and inline.get("data"):
                return base64.b64decode(inline["data"]), model
    die(f"gemini returned no image: {json.dumps(payload)[:600]}")


def next_attempt(run: dict) -> int:
    return len(run.get("attempts", [])) + 1


def cmd_gen(a):
    run = load_run(a.slug)
    route = (run.get("route") or {}).get("chosen")
    if not route:
        die("no route chosen. run: rf.py route <slug> --genre <id>")
    if route["backend"] != "gemini":
        die(f"route backend is '{route['backend']}', not gemini. "
            "generate through the Higgsfield MCP tool, then: rf.py adopt")
    prompt = Path(a.prompt_file).read_text(encoding="utf-8") if a.prompt_file else a.prompt
    if not prompt:
        die("pass --prompt or --prompt-file")
    aspect = a.aspect or run["brief"].get("aspect") or "3:2"

    n = next_attempt(run)
    blob, used_model = gemini_generate(prompt, aspect, route.get("model"))
    rel = f"out/attempt-{n:02d}.png"
    (run_dir(a.slug) / rel).write_bytes(blob)
    run.setdefault("attempts", []).append({
        "n": n, "backend": "gemini", "model": used_model,
        "prompt": prompt, "aspect": aspect, "file": rel,
        "bytes": len(blob), "created_at": now(),
        "score": None, "critique": None, "fix": None,
    })
    run["status"] = "generated"
    save_run(a.slug, run)
    print(json.dumps({"ok": True, "attempt": n, "file": rel, "bytes": len(blob)},
                     ensure_ascii=False))


def cmd_adopt(a):
    run = load_run(a.slug)
    n = next_attempt(run)
    src = a.source
    ext = Path(urllib.parse.urlparse(src).path).suffix or ".png"
    rel = f"out/attempt-{n:02d}{ext}"
    dest = run_dir(a.slug) / rel
    if src.startswith(("http://", "https://")):
        size = download(src, dest)
    else:
        p = Path(src).expanduser()
        if not p.exists():
            die(f"no such file: {p}")
        shutil.copyfile(p, dest)
        size = dest.stat().st_size
    run.setdefault("attempts", []).append({
        "n": n, "backend": a.backend, "model": a.model,
        "prompt": a.prompt, "file": rel, "bytes": size,
        "source": src, "created_at": now(),
        "score": None, "critique": None, "fix": None,
    })
    run["status"] = "generated"
    save_run(a.slug, run)
    print(json.dumps({"ok": True, "attempt": n, "file": rel, "bytes": size},
                     ensure_ascii=False))


def set_path(obj, dotted: str, value):
    keys = dotted.split(".")
    cur = obj
    for k in keys[:-1]:
        if k.isdigit() and isinstance(cur, list):
            cur = cur[int(k)]
            continue
        # A key can exist holding null (a fresh run.json has genre: null),
        # so setdefault is not enough — replace anything that is not a dict.
        if not isinstance(cur.get(k), dict):
            cur[k] = {}
        cur = cur[k]
    last = keys[-1]
    if last.isdigit() and isinstance(cur, list):
        cur[int(last)] = value
    else:
        cur[last] = value


def cmd_set(a):
    run = load_run(a.slug)
    for pair in a.pairs:
        if "=" not in pair:
            die(f"expected dotted.path=json, got: {pair}")
        path, raw = pair.split("=", 1)
        try:
            value = json.loads(raw)
        except json.JSONDecodeError:
            value = raw
        set_path(run, path, value)
    save_run(a.slug, run)
    print(json.dumps({"ok": True, "run": a.slug}, ensure_ascii=False))


def cmd_show(a):
    print(json.dumps(load_run(a.slug), ensure_ascii=False, indent=2))


def cmd_index(a):
    runs = []
    for d in sorted(RUNS.iterdir() if RUNS.exists() else []):
        f = d / "run.json"
        if f.is_dir() or not f.exists():
            continue
        try:
            runs.append(json.loads(f.read_text(encoding="utf-8")))
        except json.JSONDecodeError as e:
            print(f"  skip {d.name}: {e}", file=sys.stderr)
    runs.sort(key=lambda r: r.get("created_at", ""), reverse=True)
    VIEWER.mkdir(parents=True, exist_ok=True)
    payload = {"generated_at": now(), "runs": runs}
    (VIEWER / "data.js").write_text(
        "window.RF_DATA = " + json.dumps(payload, ensure_ascii=False, indent=2) + ";\n",
        encoding="utf-8")
    print(json.dumps({"ok": True, "runs": len(runs),
                      "viewer": str(VIEWER / "index.html")}, ensure_ascii=False))


def main():
    ap = argparse.ArgumentParser(prog="rf.py", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("new"); p.add_argument("slug"); p.add_argument("--request", required=True)
    p.add_argument("--aspect", default="3:2"); p.add_argument("--force", action="store_true")
    p.set_defaults(fn=cmd_new)

    p = sub.add_parser("refs"); p.add_argument("slug"); p.add_argument("--query", required=True)
    p.add_argument("--genre"); p.add_argument("-n", type=int, default=10)
    p.set_defaults(fn=cmd_refs)

    p = sub.add_parser("routing"); p.add_argument("genre", nargs="?")
    p.set_defaults(fn=cmd_routing)

    p = sub.add_parser("route"); p.add_argument("slug"); p.add_argument("--genre")
    p.set_defaults(fn=cmd_route)

    p = sub.add_parser("gen"); p.add_argument("slug")
    p.add_argument("--prompt"); p.add_argument("--prompt-file"); p.add_argument("--aspect")
    p.set_defaults(fn=cmd_gen)

    p = sub.add_parser("adopt"); p.add_argument("slug"); p.add_argument("source")
    p.add_argument("--backend", default="higgsfield"); p.add_argument("--model", default="")
    p.add_argument("--prompt", default="")
    p.set_defaults(fn=cmd_adopt)

    p = sub.add_parser("set"); p.add_argument("slug"); p.add_argument("pairs", nargs="+")
    p.set_defaults(fn=cmd_set)

    p = sub.add_parser("show"); p.add_argument("slug"); p.set_defaults(fn=cmd_show)
    p = sub.add_parser("index"); p.set_defaults(fn=cmd_index)

    args = ap.parse_args()
    args.fn(args)


if __name__ == "__main__":
    main()
