"""
╔══════════════════════════════════════════════════════════════════════╗
║  BENY-JOE IA — Serveur Render (app.py)                             ║
║  Fondé par KHEDIM BENYAKHLEF dit BENY-JOE                          ║
║                                                                      ║
║  Déploiement : Render Web Service                                   ║
║  Variables d'environnement requises :                               ║
║    BENYJOE_SECRET  → clé secrète partagée avec le notebook Kaggle  ║
║    PORT            → fourni automatiquement par Render              ║
╚══════════════════════════════════════════════════════════════════════╝

Ce fichier est le SERVEUR RENDER — il reçoit :
  1. L'URL ngrok du notebook Kaggle  (/api/kaggle-url)
  2. La notification quand une vidéo est prête (/api/video-ready)
  3. Les requêtes de génération du frontend (/api/generate)
  4. Le polling de statut des jobs (/api/jobs/<jid>)

Et il sert :
  - Le frontend HTML/JS (pages vidéo, image, animation)
  - Les fichiers statiques
"""

import os
import uuid
import time
import logging
import threading
import requests
from pathlib import Path
from datetime import datetime, timezone
from flask import Flask, request, jsonify, send_from_directory, abort, redirect
from flask_cors import CORS

# ── Chemin absolu vers frontend/public/ (structure du repo) ───────────
BASE_DIR     = Path(__file__).resolve().parent        # backend/
FRONTEND_DIR = BASE_DIR.parent / 'frontend' / 'public'  # frontend/public/

# ── Configuration ──────────────────────────────────────────────────────
app = Flask(__name__, static_folder=str(FRONTEND_DIR))
CORS(app)

logging.basicConfig(level=logging.INFO)
log = logging.getLogger('BENYJOE-RENDER')

PORT          = int(os.environ.get('PORT', 10000))
SECRET_KEY    = os.environ.get('BENYJOE_SECRET', 'benyjoe-secret-2025')
PLATFORM_NAME = 'BENY-JOE IA'

# ── État partagé (en mémoire) ──────────────────────────────────────────
state = {
    'kaggle_url':    None,   # URL ngrok du notebook Kaggle actif
    'kaggle_device': None,
    'kaggle_seen':   None,   # datetime dernière connexion Kaggle
    'videos':        [],     # liste des vidéos prêtes (url + job_id)
}
state_lock = threading.Lock()

# Jobs locaux (proxy du statut Kaggle)
jobs_cache = {}
jobs_lock  = threading.Lock()


# ════════════════════════════════════════════════════════════════════════
#  UTILITAIRES
# ════════════════════════════════════════════════════════════════════════

def check_secret(data):
    """Vérifie que la clé secrète est correcte."""
    return data.get('secret') == SECRET_KEY


def forward_to_kaggle(path, method='POST', json_data=None, timeout=60):
    """Transmet une requête au notebook Kaggle via ngrok."""
    with state_lock:
        base = state.get('kaggle_url')
    if not base:
        return None, 'Notebook Kaggle non connecté'
    url = f"{base.rstrip('/')}/{path.lstrip('/')}"
    try:
        if method == 'POST':
            r = requests.post(url, json=json_data, timeout=timeout)
        else:
            r = requests.get(url, timeout=timeout)
        return r, None
    except requests.exceptions.ConnectionError:
        with state_lock:
            state['kaggle_url'] = None  # Tunnel mort → reset
        return None, 'Tunnel ngrok expiré — relancez le notebook Kaggle'
    except Exception as e:
        return None, str(e)


# ════════════════════════════════════════════════════════════════════════
#  ENDPOINTS REÇUS DU NOTEBOOK KAGGLE
# ════════════════════════════════════════════════════════════════════════

@app.route('/api/kaggle-url', methods=['POST'])
def receive_kaggle_url():
    """
    Reçoit l'URL ngrok du notebook Kaggle.
    Appelé par cellule 4 et cellule 5 (re-push toutes les 5 min).
    """
    data = request.get_json(silent=True) or {}
    if not check_secret(data):
        return jsonify({'error': 'Secret invalide'}), 403

    url    = (data.get('url') or '').strip()
    device = data.get('device', 'Kaggle-TPU')

    if not url or not url.startswith('http'):
        return jsonify({'error': 'URL invalide'}), 400

    with state_lock:
        state['kaggle_url']    = url
        state['kaggle_device'] = device
        state['kaggle_seen']   = datetime.now(timezone.utc).isoformat()

    log.info(f'✅ Kaggle connecté : {url} [{device}]')
    return jsonify({'status': 'ok', 'message': 'URL enregistrée', 'url': url}), 200


