# AI Brain — Public Website Deployment (Render)

இந்த package-ல் உள்ள code Render-ல் deploy செய்யத் தயாராக அமைக்கப்பட்டுள்ளது. User database மற்றும் uploads-ஐ source code-ல் சேர்க்கவில்லை; privacy மற்றும் security காரணமாக அவை புதிதாக உருவாகும்.

## GitHub upload
1. ZIP-ஐ extract செய்யவும்.
2. GitHub-ல் `ai-brain` என்ற repository உருவாக்கவும். Private repository பரிந்துரைக்கப்படுகிறது.
3. இந்த folder-இன் உள்ளடக்கங்களை upload/push செய்யவும்.
4. `.env` அல்லது API key-களை repository-ல் சேர்க்க வேண்டாம்.

## Render deploy
1. https://dashboard.render.com/ திறந்து GitHub repository-ஐ connect செய்யவும்.
2. `render.yaml` பயன்படுத்தி Blueprint deploy செய்யவும், அல்லது Web Service-ஐ manual-ஆக உருவாக்கவும்.
3. Build command: `pip install -r requirements.txt`
4. Start command: `gunicorn --workers 1 --threads 4 --timeout 120 app:app`
5. Environment variables-ல் உங்களுக்குச் சொந்தமான valid AI provider API key-ஐ சேர்க்கவும். `SECRET_KEY`-க்கு Render உருவாக்கும் value-ஐ பயன்படுத்தவும்.
6. Deploy முடிந்ததும் Render வழங்கும் `https://....onrender.com` URL-ஐ திறந்து register/login மற்றும் AI features-ஐ test செய்யவும்.

## Custom domain
Render service → Settings → Custom Domains → உங்கள் domain-ஐ add செய்யவும். Render காட்டும் DNS records-ஐ domain provider DNS-ல் அமைக்கவும். DNS verification மற்றும் HTTPS முடிந்ததும் custom domain public-ஆக வேலை செய்யும்.

## Important notes
- `render.yaml`-ல் persistent disk அமைக்கப்பட்டுள்ளது; இதற்கு paid Render instance தேவைப்படலாம்.
- Existing local `.db` files மற்றும் uploaded documents ZIP-ல் சேர்க்கப்படவில்லை. Deploy செய்ததும் புதிய database உருவாகும்.
- API key இல்லாமல் AI routes வேலை செய்யாமல் இருக்கலாம்; keys-ஐ Render Environment பகுதியில் மட்டும் சேர்க்கவும்.
- Desktop reminder popups/Windows notifications local Windows app feature; hosted Linux server-ல் user-ன் PC-க்கு system popup காட்ட முடியாது.
- Public website-ஐ பகிர்வதற்கு முன் registration, login, file upload, AI chat, mobile layout ஆகியவற்றை test செய்யவும்.
