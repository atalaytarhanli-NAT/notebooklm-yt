# notebooklm-yt

Mobil uyumlu kişisel kontrol paneli: YouTube'da ara → seç → NotebookLM'e kaynak olarak gönder → podcast / rapor / quiz / zihin haritası üret → indir.

**Tek kullanıcılı:** NotebookLM'in public API'si yok, kendi Google oturum cookie'nle çalışır. Telefon, tablet ve masaüstünden tek hesaba bağlanır.

---

## Stack

- **Backend:** FastAPI + yt-dlp + [notebooklm-py](https://pypi.org/project/notebooklm-py/)
- **Frontend:** Tailwind CDN + vanilla JS (build step yok)
- **Auth:** Bearer token (tek kullanıcı)
- **Deploy:** Render (Free tier)

---

## Lokal kurulum

```bash
python -m venv .venv
.venv/Scripts/activate     # Windows
# source .venv/bin/activate # macOS/Linux
pip install -r requirements.txt

# 1. NotebookLM login (browser açar, oturumu kaydeder)
notebooklm login

# 2. Storage'ı env var olarak oku
#    (Bu dosyayı tek satıra çevirmeden NOTEBOOKLM_AUTH_JSON'a verme; library doğrudan path okuyor.)
#    Lokal'de NOTEBOOKLM_HOME default olarak ~/.notebooklm — yani sadece env dosyası ayarlamak yeterli.

# 3. .env oluştur
cp .env.example .env
#   APP_TOKEN= satırına güçlü bir rastgele string yapıştır
#   python -c "import secrets; print(secrets.token_urlsafe(32))"

# 4. Çalıştır
uvicorn app.main:app --reload
# → http://127.0.0.1:8000
```

---

## Render'a deploy

1. Bu repo'yu GitHub'a push et.
2. Render Dashboard → **New → Blueprint** → repo'yu bağla. `render.yaml` otomatik algılanır.
3. **Environment variables**:
   - `APP_TOKEN`: güçlü rastgele string
   - `NOTEBOOKLM_AUTH_JSON`: `~/.notebooklm/storage_state.json` dosyasının **tüm içeriği** (tek satır JSON)

```bash
# Storage'ı kopyalamak için:
cat ~/.notebooklm/storage_state.json | tr -d '\n'
# çıktıyı Render env var'ına yapıştır
```

4. Deploy bitince `/api/health` 200 dönerse hazır.
5. URL'yi telefondan aç → token'ı gir → kullan.

---

## Cookie yenileme (ayda bir, tek komut)

Google oturum cookie'leri ~30 günde bir expire eder. Hata: `NotebookLM auth failed`.

### Bir kerelik setup

1. **Render API key oluştur:** https://dashboard.render.com/u/settings → API Keys → "Create API Key" → kopyala
2. **Service ID'yi bul:** Render Dashboard → notebooklm-yt → URL'deki ID (örn `srv-xxxxx`)
3. **Render env var'larına ekle:**
   - `RENDER_API_KEY` = (yeni oluşturduğun key)
   - `RENDER_SERVICE_ID` = (`srv-...`)
   - **Save Changes** → redeploy
4. **Lokalde APP_TOKEN'ı PowerShell profile'a ekle** (her seferinde set etmemek için):
   ```powershell
   notepad $PROFILE
   # şu satırı ekle:
   $env:APP_TOKEN = "b_XK1Tn4OOJX..."
   ```

### Aylık akış (~2 dk)

```powershell
.\scripts\refresh-cookie.ps1
```

Bu script:
1. `notebooklm login` çalıştırır → tarayıcıda Google girişi yapsın
2. `storage_state.json`'ı okur
3. App'in `/api/admin/refresh-auth` endpoint'ine POST eder
4. Endpoint, Render API üzerinden `NOTEBOOKLM_AUTH_JSON` env var'ı update eder
5. Render otomatik redeploy başlatır
6. `/api/auth/check` `{ok: true}` dönene kadar bekler

### Manuel fallback (script çalışmazsa)

```powershell
notebooklm login
((Get-Content "$env:USERPROFILE\.notebooklm\storage_state.json" -Raw) -replace "`r`n","") | Set-Clipboard
# → Render Dashboard → Environment → NOTEBOOKLM_AUTH_JSON → Value: Ctrl+V → Save
```

---

## API hızlı referans

Tüm endpoint'ler `Authorization: Bearer <APP_TOKEN>` ister.

| Method | Path | Açıklama |
|---|---|---|
| GET | `/api/health` | Sağlık (auth gerekmez) |
| GET | `/api/auth/check` | NotebookLM auth doğrulama |
| GET | `/api/youtube/search?q=&n=` | YouTube arama |
| GET | `/api/notebooks` | Defter listele |
| POST | `/api/notebooks` | `{title}` |
| POST | `/api/sources/add` | `{notebook_id, urls[]}` |
| GET | `/api/notebooks/{id}/sources` | Kaynak listesi |
| POST | `/api/generate/audio` | Podcast üret |
| POST | `/api/generate/report` | Rapor üret |
| POST | `/api/generate/quiz` | Quiz üret |
| POST | `/api/generate/mind-map` | Zihin haritası |
| GET | `/api/notebooks/{id}/artifacts` | Üretilenleri listele |
| GET | `/api/notebooks/{id}/artifacts/{aid}/download?type=` | İndir |

---

## Bilinen kısıtlar

- **Tek kullanıcı:** NotebookLM cookie multi-user değil. Bu uygulamayı sadece sen kullan.
- **Render Free tier:** 15 dk inaktivitede uyur, ilk istek 30 sn bekleyebilir. Audio üretim 10-20 dk sürer; bu sürede dyno uyanık kalır.
- **YouTube IP blokları:** Render IP'leri bazen YouTube tarafından flag'lenir. Yaşarsan yt-dlp'ye proxy/cookie eklemek gerekir.
- **Cookie expiration:** Aylık manuel yenileme.

---

## Güvenlik notları

- `APP_TOKEN` ve `NOTEBOOKLM_AUTH_JSON` git'e **asla** commit'leme — `.gitignore` koruyor ama yine de dikkat.
- Token'ı tarayıcıda `localStorage`'da saklıyor; cihazını ödünç verirsen `Çıkış` yap.
- HTTPS zorunlu (Render bunu otomatik veriyor).
