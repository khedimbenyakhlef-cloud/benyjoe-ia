"""
╔══════════════════════════════════════════════════════════╗
║  BENY-JOE IA — Backend Flask                           ║
║  Fondé par KHEDIM BENYAKHLEF dit BENY-JOE              ║
║  Déployé sur Render                                     ║
╚══════════════════════════════════════════════════════════╝
"""

import os
import uuid
import json
import time
import threading
from datetime import datetime, timezone
from flask import Flask, request, jsonify, send_from_directory, abort
from flask_cors import CORS

# ── Config ────────────────────────────────────────────────────────────
OUTPUTS_DIR   = os.environ.get("OUTPUTS_DIR", os.path.join(os.path.dirname(__file__), "..", "outputs"))
SECRET_KEY    = os.environ.get("BENYJOE_SECRET", "benyjoe-secret-2025")
PORT          = int(os.environ.get("PORT", 10000))

os.makedirs(OUTPUTS_DIR, exist_ok=True)

app = Flask(__name__, static_folder="../frontend/public", static_url_path="")
CORS(app)

# ── In-memory store ───────────────────────────────────────────────────
jobs    = {}        # job_id → {status, progress, step, result, error, meta}
lock    = threading.Lock()
kaggle_url = {"url": None, "updated_at": None}   # URL ngrok active

# ════════════════════════════════════════════════════════════════════
#  UTILS
# ════════════════════════════════════════════════════════════════════

def new_job(prompt, job_type="video", params=None):
    jid = str(uuid.uuid4())[:12]
    with lock:
        jobs[jid] = {
            "id":          jid,
            "type":        job_type,
            "prompt":      prompt,
            "status":      "pending",
            "progress":    0,
            "step":        "En attente du moteur Kaggle TPU…",
            "result":      None,
            "error":       None,
            "created_at":  datetime.now(timezone.utc).isoformat(),
            "params":      params or {},
        }
    return jid


def update_job(jid, **kwargs):
    with lock:
        if jid in jobs:
            jobs[jid].update(kwargs)


def forward_to_kaggle(jid, payload):
    """Envoie la requête au notebook Kaggle via ngrok puis poll le statut."""
    import requests as req

    base = kaggle_url.get("url")
    if not base:
        update_job(jid, status="error",
                   error="Moteur Kaggle non connecté. Lancez le notebook Kaggle.")
        return

    # ── 1. Soumettre le job à Kaggle ──────────────────────────────────
    try:
        r = req.post(f"{base}/generate", json=payload, timeout=30)
        if r.status_code != 200:
            update_job(jid, status="error",
                       error=f"Kaggle erreur {r.status_code}: {r.text[:200]}")
            return
        kaggle_jid = r.json().get("job_id", jid)
    except Exception as e:
        update_job(jid, status="error", error=f"Connexion Kaggle : {e}")
        return

    update_job(jid, status="processing", progress=5,
               step="Job soumis au moteur Kaggle TPU…")

    # ── 2. Polling du statut jusqu'à done/error (max 20 min) ──────────
    deadline = time.time() + 1200   # 20 minutes max
    interval = 10                    # poll toutes les 10s

    while time.time() < deadline:
        time.sleep(interval)

        # Vérifier si /api/video-ready a déjà mis à jour le job
        with lock:
            current = dict(jobs.get(jid, {}))
        if current.get("status") in ("done", "error"):
            return   # déjà mis à jour par video_ready()

        # Sinon, interroger Kaggle directement
        try:
            resp = req.get(f"{base}/api/jobs/{kaggle_jid}", timeout=10)
            if resp.status_code != 200:
                continue
            kdata    = resp.json()
            kstatus  = kdata.get("status", "processing")
            kprogress= kdata.get("progress", 0)
            kstep    = kdata.get("step", "")
            kresult  = kdata.get("result", "")   # ex: "/outputs/BENYJOE_FINAL_xyz.mp4"

            # Mettre à jour la progression côté Render
            update_job(jid, progress=kprogress, step=kstep)

            if kstatus == "done" and kresult:
                # Construire l'URL publique complète via ngrok
                ngrok_base = (kaggle_url.get("url") or "").rstrip("/")
                video_url  = f"{ngrok_base}{kresult}"
                update_job(jid,
                           status="done",
                           progress=100,
                           step="Vidéo prête !",
                           result=video_url)
                print(f"✅ Job {jid} terminé : {video_url}")
                return

            if kstatus == "error":
                update_job(jid, status="error",
                           error=kdata.get("error", "Erreur inconnue Kaggle"))
                return

        except Exception as e:
            print(f"⚠️  Poll Kaggle {jid} : {e}")
            continue

    # Timeout
    update_job(jid, status="error",
               error="Timeout 20min — le moteur Kaggle n'a pas répondu")


# ════════════════════════════════════════════════════════════════════
#  ROUTES API
# ════════════════════════════════════════════════════════════════════

@app.route("/api/health", methods=["GET"])
def health():
    return jsonify({
        "status":       "ok",
        "platform":     "BENY-JOE IA",
        "founder":      "KHEDIM BENYAKHLEF dit BENY-JOE",
        "kaggle_ready": kaggle_url["url"] is not None,
        "kaggle_url":   kaggle_url["url"],
        "jobs_total":   len(jobs),
        "server_time":  datetime.now(timezone.utc).isoformat(),
    })


