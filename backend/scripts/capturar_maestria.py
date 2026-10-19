"""
capturar_maestria.py — Capturas de pantalla de Maestr.ia para material de
video (tutorial de la beta). Uso interno, NO se despliega con la app.

    # Páginas públicas, sin sesión (headless):
    python backend/scripts/capturar_maestria.py --publicas

    # Primera vez: abre un navegador VISIBLE, iniciás sesión a mano y la
    # sesión queda guardada en .sesion_maestria.json:
    python backend/scripts/capturar_maestria.py

    # Siguientes veces: reutiliza la sesión guardada (headless):
    python backend/scripts/capturar_maestria.py --sesion-guardada

Opciones útiles: --base-url (default https://usemaestria.co), --grupo
"Octavo B" (grupo para chat/panel), --paginas (lista propia), --salida.

Contraseñas: el script NUNCA pide, lee, escribe ni registra una
contraseña — el login lo hacés vos a mano en la ventana. Lo que sí se
guarda en .sesion_maestria.json es el storage_state de Playwright
(cookies + localStorage), que incluye los tokens de sesión: quien tenga
ese archivo puede actuar como vos hasta que la sesión venza. Por eso se
escribe con permisos 600 y está en .gitignore. Para revocarlo: cerrá
sesión en la app (invalida el refresh token) y borrá el archivo.

Cada página se captura dos veces: `_viewport.png` (lo visible en
1920×1080) y `_completa.png` (página completa).

Restricciones del material para docentes beta (por defecto, desactivable
con --sin-ocultar): nunca se capturan páginas de admin, pagos, planes ni
precios (BLOQUEADAS), y antes de cada captura se ocultan los elementos de
OCULTAR_POR_DEFECTO (enlaces de admin, recuadro de plan, banners de
prueba/precios, secciones de precios de la portada).
"""
from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path

from playwright.sync_api import Page, sync_playwright
from playwright.sync_api import TimeoutError as PlaywrightTimeout

REPO_ROOT = Path(__file__).resolve().parents[2]
SESION = REPO_ROOT / ".sesion_maestria.json"
SALIDA_DEFAULT = REPO_ROOT / "assets_video"

VIEWPORT = {"width": 1920, "height": 1080}
LOCALE = "es-CO"
ESPERA_LOGIN_MS = 10 * 60 * 1000

PUBLICAS_DEFAULT = [
    "index.html",
    "registro.html",
    "login.html",
    "verificar-email.html",
    "recuperar-password.html",
]
APP_DEFAULT = ["dashboard.html", "grupos.html"]
# Además de APP_DEFAULT, con sesión se capturan chat.html y
# grupo-panel.html del grupo elegido (--grupo, o el primero).

# Nunca se capturan, aunque se pidan con --paginas: son del owner (admin,
# cohorte, reportes) o muestran planes/precios/pagos, que los docentes
# beta no deben ver.
BLOQUEADAS = {
    "admin-beta.html",
    "reportes.html",
    "precios.html",
    "pago-resultado.html",
    "trial-expirado.html",
    "cuenta.html",
    "terminos-uso.html",
}

OCULTAR_POR_DEFECTO = [
    "#link-admin-beta",
    "#link-reportes-admin",
    "#banner-migraciones-fallidas",
    "#plan-usage",
    "#banner-trial",
    'a[href="precios.html"]',
    'a[href="#precios"]',
    "section#precios",
    "section#para-colegios",
]

# Rutas a las que un login exitoso NO te deja — mientras la ventana siga
# en una de éstas, el script sigue esperando.
RUTAS_SIN_SESION = ("login.html", "registro.html", "verificar-email.html",
                    "recuperar-password.html", "nueva-password.html")


