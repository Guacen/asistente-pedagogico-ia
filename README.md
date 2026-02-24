# 🚀 ASISTENTE PEDAGÓGICO IA - GUÍA DE INSTALACIÓN EN HOSTINGER

Esta es la guía completa para subir tu aplicación web a Hostinger.

---

## 📁 ESTRUCTURA DE ARCHIVOS

Tu hosting debe tener esta estructura:

```
/public_html/  (o /htdocs/ según tu hosting)
├── index.html
├── login.html
├── registro.html
├── dashboard.html
├── chat.html
├── grupos.html
├── cuenta.html
├── precios.html
│
├── css/
│   ├── main.css
│   └── chat.css
│
├── js/
│   ├── config.js          ← IMPORTANTE: Editar URLs aquí
│   ├── api.js
│   ├── auth.js
│   ├── chat.js
│   ├── grupos.js
│   └── main.js
│
├── img/
│   └── logo.svg
│
└── .htaccess              ← Reglas de servidor
```

---

## 🔧 PASO 1: CONFIGURAR EL BACKEND

### Opción A: Backend en Railway (Recomendado)

1. **Crea cuenta en Railway.app:**
   - Ve a https://railway.app
   - Regístrate gratis (tienes $5 de crédito)

2. **Despliega el backend FastAPI:**
   - Sube tu código backend a GitHub
   - Conecta Railway con tu repo
   - Railway detectará FastAPI automáticamente
   - Obtendrás una URL como: `https://tu-app.railway.app`

3. **Anota tu URL del backend:**
   ```
   API_URL: https://tu-backend.railway.app
   WS_URL: wss://tu-backend.railway.app
   ```

### Opción B: Backend en Render.com

Similar a Railway, también gratuito para empezar.

### Opción C: Backend en tu propio servidor

Si tienes un VPS, instala:
```bash
# En tu servidor Ubuntu
sudo apt update
sudo apt install python3 python3-pip
pip3 install fastapi uvicorn sqlalchemy psycopg2-binary python-socketio

# Ejecutar backend
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

---

## 📤 PASO 2: SUBIR ARCHIVOS A HOSTINGER

### Método 1: Via File Manager (Panel de Control)

1. **Accede a hPanel de Hostinger:**
   - Inicia sesión en hostinger.com
   - Ve a "Panel de Control"

2. **Abre el File Manager:**
   - Busca "Administrador de Archivos"
   - Navega a `/public_html/`

3. **Sube los archivos:**
   - Selecciona "Subir archivos"
   - Arrastra todas las carpetas y archivos
   - Mantén la estructura de carpetas

### Método 2: Via FTP (Recomendado)

1. **Descarga FileZilla:**
   - https://filezilla-project.org/

2. **Obtén credenciales FTP:**
   - En hPanel → "Cuentas FTP"
   - Anota: Host, Usuario, Contraseña, Puerto (21)

3. **Conéctate:**
   - Abre FileZilla
   - Ingresa credenciales
   - Conecta

4. **Sube archivos:**
   - Panel izquierdo: Tu computadora
   - Panel derecho: Servidor Hostinger
   - Arrastra todos los archivos a `/public_html/`

---

## ⚙️ PASO 3: CONFIGURAR LAS URLs

**MUY IMPORTANTE:** Edita `js/config.js` con tus URLs reales:

```javascript
// js/config.js
const CONFIG = {
    // Cambia esta URL por la de tu backend
    API_URL: 'https://TU-BACKEND.railway.app',  // ← CAMBIAR
    WS_URL: 'wss://TU-BACKEND.railway.app',     // ← CAMBIAR
    
    // Si usas Stripe para pagos (opcional)
    STRIPE_PUBLIC_KEY: 'pk_test_...',  // ← CAMBIAR si usas Stripe
    
    APP_NAME: 'Asistente Pedagógico IA',
    VERSION: '1.0.0'
};
```

**Ejemplo real:**
```javascript
API_URL: 'https://asistente-pedagogico-api.railway.app',
WS_URL: 'wss://asistente-pedagogico-api.railway.app',
```

---

## 🌐 PASO 4: CONFIGURAR .htaccess (Para URLs Limpias)

Crea un archivo `.htaccess` en `/public_html/`:

```apache
# Habilitar mod_rewrite
RewriteEngine On

# Si el archivo no existe, redirigir a index.html
RewriteCond %{REQUEST_FILENAME} !-f
RewriteCond %{REQUEST_FILENAME} !-d
RewriteRule ^(.*)$ index.html [L,QSA]

# Forzar HTTPS (opcional pero recomendado)
RewriteCond %{HTTPS} off
RewriteRule ^(.*)$ https://%{HTTP_HOST}%{REQUEST_URI} [L,R=301]

# Headers de seguridad
<IfModule mod_headers.c>
    Header set X-Content-Type-Options "nosniff"
    Header set X-Frame-Options "SAMEORIGIN"
    Header set X-XSS-Protection "1; mode=block"
</IfModule>

# Comprimir archivos
<IfModule mod_deflate.c>
    AddOutputFilterByType DEFLATE text/html text/plain text/xml text/css text/javascript application/javascript
</IfModule>

# Cache de recursos estáticos
<IfModule mod_expires.c>
    ExpiresActive On
    ExpiresByType image/jpg "access plus 1 year"
    ExpiresByType image/jpeg "access plus 1 year"
    ExpiresByType image/png "access plus 1 year"
    ExpiresByType image/svg+xml "access plus 1 year"
    ExpiresByType text/css "access plus 1 month"
    ExpiresByType application/javascript "access plus 1 month"