@app.route('/api/video-ready', methods=['POST'])
def receive_video_ready():
    """
    Reçoit la notification quand une vidéo est prête (depuis watcher Kaggle).
    Stocke l'URL GitHub ou ngrok pour que le frontend puisse la récupérer.
    """
    data = request.get_json(silent=True) or {}
    if not check_secret(data):
        return jsonify({'error': 'Secret invalide'}), 403

    job_id    = data.get('job_id', 'unknown')
    video_url = data.get('video_url', '')
    source    = data.get('source', 'unknown')

    if not video_url:
        return jsonify({'error': 'video_url requis'}), 400

    entry = {
        'job_id':    job_id,
        'video_url': video_url,
        'source':    source,
        'device':    data.get('device', ''),
        'received':  datetime.now(timezone.utc).isoformat(),
    }

    with state_lock:
        state['videos'].append(entry)
        # Garder seulement les 50 dernières
        state['videos'] = state['videos'][-50:]

    # Mettre à jour le cache job
    with jobs_lock:
        if job_id in jobs_cache:
            jobs_cache[job_id]['status']    = 'done'
            jobs_cache[job_id]['progress']  = 100
            jobs_cache[job_id]['video_url'] = video_url
            jobs_cache[job_id]['result']    = video_url

    log.info(f'🎬 Vidéo reçue — job {job_id} : {video_url[:80]}')
    return jsonify({'status': 'ok', 'job_id': job_id}), 200


# ════════════════════════════════════════════════════════════════════════
#  ENDPOINTS DU FRONTEND (appelés par le navigateur)
# ════════════════════════════════════════════════════════════════════════

@app.route('/api/generate', methods=['POST'])
def api_generate():
    """
    Reçoit une demande de génération du frontend.
    Transmet au notebook Kaggle et retourne le job_id.
    """
    data   = request.get_json(silent=True) or {}
    prompt = (data.get('prompt') or '').strip()

    if not prompt:
        return jsonify({'error': 'Prompt requis'}), 400

    # Vérifier que Kaggle est connecté
    with state_lock:
        kaggle_url = state.get('kaggle_url')
    if not kaggle_url:
        return jsonify({
            'error': 'Notebook Kaggle non connecté',
            'help':  'Lancez les cellules 1 à 5 dans votre notebook Kaggle'
        }), 503

    # Générer un job_id côté Render aussi
    jid = str(uuid.uuid4())[:12]
    data['job_id'] = jid

    # Initialiser le job dans le cache local
    with jobs_lock:
        jobs_cache[jid] = {
            'id':        jid,
            'status':    'queued',
            'progress':  0,
            'step':      'Envoi au notebook Kaggle…',
            'result':    None,
            'video_url': None,
            'error':     None,
            'created':   datetime.now(timezone.utc).isoformat(),
        }

    # Transmettre au notebook Kaggle (en thread pour ne pas bloquer)
    def forward_async():
        resp, err = forward_to_kaggle('/generate', 'POST', data, timeout=30)
        with jobs_lock:
            if jid not in jobs_cache:
                return
            if err:
                jobs_cache[jid]['status'] = 'error'
                jobs_cache[jid]['error']  = err
            elif resp and resp.status_code == 200:
                jobs_cache[jid]['status'] = 'processing'
                jobs_cache[jid]['step']   = 'Traitement sur Kaggle TPU…'
            else:
                status_code = resp.status_code if resp else '?'
                jobs_cache[jid]['status'] = 'error'
                jobs_cache[jid]['error']  = f'Erreur Kaggle : {status_code}'

    threading.Thread(target=forward_async, daemon=True).start()

    return jsonify({'job_id': jid, 'status': 'queued'}), 200


