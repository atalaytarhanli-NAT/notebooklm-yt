# notebooklm-yt — Progress Log

Kişisel mobil/masaüstü web uygulaması: YouTube'da ara → seç → NotebookLM'e gönder → podcast/rapor/quiz/zihin haritası üret → indir.

---

## 2026-05-01 — v0.1 ilk deploy

### Tamamlandı

| Adım | Durum | Not |
|---|---|---|
| Mimari karar (tek-kullanıcı, FastAPI + Tailwind) | ✅ | NotebookLM public API yok, cookie-based auth zorunlu |
| Backend: FastAPI iskelet + bearer token auth + config | ✅ | `app/main.py`, `app/auth.py`, `app/config.py` |
| Backend: YouTube search endpoint | ✅ | yt-dlp, `extract_flat: 'in_playlist'` ile bot-challenge bypass |
| Backend: NotebookLM endpoints | ✅ | List/create notebook, add sources, generate (audio/report/quiz/mind-map), artifact list/download |
| Frontend: Mobil-uyumlu UI | ✅ | Tek `index.html` + tek `app.js`, Tailwind CDN, build step yok |
| Deploy config | ✅ | `render.yaml`, `runtime.txt`, `.env.example`, `.gitignore` |
| Lokal smoke test | ✅ | YouTube search 200 OK; NotebookLM uçları kod doğru, auth rate-limit nedeniyle CLI taze cookie istedi |
| GitHub repo + push | ✅ | https://github.com/atalaytarhanli-NAT/notebooklm-yt (public) |
| Render deploy | ⏳ | URL: https://notebooklm-yt.onrender.com — env var set ediliyor |

### Yapılacak (sonraki oturum)

- [ ] Render `APP_TOKEN` env var doğrulanacak
- [ ] Render `NOTEBOOKLM_AUTH_JSON` env var taze cookie ile yenilenecek (önceki oturum cookie'leri rotate edilmeli)
- [ ] Auto-redeploy bittikten sonra production smoke test:
  - [ ] `/api/health` → 200
  - [ ] `/api/auth/check` → `{ok: true}`
  - [ ] `/api/youtube/search?q=test&n=3` → sonuç
  - [ ] Mobil tarayıcıdan login + arama + 1 video ekleme + rapor üretme
- [ ] Cookie expiration playbook'unu README'de README'de doğrulan (cep telefonundan refresh akışı)

---

## Mimari özet

### Stack
- **Backend:** FastAPI 0.115 + yt-dlp 2026.03+ + notebooklm-py 0.3.4 + Pydantic 2
- **Frontend:** Tailwind CDN + vanilla JS, mobile-first (env safe-area, sticky header, FAB)
- **Auth:** Bearer token (`APP_TOKEN`) — kullanıcı tek; localStorage'da cache
- **NotebookLM auth:** `NOTEBOOKLM_AUTH_JSON` env var (storage_state.json içeriği)
- **Deploy:** Render free tier web service, `render.yaml` blueprint
- **Repo:** Public GitHub (kod açık, secrets env var)

### Tradeoff'lar (bilinen)
- **Tek kullanıcı:** NotebookLM cookie-based auth, multi-user mümkün değil.
- **Cookie ~30 günde expire:** Aylık manuel yenileme ritüeli (~30 sn).
- **Render free tier 15 dk inaktivitede uyur:** İlk istek 30 sn cold start. Audio üretim sırasında dyno uyanık kalır.
- **YouTube extract_flat:** Bot-challenge'ı bypass eder ama `upload_date` boş döner.

### Klasör yapısı
```
notebooklm-yt/
├── app/
│   ├── __init__.py
│   ├── main.py          # FastAPI app, route'lar, static mount
│   ├── auth.py          # Bearer token middleware
│   ├── config.py        # pydantic-settings
│   ├── youtube.py       # yt-dlp wrapper
│   ├── nlm.py           # NotebookLM client wrapper
│   └── static/
│       ├── index.html   # UI
│       └── app.js       # Frontend logic
├── render.yaml
├── requirements.txt
├── runtime.txt
├── .env.example
├── .gitignore
├── README.md
└── PROGRESS.md          # bu dosya
```

---

## Cookie yenileme playbook'u

Render `/api/auth/check` `{ok: false, error: "Authentication expired"}` dönüyorsa:

```powershell
# 1. Tarayıcıda fresh login
notebooklm login

# 2. İçeriği panoya al (terminale yazma!)
((Get-Content "$env:USERPROFILE\.notebooklm\storage_state.json" -Raw) -replace "`r`n","") | Set-Clipboard

# 3. Render Dashboard → notebooklm-yt → Environment → NOTEBOOKLM_AUTH_JSON → Value: Ctrl+V → Save
# 4. Render otomatik redeploy eder (~1-2 dk)
```

---

## Env vars referans

| Var | Kaynak | Açıklama |
|---|---|---|
| `APP_TOKEN` | `secrets.token_urlsafe(32)` | Panel parolası |
| `NOTEBOOKLM_AUTH_JSON` | `storage_state.json` içeriği | Google session cookies |
| `NOTEBOOKLM_HOME` | `/tmp/notebooklm` | Render ephemeral path |
| `ARTIFACTS_DIR` | `/tmp/notebooklm-artifacts` | İndirme cache |
| `CORS_ORIGINS` | `*` | Cross-origin (gerekirse domain-specific yap) |