</IfModule>
```

---

## 🔒 PASO 5: CONFIGURAR SSL (HTTPS)

**Hostinger te da SSL gratis:**

1. En hPanel → "SSL"
2. Activa "SSL Gratuito" (Let's Encrypt)
3. Espera 10-15 minutos
4. Tu sitio estará en `https://tu-dominio.com`

---

## 🧪 PASO 6: PROBAR LA APLICACIÓN

1. **Abre tu sitio:**
   ```
   https://tu-dominio.com
   ```

2. **Prueba el registro:**
   - Ve a "Crear cuenta"
   - Registra un usuario de prueba

3. **Revisa la consola del navegador:**
   - F12 → Consola
   - NO debe haber errores rojos
   - Si hay errores de CORS, configura CORS en tu backend

4. **Prueba el login:**
   - Inicia sesión con el usuario creado

5. **Crea un grupo:**
   - Dashboard → Crear grupo

6. **Prueba el chat:**
   - Click en el grupo
   - Envía un mensaje
   - Verifica que la IA responda

---

## 🐛 SOLUCIÓN DE PROBLEMAS COMUNES

### Error: "Failed to fetch"

**Causa:** El frontend no puede conectar con el backend.

**Solución:**
1. Verifica que la URL en `config.js` sea correcta
2. Verifica que tu backend esté ejecutándose
3. Abre `https://TU-BACKEND.railway.app/docs` (debe mostrar la API)

### Error: "CORS policy"

**Causa:** El backend no permite peticiones desde tu dominio.

**Solución en backend (FastAPI):**
```python
from fastapi.middleware.cors import CORSMiddleware

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "https://tu-dominio.com",
        "http://localhost:3000"  # Para desarrollo
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
```

### Error: "WebSocket connection failed"

**Causa:** Socket.io no puede conectar.

**Solución:**
1. Verifica `WS_URL` en `config.js`
2. Debe ser `wss://` (con 's') si tu frontend es HTTPS
3. Verifica que tu backend soporte WebSockets

### El sitio no carga, muestra error 404

**Causa:** Archivo `.htaccess` mal configurado.

**Solución:**
1. Verifica que `.htaccess` esté en `/public_html/`
2. Verifica que `mod_rewrite` esté habilitado (Hostinger lo tiene por defecto)

### Imágenes o CSS no cargan

**Causa:** Rutas incorrectas.

**Solución:**
- Las rutas en HTML deben ser relativas: `css/main.css` (sin `/` al inicio)
- O absolutas desde la raíz: `/css/main.css`

---

## 📊 PASO 7: MONITOREO Y ANALÍTICAS (Opcional)

### Google Analytics

1. Crea una cuenta en https://analytics.google.com
2. Obtén tu ID de seguimiento (G-XXXXXXXXXX)
3. Agrega este código ANTES de `</head>` en todos los HTML:

```html
<!-- Google Analytics -->
<script async src="https://www.googletagmanager.com/gtag/js?id=G-XXXXXXXXXX"></script>
<script>
  window.dataLayer = window.dataLayer || [];
  function gtag(){dataLayer.push(arguments);}
  gtag('js', new Date());
  gtag('config', 'G-XXXXXXXXXX');
</script>
```

### Sentry (Para errores)

1. Crea cuenta en https://sentry.io
2. Crea proyecto JavaScript
3. Agrega el SDK en todos los HTML:

```html
<script src="https://browser.sentry-cdn.com/7.x.x/bundle.min.js"></script>
<script>
  Sentry.init({
    dsn: "https://tu-dsn@sentry.io/proyecto",
    environment: "production"
  });
</script>
```

---

## 🔄 PASO 8: ACTUALIZACIONES FUTURAS

Cuando hagas cambios:

1. **Edita archivos localmente**
2. **Prueba en local** (abre index.html en navegador)
3. **Sube via FTP** solo los archivos modificados
4. **Limpia caché del navegador** (Ctrl+Shift+R)

---

## 💰 COSTOS ESTIMADOS

| Servicio | Costo | Notas |
|----------|-------|-------|
| **Hostinger** | $2-4/mes | Hosting compartido |
| **Dominio** | $10-15/año | .com o .co |
| **Backend (Railway)** | $5/mes | Free tier primero |
| **SSL** | GRATIS | Incluido en Hostinger |
| **TOTAL** | ~$10/mes | Para empezar |

---

## 📞 SOPORTE

Si tienes problemas:

1. **Revisa la consola del navegador** (F12)
2. **Revisa logs del backend** (Railway → Logs)
3. **Hostinger tiene soporte 24/7** via chat

---

## ✅ CHECKLIST FINAL

Antes de lanzar públicamente:

- [ ] Todas las URLs en `config.js` están correctas
- [ ] SSL está activado (https://)
- [ ] El backend está funcionando (puedes abrir /docs)
- [ ] Puedes registrarte y hacer login
- [ ] Puedes crear grupos
- [ ] El chat funciona y la IA responde
- [ ] Los estilos se ven correctos (no hay CSS roto)
- [ ] No hay errores en consola del navegador
- [ ] El sitio funciona en móvil
- [ ] `.htaccess` está configurado
- [ ] Backup de archivos localmente

---

## 🚀 ¡LISTO!

Tu aplicación ahora está en vivo en:
```
https://tu-dominio.com
```

Comparte el link con tus docentes beta testers y empieza a recibir feedback.

---

## 📝 PRÓXIMOS PASOS

1. **Marketing:**
   - Crea página en redes sociales
   - Graba video demo
   - Contacta secretarías de educación

2. **Mejoras técnicas:**
   - Agrega Google Analytics
   - Configura backups automáticos
   - Implementa sistema de pagos (Stripe)

3. **Investigación:**
   - Recolecta datos de uso
   - Entrevistas con docentes
   - Métricas de impacto

---

¿Necesitas ayuda con algún paso? ¡Pregúntame!
