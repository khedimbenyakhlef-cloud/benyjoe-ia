"""
╔══════════════════════════════════════════════════════════════════════╗
║  BENY-JOE IA — Serveur Render (benyjoe.py) ✅ COMPLET              ║
║  Fondé par KHEDIM BENYAKHLEF dit BENY-JOE                          ║
║                                                                      ║
║  FIXES v3 :                                                          ║
║    ✅ Keep-alive auto (ping /health toutes les 14min)               ║
║    ✅ /api/download  — proxy vidéo + streaming MP4                  ║
║    ✅ /api/stream/<jid> — player HTML5 avec Range requests          ║
║    ✅ /api/health   — alias de /health pour le frontend             ║
║    ✅ jobs réponse inclut stream_url + download_url                 ║
╚══════════════════════════════════════════════════════════════════════╝
"""

import os, uuid, time, logging, threading, requests
from pathlib import Path
from datetime import datetime, timezone
from flask import (Flask, request, jsonify, send_from_directory,
                   abort, Response, stream_with_context)
from flask_cors import CORS

BASE_DIR     = Path(__file__).resolve().parent
FRONTEND_DIR = BASE_DIR.parent / 'frontend' / 'public'

app = Flask(__name__, static_folder=str(FRONTEND_DIR))
CORS(app)

# GOOGLE AUTH
from flask_dance.contrib.google import make_google_blueprint, google
from functools import wraps
os.environ.setdefault('OAUTHLIB_RELAX_TOKEN_SCOPE', '1')
os.environ.setdefault('OAUTHLIB_INSECURE_TRANSPORT', '0')
google_bp = make_google_blueprint(
    client_id=os.environ.get('GOOGLE_CLIENT_ID'),
    client_secret=os.environ.get('GOOGLE_CLIENT_SECRET'),
    scope=['openid','https://www.googleapis.com/auth/userinfo.email','https://www.googleapis.com/auth/userinfo.profile'],
    redirect_url='/auth/google/authorized',
)
app.secret_key = os.environ.get('SECRET_KEY', os.environ.get('BENYJOE_SECRET','benyjoe-secret-2025'))
app.register_blueprint(google_bp, url_prefix='/auth')
ALLOWED_EMAIL = os.environ.get('ALLOWED_EMAIL','khedimbenyakhlef@gmail.com')
def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not google.authorized:
            return '<html><body style="text-align:center;margin-top:100px"><h2>BENY-JOE IA</h2><br><a href="/auth/google/login" style="padding:12px 24px;background:#4285F4;color:white;border-radius:6px;text-decoration:none">Se connecter avec Google</a></body></html>'
        info = google.get('/oauth2/v2/userinfo')
        if not info.ok:
            return '<h3>Erreur Auth</h3>', 500
        email = info.json().get('email','')
        if email != ALLOWED_EMAIL:
            return f'<h3>Acces refuse : {email}</h3>', 403
        return f(*args, **kwargs)
    return decorated


logging.basicConfig(level=logging.INFO)
log = logging.getLogger('BENYJOE-RENDER')

PORT          = int(os.environ.get('PORT', 10000))
SECRET_KEY    = os.environ.get('BENYJOE_SECRET', 'benyjoe-secret-2025')
RENDER_URL    = os.environ.get('RENDER_URL', 'https://benyjoe-ia.onrender.com')
PLATFORM_NAME = 'BENY-JOE IA'

state = {
    'kaggle_url':    None,
    'kaggle_device': None,
    'kaggle_seen':   None,
    'videos':        [],
}
state_lock = threading.Lock()
jobs_cache = {}
jobs_lock  = threading.Lock()


# ════════════════════════════════════════════════════════════════════════
#  KEEP-ALIVE RENDER (évite le spin-down sur plan gratuit)
#  Render free tier s'endort après 15min d'inactivité.
#  On se ping soi-même toutes les 14min pour rester éveillé.
# ════════════════════════════════════════════════════════════════════════

def _self_ping():
    """Ping notre propre /health toutes les 14 minutes."""
    time.sleep(30)  # attendre que le serveur soit prêt
    while True:
        try:
            r = requests.get(f'{RENDER_URL}/health', timeout=10)
            log.info(f'♾️  Keep-alive ping → {r.status_code}')
        except Exception as e:
            log.warning(f'Keep-alive ping erreur : {e}')
        time.sleep(14 * 60)  # 14 minutes

threading.Thread(target=_self_ping, daemon=True, name='KeepAlive').start()


# ════════════════════════════════════════════════════════════════════════
#  UTILITAIRES
# ════════════════════════════════════════════════════════════════════════

def check_secret(data):
    return data.get('secret') == SECRET_KEY

def get_kaggle_base():
    with state_lock:
        return state.get('kaggle_url')

