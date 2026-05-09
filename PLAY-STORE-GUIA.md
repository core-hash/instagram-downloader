# 🚀 Muse en Play Store — Guía completa

## Estado actual

✅ **Lo que ya está listo (yo lo hice):**
- Página `/privacy` deployada en https://muse-co.pages.dev/privacy
- `assetlinks.json` deployado con SHA-256 real del keystore
- Feature graphic 1024×500 generado (`web/playstore-feature.png`)
- 4 screenshots 1080×1920 generados (`web/playstore-screen-{1,2,3,4}.png`)
- Icono 512×512 listo (`web/icon-512.png`)
- Keystore generado (`android-app/android.keystore`)
- Copy completo del store listing (`PLAY-STORE-LISTING.md`)
- Configuración manifest PWA correcta para TWA

⚠️ **Lo que tienes que hacer tú (~2 horas total):**

---

## Paso 1: Generar el APK (5-10 min)

Sigue las instrucciones en **`android-app/README.md`** usando **PWABuilder.com**.

Output esperado:
- `app-release-bundle.aab` (este sube a Play)
- `app-release-signed.apk` (para distribución directa)

---

## Paso 2: Crear cuenta Play Console ($25 + ~1 día verificación)

1. Ve a https://play.google.com/console
2. Login con tu cuenta de Google personal o de empresa
3. Click **"Create developer account"**
4. Paga **$25 USD** one-time fee con tarjeta
5. Llena formulario de identidad:
   - Nombre completo (legal)
   - Dirección
   - Teléfono
   - País: Colombia
   - Tipo: Individual / Organization (recomiendo Organization si tienes RUT de Big Bang Brand)
6. Sube **foto de tu cédula/DNI** (frente y reverso)
7. Sube **selfie** sosteniendo el documento
8. Espera verificación (1-3 días hábiles típicamente)

Mientras esperas la verificación, puedes seguir armando la app — solo no podrás publicar hasta que verifiquen.

---

## Paso 3: Crear la app en Play Console (~30 min)

Ya verificado:

1. **All apps → Create app**
2. Llena:
   - **App name**: `Muse — Guarda lo que te inspira` (copia de PLAY-STORE-LISTING.md)
   - **Default language**: Spanish (Latin America) — `es-419`
   - **App or game**: App
   - **Free or paid**: Free
3. Acepta declaraciones (designed for families: NO; ads: NO; meets guidelines: YES)

---

## Paso 4: Llenar el store listing (~30 min)

Ve a **Grow → Store presence → Main store listing**.

Copia/pega todos los campos de **`PLAY-STORE-LISTING.md`**.

**Subir assets**:
- App icon → `web/icon-512.png`
- Feature graphic → `web/playstore-feature.png`
- Phone screenshots → `web/playstore-screen-{1,2,3,4}.png` (mínimo 2)

---

## Paso 5: Configurar privacidad y safety (~15 min)

1. **Policy → App content**:
   - Privacy policy URL: `https://muse-co.pages.dev/privacy`
   - Ads: **No** (no monetizamos con ads)
   - App access: All functionality available without restrictions
   - Content rating: Completar cuestionario (todo NO → resultado: PEGI 3 / Everyone)
   - Target audience: 13+
   - News app: No
   - COVID-19 contact tracing: No
   - Data safety: marcar **"No data collected"** y **"No data shared"**
   - Government app: No
   - Financial features: No

---

## Paso 6: Subir el bundle (~10 min)

1. **Production → Create new release**
2. **App bundles**: sube el `app-release-bundle.aab` que descargaste de PWABuilder
3. **Release name**: `1.0.0` (auto-detectado)
4. **Release notes**:
   ```
   Versión 1.0 — Lanzamiento inicial.
   • Descarga de Instagram, TikTok, X, Reddit, Pinterest
   • Calidad original sin marca de agua
   • PWA instalable como app nativa
   • Modo claro/oscuro automático
   • Sin login, sin cuenta, 100% gratis
   ```
5. **Save** → **Review release**

---

## Paso 7: Submit y esperar (1-7 días)

Click **Start rollout to production**.

Google revisa:
- Política de contenido
- Funcionamiento de la app
- Compatibilidad con dispositivos
- Verificación del Digital Asset Links (`/.well-known/assetlinks.json` ya deployado)

Recibirás email cuando aprueben (o rechacen con razón).

---

## ⚠️ Riesgo real de rejection

Ya te lo dije: apps que descargan de IG/TikTok han sido rechazadas o removidas (snaptik, savefromnet). Probabilidad ~30-40% de problemas en review.

**Si rechazan**, te dirán la razón. Soluciones típicas:
- "Violates intellectual property" → enfatizar más "uso personal" en descripción
- "Misleading description" → ajustar copy
- "Functionality issues" → testing más pulido

Si rechazan definitivamente, te quedan opciones:
- **F-Droid** (más amigable a este tipo de apps)
- **Distribución APK directa** desde muse-co.pages.dev/app
- **Aurora Store** (alternativa OSS a Play)

---

## Bonus: Distribución APK directa (incluso si Play aprueba, ten esto como backup)

PWABuilder también te da `app-release-signed.apk`. Súbelo a tu sitio:

1. Crea `web/app/index.html` con un link de descarga directa al `.apk`
2. Usuarios pueden bajarlo y sideloadear en Android (requiere "permitir fuentes desconocidas")
3. Si Play algún día baja Muse, esto sigue funcionando

Te lo armo cuando tengas el APK generado, dime.

---

## Resumen de archivos clave

| Archivo | Para qué |
|---|---|
| `android-app/android.keystore` | **GUARDA SIEMPRE**. Firma la app. Sin esto no puedes actualizar. |
| `android-app/README.md` | Instrucciones específicas del keystore + PWABuilder |
| `PLAY-STORE-LISTING.md` | Copia/pega esto en Play Console |
| `PLAY-STORE-GUIA.md` | Este archivo. La guía completa. |
| `web/icon-512.png` | App icon |
| `web/playstore-feature.png` | Feature graphic 1024×500 |
| `web/playstore-screen-1.png` ... `4.png` | Screenshots |
| `web/privacy.html` (deployed) | Política de privacidad |
| `web/.well-known/assetlinks.json` (deployed) | Validación de TWA |

Cualquier paso que se atasque, dime y te ayudo en vivo.