@app.route('/api/jobs/<jid>', methods=['GET'])
def api_job_status(jid):
    """
    Polling de statut d'un job.
    Vérifie d'abord le cache local, sinon interroge Kaggle directement.
    """
    # 1. Vérifier cache local
    with jobs_lock:
        job = jobs_cache.get(jid)

    if job:
        # Si done, retourner directement
        if job.get('status') == 'done':
            return jsonify(job)
        # Si en cours, aller chercher le vrai statut chez Kaggle
        resp, err = forward_to_kaggle(f'/api/jobs/{jid}', 'GET', timeout=10)
        if resp and resp.status_code == 200:
            kaggle_job = resp.json()
            with jobs_lock:
                # Merge : on garde video_url si Render l'a déjà
                if jid in jobs_cache and jobs_cache[jid].get('video_url'):
                    kaggle_job['video_url'] = jobs_cache[jid]['video_url']
                jobs_cache[jid] = kaggle_job
            return jsonify(kaggle_job)
        # Kaggle inaccessible : retourner ce qu'on a
        return jsonify(job)

    # 2. Job inconnu localement → demander à Kaggle
    resp, err = forward_to_kaggle(f'/api/jobs/{jid}', 'GET', timeout=10)
    if err:
        return jsonify({'error': err}), 503
    if resp.status_code == 404:
        return jsonify({'error': 'Job introuvable'}), 404
    return jsonify(resp.json())


@app.route('/api/jobs', methods=['GET'])
def api_all_jobs():
    """Liste tous les jobs connus par Render."""
    with jobs_lock:
        return jsonify({'jobs': list(jobs_cache.values()), 'count': len(jobs_cache)})


@app.route('/api/videos', methods=['GET'])
def api_videos():
    """Liste les vidéos reçues et disponibles."""
    with state_lock:
        return jsonify({'videos': state['videos']})


@app.route('/api/status', methods=['GET'])
def api_status():
    """Statut global de la plateforme (frontend polling toutes les 10s)."""
    with state_lock:
        kaggle_url    = state.get('kaggle_url')
        kaggle_device = state.get('kaggle_device')
        kaggle_seen   = state.get('kaggle_seen')
        nb_videos     = len(state['videos'])

    # Vérifier si Kaggle est vraiment vivant
    kaggle_alive = False
    if kaggle_url:
        try:
            r = requests.get(f"{kaggle_url}/health", timeout=5)
            kaggle_alive = r.status_code == 200
            if not kaggle_alive:
                with state_lock:
                    state['kaggle_url'] = None
        except Exception:
            with state_lock:
                state['kaggle_url'] = None

    return jsonify({
        'platform':      PLATFORM_NAME,
        'founder':       'KHEDIM BENYAKHLEF dit BENY-JOE',
        'kaggle_connected': kaggle_alive,
        'kaggle_device': kaggle_device,
        'kaggle_seen':   kaggle_seen,
        'videos_ready':  nb_videos,
        'timestamp':     datetime.now(timezone.utc).isoformat(),
    })


# ════════════════════════════════════════════════════════════════════════
#  HEALTH CHECK (requis par Render)
# ════════════════════════════════════════════════════════════════════════

@app.route('/health', methods=['GET'])
def health():
    return jsonify({'status': 'ok', 'service': PLATFORM_NAME}), 200


# ════════════════════════════════════════════════════════════════════════
#  FRONTEND : servir les fichiers depuis frontend/public/
# ════════════════════════════════════════════════════════════════════════

@app.route('/', methods=['GET'])
def index():
    """Page principale — sert index.html depuis frontend/public/."""
    return send_from_directory(str(FRONTEND_DIR), 'index.html')


@app.route('/<path:path>', methods=['GET'])
def static_files(path):
    """Sert tous les fichiers statiques (JS, CSS, images)."""
    # Ne pas intercepter les routes /api/
    if path.startswith('api/'):
        abort(404)
    target = FRONTEND_DIR / path
    if target.exists() and target.is_file():
        return send_from_directory(str(FRONTEND_DIR), path)
    # SPA fallback → index.html
    return send_from_directory(str(FRONTEND_DIR), 'index.html')


# ════════════════════════════════════════════════════════════════════════
#  DÉMARRAGE
# ════════════════════════════════════════════════════════════════════════

if __name__ == '__main__':
    log.info(f'🚀 {PLATFORM_NAME} — Render server démarré sur port {PORT}')
    app.run(host='0.0.0.0', port=PORT, debug=False)