def forward_to_kaggle(path, method='POST', json_data=None, timeout=60):
    base = get_kaggle_base()
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
            state['kaggle_url'] = None
        return None, 'Tunnel ngrok expiré — relancez le notebook Kaggle'
    except Exception as e:
        return None, str(e)

def _build_video_urls(jid, raw_url):
    """Construit stream_url et download_url pour un job vidéo."""
    kaggle_base = get_kaggle_base()
    if raw_url and not raw_url.startswith('http') and kaggle_base:
        abs_url = f"{kaggle_base.rstrip('/')}/{raw_url.lstrip('/')}"
    else:
        abs_url = raw_url or ''
    return {
        'video_url':    abs_url,
        'stream_url':   f'/api/stream/{jid}',
        'download_url': f'/api/download?url={raw_url}&type=video',
    }


# ════════════════════════════════════════════════════════════════════════
#  ENDPOINTS REÇUS DU NOTEBOOK KAGGLE
# ════════════════════════════════════════════════════════════════════════

@app.route('/api/kaggle-url', methods=['POST'])
def receive_kaggle_url():
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
    return jsonify({'status': 'ok', 'url': url}), 200


@app.route('/api/video-ready', methods=['POST'])
def receive_video_ready():
    data = request.get_json(silent=True) or {}
    if not check_secret(data):
        return jsonify({'error': 'Secret invalide'}), 403
    job_id    = data.get('job_id', 'unknown')
    video_url = data.get('video_url', '')
    if not video_url:
        return jsonify({'error': 'video_url requis'}), 400
    entry = {
        'job_id':    job_id,
        'video_url': video_url,
        'source':    data.get('source', 'unknown'),
        'device':    data.get('device', ''),
        'received':  datetime.now(timezone.utc).isoformat(),
    }
    with state_lock:
        state['videos'].append(entry)
        state['videos'] = state['videos'][-50:]
    with jobs_lock:
        if job_id in jobs_cache:
            urls = _build_video_urls(job_id, video_url)
            jobs_cache[job_id].update({
                'status':       'done',
                'progress':     100,
                'result':       video_url,
                **urls,
            })
    log.info(f'🎬 Vidéo reçue — job {job_id}')
    return jsonify({'status': 'ok', 'job_id': job_id}), 200


# ════════════════════════════════════════════════════════════════════════
#  PROXY VIDÉO — /api/download  et  /api/stream/<jid>
# ════════════════════════════════════════════════════════════════════════

@app.route('/api/download', methods=['GET'])
def api_download():
    """
    Proxifie un fichier MP4/PNG depuis Kaggle (ngrok) ou GitHub.
    Paramètre GET : url = chemin relatif ou URL absolue
    """
    url_param = request.args.get('url', '').strip()
    if not url_param:
        return jsonify({'error': 'Paramètre url requis'}), 400

    if url_param.startswith('http'):
        source_url = url_param
    else:
        kaggle_base = get_kaggle_base()
        if not kaggle_base:
            return jsonify({'error': 'Kaggle non connecté'}), 503
        source_url = f"{kaggle_base.rstrip('/')}/{url_param.lstrip('/')}"

    try:
        upstream = requests.get(source_url, stream=True, timeout=30)
        if upstream.status_code == 404:
            return jsonify({'error': 'Fichier introuvable sur Kaggle'}), 404
        if upstream.status_code != 200:
            return jsonify({'error': f'Erreur source : {upstream.status_code}'}), 502

        # MIME type
        if url_param.endswith('.png'):
            ct = 'image/png'
        elif url_param.endswith(('.jpg', '.jpeg')):
            ct = 'image/jpeg'
        else:
            ct = 'video/mp4'

        filename = url_param.split('/')[-1] or 'benyjoe.mp4'

        def generate():
            for chunk in upstream.iter_content(chunk_size=65536):
                if chunk:
                    yield chunk

        resp = Response(stream_with_context(generate()), status=200, content_type=ct)
        resp.headers['Content-Disposition'] = f'attachment; filename="{filename}"'
        resp.headers['Accept-Ranges'] = 'bytes'
        if upstream.headers.get('Content-Length'):
            resp.headers['Content-Length'] = upstream.headers['Content-Length']
        return resp

    except requests.exceptions.ConnectionError:
        with state_lock:
            state['kaggle_url'] = None
        return jsonify({'error': 'Tunnel ngrok expiré'}), 503
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/stream/<jid>', methods=['GET'])
def api_stream_video(jid):
    """
    Stream MP4 pour le player HTML5.
    Supporte Range requests (seek dans la vidéo).
    """
    with jobs_lock:
        job = jobs_cache.get(jid, {})
    raw_url = job.get('result') or job.get('video_url', '')

    if not raw_url:
        return jsonify({'error': 'Vidéo non disponible'}), 404

    if not raw_url.startswith('http'):
        kaggle_base = get_kaggle_base()
        if not kaggle_base:
            return jsonify({'error': 'Kaggle non connecté'}), 503
        raw_url = f"{kaggle_base.rstrip('/')}/{raw_url.lstrip('/')}"

    try:
        headers = {}
        range_h = request.headers.get('Range')
        if range_h:
            headers['Range'] = range_h

        upstream = requests.get(raw_url, stream=True, timeout=30, headers=headers)
        status   = upstream.status_code  # 200 ou 206

        def generate():
            for chunk in upstream.iter_content(chunk_size=65536):
                if chunk:
                    yield chunk

        resp = Response(stream_with_context(generate()), status=status, content_type='video/mp4')
        resp.headers['Accept-Ranges'] = 'bytes'
        resp.headers['Cache-Control'] = 'no-cache'
        for h in ('Content-Length', 'Content-Range'):
            if h in upstream.headers:
                resp.headers[h] = upstream.headers[h]
        return resp

    except Exception as e:
        return jsonify({'error': str(e)}), 500