@app.route("/api/kaggle-url", methods=["POST"])
def set_kaggle_url():
    """Le notebook Kaggle envoie son URL ngrok ici."""
    data = request.get_json(silent=True) or {}
    secret = data.get("secret") or request.headers.get("X-Secret")
    if secret != SECRET_KEY:
        abort(403)
    url = data.get("url", "").rstrip("/")
    if not url.startswith("http"):
        return jsonify({"error": "URL invalide"}), 400
    kaggle_url["url"]        = url
    kaggle_url["updated_at"] = datetime.now(timezone.utc).isoformat()
    print(f"✅ Kaggle URL enregistrée : {url}")
    return jsonify({"ok": True, "url": url})


@app.route("/api/kaggle-url", methods=["GET"])
def get_kaggle_url():
    return jsonify(kaggle_url)


@app.route("/api/generate", methods=["POST"])
def generate():
    """Lance une génération vidéo / image / animation."""
    data   = request.get_json(silent=True) or {}
    prompt = (data.get("prompt") or "").strip()
    if not prompt:
        return jsonify({"error": "Prompt requis"}), 400

    job_type = data.get("type", "video")   # video | image | animate
    params   = {
        "resolution":  data.get("resolution",  "1024x576"),
        "frames":      int(data.get("frames",  120)),
        "fps":         int(data.get("fps",     24)),
        "voice":       data.get("voice",       True),
        "music":       data.get("music",       True),
        "voice_lang":  data.get("voice_lang",  "fr"),
        "music_style": data.get("music_style", "cinematic"),
        "duration":    int(data.get("duration", 10)),
    }

    jid = new_job(prompt, job_type=job_type, params=params)
    update_job(jid, status="queued", step="Envoi au moteur Kaggle TPU…")

    payload = {"job_id": jid, "prompt": prompt, "type": job_type, **params}
    t = threading.Thread(target=forward_to_kaggle, args=(jid, payload), daemon=True)
    t.start()

    return jsonify({"job_id": jid, "status": "queued"})


@app.route("/api/jobs", methods=["GET"])
def list_jobs():
    with lock:
        return jsonify({
            "queue_size": sum(1 for j in jobs.values() if j["status"] in ("pending","queued","processing")),
            "jobs":       dict(jobs),
        })


@app.route("/api/jobs/<jid>", methods=["GET"])
def get_job(jid):
    with lock:
        job = jobs.get(jid)
    if not job:
        return jsonify({"error": "Job introuvable"}), 404
    return jsonify(job)


@app.route("/api/video-ready", methods=["POST"])
def video_ready():
    """Le notebook signale qu'une vidéo est prête (watcher)."""
    data   = request.get_json(silent=True) or {}
    secret = data.get("secret") or request.headers.get("X-Secret")
    # Secret optionnel mais vérifié s'il est fourni
    if secret and secret != SECRET_KEY:
        abort(403)

    jid = data.get("job_id", "unknown")
    url = (data.get("video_url") or "").strip()

    # ── Rejeter les URLs invalides (null, vide, etc.) ─────────────────
    if not url or url in ("null", "None", "undefined") or not url.startswith("http"):
        print(f"⚠️  video_ready ignoré : URL invalide '{url}' pour job {jid}")
        return jsonify({"ok": False, "reason": "URL invalide — ignorée"}), 400

    if jid in jobs:
        update_job(jid, status="done", progress=100,
                   step="Vidéo prête !", result=url)
    else:
        # Vidéo sans job connu → on l'enregistre quand même
        with lock:
            jobs[jid] = {
                "id":         jid,
                "type":       data.get("type", "video"),
                "prompt":     data.get("prompt", ""),
                "status":     "done",
                "progress":   100,
                "step":       "Vidéo reçue du notebook",
                "result":     url,
                "error":      None,
                "created_at": datetime.now(timezone.utc).isoformat(),
                "params":     data,
            }
    print(f"✅ video_ready : job {jid} → {url}")
    return jsonify({"ok": True})


@app.route("/api/jobs/<jid>/progress", methods=["POST"])
def update_progress(jid):
    """Le notebook met à jour la progression d'un job."""
    data = request.get_json(silent=True) or {}
    secret = data.get("secret") or request.headers.get("X-Secret")
    if secret != SECRET_KEY:
        abort(403)
    update_job(jid,
               status=data.get("status", "processing"),
               progress=data.get("progress", 0),
               step=data.get("step", ""))
    return jsonify({"ok": True})


@app.route("/outputs/<path:filename>")
def serve_output(filename):
    return send_from_directory(OUTPUTS_DIR, filename)


# ── SPA fallback ──────────────────────────────────────────────────────
@app.route("/", defaults={"path": ""})
@app.route("/<path:path>")
def spa(path):
    index = os.path.join(app.static_folder, "index.html")
    if os.path.exists(index):
        return send_from_directory(app.static_folder, "index.html")
    return "BENY-JOE IA — Backend opérationnel", 200


# ════════════════════════════════════════════════════════════════════
if __name__ == "__main__":
    print("╔══════════════════════════════════════════════╗")
    print("║  BENY-JOE IA — Serveur Backend              ║")
    print("║  Fondé par KHEDIM BENYAKHLEF dit BENY-JOE  ║")
    print("╚══════════════════════════════════════════════╝")
    app.run(host="0.0.0.0", port=PORT, debug=False)