def _slug(texto: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", texto.lower()).strip("-") or "pagina"


def _nombre_archivo(pagina: str, sufijo: str = "") -> str:
    base = pagina.split("?")[0].removesuffix(".html")
    return _slug(base) + (f"_{_slug(sufijo)}" if sufijo else "")


def _validar_paginas(paginas: list[str]) -> list[str]:
    bloqueadas = [p for p in paginas if p.split("?")[0] in BLOQUEADAS]
    if bloqueadas:
        sys.exit(f"❌ Estas páginas están bloqueadas para el material de la beta: {', '.join(bloqueadas)}")
    return paginas


def _esperar_estable(page: Page) -> None:
    # networkidle nunca llega en páginas con socket.io: espera "best effort".
    try:
        page.wait_for_load_state("networkidle", timeout=8_000)
    except PlaywrightTimeout:
        pass
    page.evaluate(
        "() => Promise.race([document.fonts.ready, new Promise(r => setTimeout(r, 4000))])"
    )
    # Las secciones con animación "reveal on scroll" (IntersectionObserver)
    # salen en blanco en la captura de página completa si nunca entraron
    # al viewport: se recorre la página entera y se vuelve arriba.
    page.evaluate(
        """async () => {
            const paso = window.innerHeight * 0.8;
            for (let y = 0; y < document.body.scrollHeight; y += paso) {
                window.scrollTo(0, y);
                await new Promise(r => setTimeout(r, 150));
            }
            window.scrollTo(0, document.body.scrollHeight);
            await new Promise(r => setTimeout(r, 900));  // transiciones CSS (~0.6 s)
            window.scrollTo(0, 0);
        }"""
    )
    page.wait_for_timeout(600)


def _ocultar(page: Page, selectores: list[str]) -> list[str]:
    """Oculta los selectores presentes y devuelve cuáles había en la página."""
    if not selectores:
        return []
    return page.evaluate(
        """(sels) => sels.filter(sel => {
            const els = document.querySelectorAll(sel);
            els.forEach(el => el.style.setProperty('display', 'none', 'important'));
            return els.length > 0;
        })""",
        selectores,
    )


def capturar(page: Page, url: str, destino: Path, nombre: str, ocultar: list[str]) -> None:
    page.goto(url, wait_until="domcontentloaded", timeout=45_000)
    _esperar_estable(page)
    ocultos = _ocultar(page, ocultar)
    destino.mkdir(parents=True, exist_ok=True)
    page.screenshot(path=destino / f"{nombre}_viewport.png", animations="disabled")
    page.screenshot(path=destino / f"{nombre}_completa.png", full_page=True, animations="disabled")
    extra = f"  (ocultos: {', '.join(ocultos)})" if ocultos else ""
    print(f"  ✔ {nombre}{extra}")


def _hay_sesion(page: Page) -> bool:
    try:
        tiene_token = page.evaluate("() => !!localStorage.getItem('token')")
    except Exception:
        return False
    return tiene_token and not any(r in page.url for r in RUTAS_SIN_SESION)


def esperar_login_manual(page: Page, base_url: str) -> None:
    page.goto(f"{base_url}/login.html")
    print(
        "\n👉 Iniciá sesión en la ventana del navegador que se abrió.\n"
        "   El script NO pide ni ve tu contraseña: espera hasta que llegues al panel\n"
        f"   (máximo {ESPERA_LOGIN_MS // 60000} minutos).\n"
    )
    # Sondeo en Python (no wait_for_function): sobrevive a las navegaciones
    # del propio login sin que el contexto de evaluación se destruya. La
    # sesión tiene que sostenerse 3 sondeos seguidos: un token que la app
    # rechaza dura un instante antes de que vuelva a mandarte a login.html.
    transcurrido, seguidos = 0, 0
    while seguidos < 3:
        if transcurrido >= ESPERA_LOGIN_MS:
            sys.exit("❌ Se agotó la espera de login. Volvé a correr el script.")
        page.wait_for_timeout(1_000)
        transcurrido += 1_000
        seguidos = seguidos + 1 if _hay_sesion(page) else 0
    _esperar_estable(page)
    if not _hay_sesion(page):
        sys.exit("❌ La sesión no quedó activa después del login. Volvé a intentarlo.")


def guardar_sesion(context) -> None:
    context.storage_state(path=str(SESION))
    os.chmod(SESION, 0o600)
    print(f"🔐 Sesión guardada en {SESION.name} (permisos 600, en .gitignore).")


def grupos_de_la_sesion(page: Page) -> list[dict]:
    return page.evaluate(
        """async () => {
            const r = await fetch('/api/grupos', {
                headers: { Authorization: 'Bearer ' + localStorage.getItem('token') },
            });
            return r.ok ? r.json() : [];
        }"""
    )


def paginas_de_app(page: Page, base_url: str, nombre_grupo: str | None) -> list[tuple[str, str]]:
    """(ruta, nombre de archivo) de las páginas con sesión."""
    paginas = [(p, _nombre_archivo(p)) for p in APP_DEFAULT]
    page.goto(f"{base_url}/dashboard.html", wait_until="domcontentloaded")
    grupos = grupos_de_la_sesion(page)
    if nombre_grupo:
        grupos = [g for g in grupos if g.get("nombre_grupo") == nombre_grupo]
        if not grupos:
            sys.exit(f"❌ No hay ningún grupo llamado {nombre_grupo!r} en esta cuenta.")
    if grupos:
        g = grupos[0]
        for ruta in ("chat.html", "grupo-panel.html"):
            paginas.append((f"{ruta}?id={g['id_grupo']}", _nombre_archivo(ruta, g["nombre_grupo"])))
    else:
        print("  ℹ️  La cuenta no tiene grupos todavía — se omiten chat y panel de grupo.")
    return paginas


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    modo = parser.add_mutually_exclusive_group()
    modo.add_argument("--publicas", action="store_true", help="captura páginas sin sesión (headless)")
    modo.add_argument("--sesion-guardada", action="store_true", help=f"reutiliza {SESION.name} (headless)")
    parser.add_argument("--base-url", default="https://usemaestria.co")
    parser.add_argument("--salida", type=Path, default=SALIDA_DEFAULT)
    parser.add_argument("--grupo", help="nombre exacto del grupo para chat/panel (default: el primero)")
    parser.add_argument("--paginas", nargs="+", help="lista propia de páginas (reemplaza la default)")
    parser.add_argument("--sin-ocultar", action="store_true", help="no oculta admin/planes/precios")
    args = parser.parse_args()

    base_url = args.base_url.rstrip("/")
    ocultar = [] if args.sin_ocultar else OCULTAR_POR_DEFECTO

    with sync_playwright() as p:
        if args.publicas:
            paginas = _validar_paginas(args.paginas or PUBLICAS_DEFAULT)
            browser = p.chromium.launch(headless=True)
            context = browser.new_context(viewport=VIEWPORT, locale=LOCALE)
            page = context.new_page()
            print(f"📸 Páginas públicas de {base_url} → {args.salida / 'publicas'}")
            for ruta in paginas:
                capturar(page, f"{base_url}/{ruta}", args.salida / "publicas", _nombre_archivo(ruta), ocultar)
            browser.close()
            return

        if args.sesion_guardada:
            if not SESION.exists():
                sys.exit(f"❌ No existe {SESION.name}. Corré el script una vez sin --sesion-guardada para iniciar sesión.")
            browser = p.chromium.launch(headless=True)
            context = browser.new_context(viewport=VIEWPORT, locale=LOCALE, storage_state=str(SESION))
            page = context.new_page()
            page.goto(f"{base_url}/dashboard.html", wait_until="domcontentloaded")
            _esperar_estable(page)
            if not _hay_sesion(page):
                sys.exit(f"❌ La sesión guardada venció. Corré el script sin --sesion-guardada para renovarla.")
            # El frontend renueva el access token al cargar: se re-guarda
            # para que la próxima corrida arranque con tokens frescos.
            guardar_sesion(context)
        else:
            browser = p.chromium.launch(headless=False)
            context = browser.new_context(viewport=VIEWPORT, locale=LOCALE)
            page = context.new_page()
            esperar_login_manual(page, base_url)
            guardar_sesion(context)

        if args.paginas:
            paginas = [(r, _nombre_archivo(r)) for r in _validar_paginas(args.paginas)]
        else:
            paginas = paginas_de_app(page, base_url, args.grupo)
        print(f"📸 Páginas con sesión de {base_url} → {args.salida / 'app'}")
        for ruta, nombre in paginas:
            capturar(page, f"{base_url}/{ruta}", args.salida / "app", nombre, ocultar)
        browser.close()


if __name__ == "__main__":
    main()