# ════════════════════════════════════════════════════════════════════════
#  GÉNÉRATION + JOBS
# ════════════════════════════════════════════════════════════════════════

@app.route('/api/generate', methods=['POST'])
def api_generate():
    data   = request.get_json(silent=True) or {}
    prompt = (data.get('prompt') or '').strip()
    if not prompt:
        return jsonify({'error': 'Prompt requis'}), 400
    with state_lock:
        kaggle_url = state.get('kaggle_url')
    if not kaggle_url:
        return jsonify({'error': 'Notebook Kaggle non connecté',
                        'help':  'Lancez les cellules 1 à 5 dans Kaggle'}), 503

    jid = str(uuid.uuid4())[:12]
    data['job_id'] = jid
    with jobs_lock:
        jobs_cache[jid] = {
            'id':        jid,
            'status':    'queued',
            'progress':  0,
            'step':      'Envoi au notebook Kaggle…',
            'result':    None,
            'video_url': None,
            'stream_url':None,
            'download_url':None,
            'error':     None,
            'prompt':    prompt,
            'type':      data.get('type','video'),
            'created':   datetime.now(timezone.utc).isoformat(),
        }

    def forward_async():
        resp, err = forward_to_kaggle('/generate', 'POST', data, timeout=30)
        with jobs_lock:
            if jid not in jobs_cache:
                return
            if err:
                jobs_cache[jid].update({'status':'error','error':err})
            elif resp and resp.status_code == 200:
                jobs_cache[jid].update({'status':'processing',
                                        'step':'Traitement sur Kaggle TPU…'})
            else:
                jobs_cache[jid].update({'status':'error',
                                        'error':f'Erreur Kaggle : {resp.status_code if resp else "?"}'})

    threading.Thread(target=forward_async, daemon=True).start()
    return jsonify({'job_id': jid, 'status': 'queued'}), 200


@app.route('/api/jobs/<jid>', methods=['GET'])
def api_job_status(jid):
    with jobs_lock:
        job = dict(jobs_cache.get(jid) or {})

    # Job done en cache local → retourner directement avec URLs
    if job.get('status') == 'done':
        return jsonify(job)

    # Interroger Kaggle pour le vrai statut
    resp, err = forward_to_kaggle(f'/api/jobs/{jid}', 'GET', timeout=10)
    if resp and resp.status_code == 200:
        kaggle_job = resp.json()

        # Injecter les URLs si done
        if kaggle_job.get('status') == 'done':
            raw = kaggle_job.get('result') or kaggle_job.get('video_url', '')
            if raw:
                kaggle_job.update(_build_video_urls(jid, raw))

        # Conserver video_url local si Render l'a déjà (depuis /api/video-ready)
        with jobs_lock:
            local = jobs_cache.get(jid, {})
            if local.get('video_url'):
                kaggle_job['video_url']    = local['video_url']
                kaggle_job['stream_url']   = local.get('stream_url',   f'/api/stream/{jid}')
                kaggle_job['download_url'] = local.get('download_url', '')
            jobs_cache[jid] = kaggle_job

        return jsonify(kaggle_job)

    if job:
        return jsonify(job)
    return jsonify({'error': err or 'Job introuvable'}), 503


@app.route('/api/jobs', methods=['GET'])
def api_all_jobs():
    with jobs_lock:
        return jsonify({'jobs': list(jobs_cache.values()), 'count': len(jobs_cache)})

@app.route('/api/videos', methods=['GET'])
def api_videos():
    with state_lock:
        return jsonify({'videos': state['videos']})


