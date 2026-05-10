# 🎬 BENY-JOE IA — Plateforme de Génération Vidéo & Image HD

> **Fondée par KHEDIM BENYAKHLEF dit BENY-JOE**

[![Deploy on Render](https://render.com/images/deploy-to-render-button.svg)](https://render.com/deploy)

---

## 📐 Architecture

```
┌─────────────────────────────────────────────────────────┐
│  BENY-JOE IA — Architecture Complète                   │
├──────────────────┬──────────────────┬───────────────────┤
│  Kaggle Notebook │   Backend Render │  Frontend HTML5   │
│  (TPU v5e)       │   (Flask)        │  (Public URL)     │
│                  │                  │                   │
│  AnimateDiff     │  /api/generate   │  Interface Studio │
│  SD 1.5          │  /api/jobs       │  Génération       │
│  MusicGen        │  /api/health     │  Suivi temps réel │
│  gTTS voix       │  /api/kaggle-url │  Téléchargement   │
│       ↕ ngrok    │       ↕          │       ↕           │
│  Flask :8765 ────┼──→ Render URL ←─┼── User Browser    │
└──────────────────┴──────────────────┴───────────────────┘
```

---

## 🚀 Déploiement sur Render

### 1. Fork ou upload ce projet sur GitHub

```bash
git init
git add .
git commit -m "BENY-JOE IA v1.0"
git remote add origin https://github.com/VOTRE_USERNAME/benyjoe-ia
git push -u origin main
```

### 2. Créer un Web Service sur Render

- Connectez votre compte Render → **New Web Service**
- Sélectionnez votre repo GitHub
- Render détectera automatiquement `render.yaml`

### 3. Variables d'environnement Render

| Variable | Valeur |
|---|---|
| `BENYJOE_SECRET` | Clé secrète générée auto par Render |
| `FLASK_ENV` | `production` |
| `OUTPUTS_DIR` | `/tmp/outputs` |

### 4. Récupérer l'URL Render

Après le déploiement, copiez l'URL (ex : `https://benyjoe-ia.onrender.com`)

---

## 🧠 Notebook Kaggle

### Configuration

1. Ouvrez `notebook/BENYJOE_IA_Kaggle.ipynb` dans Kaggle
2. Activez l'accélérateur **TPU v5e** dans les paramètres
3. Activez **Internet** dans les paramètres
4. Ajoutez vos secrets dans Kaggle → Settings → Secrets :
   - `GITHUB_TOKEN` — Token GitHub (pour upload vidéos)
   - `NGROK_TOKEN` — Token ngrok (pour tunnel public)

### Dans la Cellule 5

Remplacez `RENDER_URL` par votre URL Render :
```python
RENDER_URL = "https://benyjoe-ia.onrender.com"  # ← Votre URL
```

### Ordre d'exécution

| Cellule | Action |
|---|---|
| **Cellule 0** | Vérification TPU |
| **Cellule 1** | Chargement secrets |
| **Cellule 2** | Installation dépendances (~10 min) |
| **Cellule 3** | Chargement modèles (~5 min) |
| **Cellule 4** | Flask + ngrok (laissez tourner) |
| **Cellule 5** | Auto-push + Watcher (laissez tourner) |
| **Cellule Diag** | Vérification (facultative) |

---

## 📦 Stack Technique

| Composant | Technologie |
|---|---|
| **Génération vidéo** | AnimateDiff v3 + Stable Diffusion 1.5 |
| **Génération image** | Stable Diffusion 1.5 |
| **Voix OFF** | gTTS (FR / EN / AR) |
| **Musique IA** | MusicGen-medium (Meta / Facebook) |
| **Accélérateur** | TPU v5e — Kaggle |
| **Tunnel** | ngrok |
| **Backend** | Flask + Gunicorn |
| **Frontend** | HTML5 + CSS3 + JS Vanilla |
| **Déploiement** | Render (Web Service) |
| **Résolution** | 1024×576 Full HD 16:9 |
| **Format sortie** | MP4 H.264 + AAC |

---

## 🗂 Structure du Projet

```
BENY-JOE-IA/
├── backend/
│   ├── app.py              # Serveur Flask principal
│   └── requirements.txt    # Dépendances Python
├── frontend/
│   └── public/
│       ├── index.html      # Interface utilisateur complète
│       └── favicon.svg     # Logo BENY-JOE IA
├── notebook/
│   └── BENYJOE_IA_Kaggle.ipynb   # Notebook Kaggle (8 cellules)
├── outputs/                # Dossier vidéos (local dev)
├── render.yaml             # Config déploiement Render
└── README.md               # Cette documentation
```

---

## 🔗 Communication Notebook ↔ Plateforme

```
Kaggle Notebook
     │
     ├─ Cellule 4 → Flask :8765 + ngrok tunnel
     │                    │
     │                    ├─→ POST /api/kaggle-url    (enregistre l'URL ngrok)
     │                    │
     │  Cellule 5 ────────┤
     │  (watcher)         ├─→ POST /api/video-ready  (notifie vidéo prête)
     │                    │
     └──────────────────────→ POST /api/jobs/{id}/progress (progression)

Frontend ──── GET /api/health    → status + kaggle_ready
         ──── POST /api/generate → crée un job, forward vers Kaggle
         ──── GET /api/jobs/{id} → poll progression (toutes 2.5s)
```

---

## ⚡ Fonctionnalités

- ✅ Génération **vidéo longue durée** (jusqu'à 60 secondes)
- ✅ Génération **image HD** (1024×1024 / 1024×576 / 576×1024)
- ✅ **Animation** d'images via AnimateDiff
- ✅ **Voix OFF** multilingue (Français, Anglais, Arabe)
- ✅ **Musique IA** (Cinématique, Électronique, Ambient, Épique, Oriental)
- ✅ **Suivi temps réel** de la progression
- ✅ **Téléchargement direct** des vidéos
- ✅ **File de jobs** avec historique
- ✅ **Upload GitHub** automatique des vidéos

---

## 👤 À Propos

**BENY-JOE IA** est une plateforme de génération de contenu multimédia par intelligence artificielle.

**Fondateur** : KHEDIM BENYAKHLEF dit **BENY-JOE**

---

*BENY-JOE IA © 2025 — KHEDIM BENYAKHLEF*
