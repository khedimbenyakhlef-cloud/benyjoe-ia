/**
 * BENY-JOE IA — Frontend API Client
 * Fondé par KHEDIM BENYAKHLEF dit BENY-JOE
 *
 * Ce fichier gère toute la communication entre le frontend
 * et le serveur Render (qui lui-même communique avec Kaggle).
 *
 * À inclure dans votre index.html :
 *   <script src="benyjoe-api.js"></script>
 */

const BenyJoeAPI = (() => {

  // ── Configuration ──────────────────────────────────────────────────
  const BASE_URL      = '';          // Même origine (Render)
  const POLL_INTERVAL = 3000;        // ms entre chaque poll de statut job
  const STATUS_INTERVAL = 10000;    // ms entre chaque poll statut Kaggle

  // ── État interne ───────────────────────────────────────────────────
  let kaggleConnected = false;
  let statusPollTimer = null;
  let activePolls     = {};    // { jid: timer }

  // ── Callbacks configurables par le frontend ────────────────────────
  const callbacks = {
    onKaggleStatusChange: null,   // (connected, device) => {}
    onJobProgress:        null,   // (jid, job) => {}
    onJobDone:            null,   // (jid, videoUrl) => {}
    onJobError:           null,   // (jid, errorMsg) => {}
  };

  // ══════════════════════════════════════════════════════════════════
  //  POLLING STATUT KAGGLE (toutes les 10s)
  // ══════════════════════════════════════════════════════════════════

  async function pollKaggleStatus() {
    try {
      const r = await fetch(`${BASE_URL}/api/status`, { cache: 'no-store' });
      if (!r.ok) return;
      const data = await r.json();
      const wasConnected = kaggleConnected;
      kaggleConnected = data.kaggle_connected === true;

      // Notifier seulement si changement
      if (wasConnected !== kaggleConnected || !wasConnected) {
        if (callbacks.onKaggleStatusChange) {
          callbacks.onKaggleStatusChange(kaggleConnected, data.kaggle_device);
        }
        updateKaggleUI(kaggleConnected, data.kaggle_device);
      }
    } catch (e) {
      // Serveur Render inaccessible
      console.warn('[BenyJoeAPI] Status poll failed:', e.message);
    }
  }

  function updateKaggleUI(connected, device) {
    // Met à jour les indicateurs visuels si présents
    const indicator = document.querySelector('.kaggle-status, #kaggle-status');
    if (!indicator) return;
    if (connected) {
      indicator.textContent = `⚡ Notebook connecté${device ? ` (${device})` : ''}`;
      indicator.style.color = '#00ff88';
    } else {
      indicator.textContent = '⚠️ Notebook Kaggle non connecté — lancez les cellules 1→6';
      indicator.style.color = '#ff8800';
    }
  }

  function startStatusPolling() {
    pollKaggleStatus();  // Immédiat
    statusPollTimer = setInterval(pollKaggleStatus, STATUS_INTERVAL);
  }

  function stopStatusPolling() {
    if (statusPollTimer) {
      clearInterval(statusPollTimer);
      statusPollTimer = null;
    }
  }

  // ══════════════════════════════════════════════════════════════════
  //  GÉNÉRATION
  // ══════════════════════════════════════════════════════════════════

  /**
   * Lance une génération vidéo/image/animation.
   * @param {Object} params
   *   - prompt       {string}  Description du contenu
   *   - type         {string}  'video' | 'image' | 'animation'
   *   - resolution   {string}  '1024x576' | '512x512' | ...
   *   - duration     {number}  Durée vidéo en secondes
   *   - fps          {number}  Images par seconde
   *   - frames       {number}  Nombre de frames
   *   - voice        {boolean} Activer voix OFF
   *   - voice_lang   {string}  'fr' | 'en' | 'ar'
   *   - music        {boolean} Activer musique IA
   *   - music_style  {string}  'cinematic' | 'electronic' | 'ambient' | 'epic' | 'oriental'
   * @returns {Promise<string>} job_id
   */
  async function generate(params) {
    if (!kaggleConnected) {
      throw new Error('Notebook Kaggle non connecté. Assurez-vous que la Cellule 4 tourne.');
    }

    const r = await fetch(`${BASE_URL}/api/generate`, {
      method:  'POST',
      headers: { 'Content-Type': 'application/json' },
      body:    JSON.stringify(params),
    });

    const data = await r.json();

    if (!r.ok) {
      throw new Error(data.error || `Erreur serveur : ${r.status}`);
    }

    if (!data.job_id) {
      throw new Error('Pas de job_id retourné');
    }

    // Démarrer le polling pour ce job
    startJobPoll(data.job_id);
    return data.job_id;
  }

  // ══════════════════════════════════════════════════════════════════
  //  POLLING JOB
  // ══════════════════════════════════════════════════════════════════

  function startJobPoll(jid) {
    if (activePolls[jid]) return;  // Déjà en cours

    activePolls[jid] = setInterval(async () => {
      try {
        const r = await fetch(`${BASE_URL}/api/jobs/${jid}`, { cache: 'no-store' });
        if (!r.ok) return;
        const job = await r.json();

        // Notifier progression
        if (callbacks.onJobProgress) {
          callbacks.onJobProgress(jid, job);
        }

        // Terminé
        if (job.status === 'done') {
          stopJobPoll(jid);
          const videoUrl = job.video_url || job.result || null;
          if (callbacks.onJobDone) {
            callbacks.onJobDone(jid, videoUrl, job);
          }
        }

        // Erreur
        if (job.status === 'error') {
          stopJobPoll(jid);
          if (callbacks.onJobError) {
            callbacks.onJobError(jid, job.error || 'Erreur inconnue');
          }
        }
      } catch (e) {
        console.warn(`[BenyJoeAPI] Poll job ${jid} :`, e.message);
      }
    }, POLL_INTERVAL);
  }

  function stopJobPoll(jid) {
    if (activePolls[jid]) {
      clearInterval(activePolls[jid]);
      delete activePolls[jid];
    }
  }

  // ══════════════════════════════════════════════════════════════════
  //  INITIALISATION
  // ══════════════════════════════════════════════════════════════════

  function init(userCallbacks = {}) {
    Object.assign(callbacks, userCallbacks);
    startStatusPolling();
    console.log('[BenyJoeAPI] Initialisé — BENY-JOE IA by KHEDIM BENYAKHLEF');
  }

  // ══════════════════════════════════════════════════════════════════
  //  INTERFACE PUBLIQUE
  // ══════════════════════════════════════════════════════════════════

  return {
    init,
    generate,
    stopJobPoll,
    isKaggleConnected: () => kaggleConnected,

    /**
     * Exemple d'utilisation dans votre frontend :
     *
     * BenyJoeAPI.init({
     *   onKaggleStatusChange: (ok, device) => {
     *     document.getElementById('btn-generate').disabled = !ok;
     *   },
     *   onJobProgress: (jid, job) => {
     *     progressBar.style.width = job.progress + '%';
     *     stepLabel.textContent = job.step;
     *   },
     *   onJobDone: (jid, videoUrl) => {
     *     videoEl.src = videoUrl;
     *     videoEl.play();
     *   },
     *   onJobError: (jid, err) => {
     *     alert('Erreur : ' + err);
     *   }
     * });
     *
     * // Lancer une génération :
     * const jid = await BenyJoeAPI.generate({
     *   prompt:      'Un coucher de soleil sur le Sahara',
     *   type:        'video',
     *   resolution:  '1024x576',
     *   duration:    15,
     *   fps:         24,
     *   frames:      32,
     *   voice:       true,
     *   voice_lang:  'fr',
     *   music:       true,
     *   music_style: 'oriental',
     * });
     */
  };

})();

// Auto-init si DOM prêt
if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', () => BenyJoeAPI.init());
} else {
  BenyJoeAPI.init();
}