# ════════════════════════════════════════════════════════════════════════
#  STATUS / HEALTH
# ════════════════════════════════════════════════════════════════════════

def _get_status():
    with state_lock:
        kaggle_url    = state.get('kaggle_url')
        kaggle_device = state.get('kaggle_device')
        kaggle_seen   = state.get('kaggle_seen')
        nb_videos     = len(state['videos'])
    alive = False
    if kaggle_url:
        try:
            r = requests.get(f"{kaggle_url}/health", timeout=5)
            alive = r.status_code == 200
            if not alive:
                with state_lock: state['kaggle_url'] = None
        except Exception:
            with state_lock: state['kaggle_url'] = None
    return {
        'platform':         PLATFORM_NAME,
        'founder':          'KHEDIM BENYAKHLEF dit BENY-JOE',
        'kaggle_connected': alive,
        'kaggle_ready':     alive,   # ← utilisé par le frontend JS
        'connected':        alive,
        'kaggle_url':       kaggle_url if alive else None,
        'kaggle_device':    kaggle_device,
        'device':           kaggle_device,
        'kaggle_seen':      kaggle_seen,
        'videos_ready':     nb_videos,
        'timestamp':        datetime.now(timezone.utc).isoformat(),
    }

@app.route('/health',        methods=['GET'])
def health():        return jsonify({'status':'ok','service':PLATFORM_NAME}), 200

@app.route('/api/health',    methods=['GET'])   # ← fix bug frontend checkStatus
def api_health():    return jsonify(_get_status())

@app.route('/api/status',    methods=['GET'])
def api_status():    return jsonify(_get_status())

@app.route('/api/connexion', methods=['GET'])
def api_connexion(): return jsonify(_get_status())

@app.route('/api/ping',      methods=['GET'])
def api_ping():      return jsonify(_get_status())

@app.route('/api/tunnel',    methods=['GET'])
def api_tunnel():
    with state_lock: url = state.get('kaggle_url')
    return jsonify({'tunnel_url': url, 'active': url is not None})


# ════════════════════════════════════════════════════════════════════════
#  FRONTEND STATIC
# ════════════════════════════════════════════════════════════════════════

@app.route('/', methods=['GET'])
@login_required
def index():
    return send_from_directory(str(FRONTEND_DIR), 'index.html')

@app.route('/<path:path>', methods=['GET'])
def static_files(path):
    if path.startswith('api/'):
        abort(404)
    target = FRONTEND_DIR / path
    if target.exists() and target.is_file():
        return send_from_directory(str(FRONTEND_DIR), path)
    return send_from_directory(str(FRONTEND_DIR), 'index.html')


if __name__ == '__main__':
    log.info(f'🚀 {PLATFORM_NAME} — port {PORT}')
    app.run(host='0.0.0.0', port=PORT, debug=False)


# ════════════════════════════════════════════════════════════════════════
#  GOOGLE AUTH
# ════════════════════════════════════════════════════════════════════════
from flask_dance.contrib.google import make_google_blueprint, google
from functools import wraps
os.environ.setdefault('OAUTHLIB_RELAX_TOKEN_SCOPE', '1')
os.environ.setdefault('OAUTHLIB_INSECURE_TRANSPORT', '0')
google_bp = make_google_blueprint(
    client_id=os.environ.get('GOOGLE_CLIENT_ID'),
    client_secret=os.environ.get('GOOGLE_CLIENT_SECRET'),
    scope=['openid','https://www.googleapis.com/auth/userinfo.email','https://www.googleapis.com/auth/userinfo.profile'],
    redirect_url='/auth/google/authorized',
)
app.secret_key = os.environ.get('SECRET_KEY', os.environ.get('BENYJOE_SECRET','benyjoe-secret-2025'))
app.register_blueprint(google_bp, url_prefix='/auth')
ALLOWED_EMAIL = os.environ.get('ALLOWED_EMAIL','khedimbenyakhlef@gmail.com')
def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not google.authorized:
            return '<html><body style="text-align:center;margin-top:100px"><h2>BENY-JOE IA</h2><a href="/auth/google/login" style="padding:12px 24px;background:#4285F4;color:white;border-radius:6px;text-decoration:none">Se connecter avec Google</a></body></html>'
        info = google.get('/oauth2/v2/userinfo')
        if not info.ok:
            return '<h3>Erreur Auth</h3>', 500
        email = info.json().get('email','')
        if email != ALLOWED_EMAIL:
            return f'<h3>Acces refuse : {email}</h3>', 403
        return f(*args, **kwargs)
    return decorated
@app.route('/me')
def me():
    if not google.authorized:
        return jsonify({'connected': False})
    info = google.get('/oauth2/v2/userinfo')
    return jsonify(info.json() if info.ok else {'error': 'Auth error'})
