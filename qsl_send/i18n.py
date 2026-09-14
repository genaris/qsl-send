"""Interface translation, chosen from the operating system's language.

Only the desktop window is translated. Command-line output, the README and the
config file stay in English, because those are read by whoever set the tool up
rather than by the colleagues using the window.

Why not ``locale.getdefaultlocale()``: on macOS it commonly reports ``('C',
'UTF-8')`` regardless of the user's actual language, because a GUI app inherits
no LANG. Each platform is therefore asked directly:

  * Windows — ``GetUserDefaultUILanguage`` (the language Windows' own menus use)
  * macOS   — ``AppleLanguages`` from the global preferences domain
  * Linux   — ``LC_ALL`` / ``LC_MESSAGES`` / ``LANG`` / ``LANGUAGE``

Override with the ``QSL_SEND_LANG`` environment variable, or a ``language:``
key in the configuration file.
"""

from __future__ import annotations

import os
import sys

DEFAULT_LANGUAGE = "en"
SUPPORTED = ("en", "es")

# Spanish interface strings. Keys are the English source text, so an untranslated
# string still renders correctly in English rather than showing a raw key.
_ES: dict[str, str] = {
    # window furniture
    "QSL Sender": "Enviador de QSL",
    "1. Files": "1. Archivos",
    "2. Card layout": "2. Diseño de la tarjeta",
    "3. Make and send the cards": "3. Crear y enviar las tarjetas",
    "What happened": "Qué pasó",
    # file rows
    "Card design": "Diseño de tarjeta",
    "Log file (ADIF)": "Archivo de log (ADIF)",
    "Save cards to": "Guardar tarjetas en",
    "Choose…": "Elegir…",
    "Choose your QSL card design": "Elegí el diseño de tu tarjeta QSL",
    "Choose your log file": "Elegí tu archivo de log",
    "Where should the cards be saved?": "¿Dónde se guardan las tarjetas?",
    # fields
    "Fields not checked yet.": "Todavía no se revisaron los campos.",
    "Find fields automatically": "Buscar campos automáticamente",
    "Show me…": "Mostrame…",
    # actions
    "Make the cards": "Crear las tarjetas",
    "Review who gets one…": "Revisar quién recibe una…",
    "Send a test to myself": "Enviarme una prueba",
    "Send the e-mails": "Enviar los correos",
    # dialogs
    "Send a test": "Enviar una prueba",
    "Send one test card to which address?":
        "¿A qué dirección enviamos la tarjeta de prueba?",
    "Still working — please wait.": "Todavía está trabajando — esperá un momento.",
    "Choose a card design first.": "Primero elegí un diseño de tarjeta.",
    "Choose a card design, a log file and a folder first.":
        "Primero elegí un diseño de tarjeta, un archivo de log y una carpeta.",
    "Make the cards first.": "Primero creá las tarjetas.",
    # status line
    "Choose a card design and a log file.":
        "Elegí un diseño de tarjeta y un archivo de log.",
    "Looking for the fields on the card…":
        "Buscando los campos en la tarjeta…",
    "Making the cards…": "Creando las tarjetas…",
    "No fields found.": "No se encontraron campos.",
    "Something went wrong — see the log below.":
        "Algo salió mal — mirá el detalle abajo.",
    # log messages
    "No fields found. The boxes may not be a flat colour.":
        "No se encontraron campos. Puede que los recuadros no sean de un color plano.",
    "Nothing to show — no fields were found.":
        "No hay nada para mostrar — no se encontraron campos.",
    "Names are guessed from left-to-right order — use 'Show me…' to check them on the card.":
        "Los nombres se deducen del orden de izquierda a derecha — usá «Mostrame…» "
        "para verificarlos sobre la tarjeta.",
    "Test sent. Nobody was marked as having received a card.":
        "Prueba enviada. No se marcó a nadie como que ya recibió su tarjeta.",
    "Cancelled — nothing was sent.": "Cancelado — no se envió nada.",
    "Nobody left to send to.": "No queda nadie a quien enviarle.",
    # summary bar
    "Callsign": "Indicativo",
    "Sends from": "Envía desde",
    "Language": "Idioma",
    "Saving to": "Guardando en",
    "follows the computer": "sigue a la computadora",
    "Settings…": "Configuración…",
    # settings dialog
    "Settings": "Configuración",
    "You": "Vos",
    "E-mail": "Correo",
    "Behaviour": "Comportamiento",
    "Save": "Guardar",
    "Cancel": "Cancelar",
    "Your callsign": "Tu indicativo",
    "'auto' follows the computer's own language.":
        "«auto» sigue el idioma de la computadora.",
    "Server": "Servidor",
    "Port": "Puerto",
    "Your name": "Tu nombre",
    "Your address": "Tu dirección",
    "Sign in as": "Iniciar sesión como",
    "Password": "Contraseña",
    "Show": "Mostrar",
    "For Gmail this is a 16-character App Password, not your normal password.":
        "Para Gmail es una contraseña de aplicación de 16 caracteres, "
        "no tu contraseña habitual.",
    "by {callsign}": "por {callsign}",
    "Created a settings file at {path}":
        "Se creó un archivo de configuración en {path}",
    "Could not create a settings file at {path}.":
        "No se pudo crear un archivo de configuración en {path}.",
    # credentials check before sending
    "E-mail settings": "Configuración de correo",
    "your own e-mail address": "tu propia dirección de correo",
    "your password": "tu contraseña",
    "your own sign-in address": "tu propia dirección de inicio de sesión",
    "Before sending, {missing} is needed in Settings.\n\nOpen Settings now?":
        "Antes de enviar hace falta {missing} en Configuración.\n\n"
        "¿Abrir Configuración ahora?",
    # output-folder confirmation
    "Check the folder": "Revisá la carpeta",
    "Continue anyway?": "¿Continuar igual?",
    "Cancelled — nothing was written.": "Cancelado — no se escribió nada.",
    # address book tab
    "E-mail": "Correo",
    "Name": "Nombre",
    "Contact": "Contacto",
    "Add…": "Agregar…",
    "Edit…": "Editar…",
    "Remove": "Quitar",
    "OK": "Aceptar",
    "Addresses and names you looked up yourself. These win over the log and QRZ.":
        "Direcciones y nombres que buscaste vos. Tienen prioridad sobre el log y QRZ.",
    "Enter a callsign.": "Ingresá un indicativo.",
    "That does not look like an e-mail address.":
        "Eso no parece una dirección de correo.",
    "Enter an e-mail address, a name, or both.":
        "Ingresá una dirección de correo, un nombre, o ambos.",
    "Remove {callsign} from the address book?":
        "¿Quitar {callsign} de la libreta de direcciones?",
    "Add the {count} missing contact(s) now?":
        "¿Agregar ahora {count} contacto(s) que faltan?",
    # missing-contacts prompt on the main window
    "Complete the address book…": "Completar la libreta…",
    "{count} contact(s) are missing a name or an address: {calls}":
        "A {count} contacto(s) les falta nombre o dirección: {calls}",
    # message tab
    "Message": "Mensaje",
    "Subject": "Asunto",
    "Message text": "Texto del mensaje",
    "You can use: {placeholders}": "Podés usar: {placeholders}",
    "Preview…": "Vista previa…",
    "Preview": "Vista previa",
    "Close": "Cerrar",
    "Save cards to": "Guardar tarjetas en",
    "Address book": "Libreta de direcciones",
    "Pause between e-mails": "Pausa entre correos",
    "Skip contacts with no e-mail address":
        "Saltear contactos sin dirección de correo",
    "The port must be a whole number.":
        "El puerto tiene que ser un número entero.",
    "The pause must be a number of seconds.":
        "La pausa tiene que ser un número de segundos.",
    "The new language will be used next time you open the window.":
        "El nuevo idioma se va a usar la próxima vez que abras la ventana.",
    "No settings file was found, so there is nothing to edit.":
        "No se encontró un archivo de configuración, así que no hay nada para editar.",
    "Saved {count} setting(s).": "Se guardaron {count} opción(es).",
    # parameterised messages ({} placeholders are preserved)
    "Looking at {name} …": "Mirando {name} …",
    "Found {count} fields in {rows} row(s):":
        "Se encontraron {count} campos en {rows} fila(s):",
    "{count} fields found automatically.":
        "{count} campos encontrados automáticamente.",
    "Found {count} fields.": "Se encontraron {count} campos.",
    "{count} fields configured.": "{count} campos configurados.",
    "Saved a marked-up copy to {path}":
        "Se guardó una copia marcada en {path}",
    "Opened {path} — check the addresses before sending.":
        "Se abrió {path} — revisá las direcciones antes de enviar.",
    "Could not read the settings file: {error}":
        "No se pudo leer el archivo de configuración: {error}",
    "! Address book problem: {error}":
        "! Problema con la libreta de direcciones: {error}",
    "Sending {count} e-mail(s)…": "Enviando {count} correo(s)…",
    "Sent {sent} of {total}.": "Se enviaron {sent} de {total}.",
    "{cards} cards made · {ready} ready to e-mail · {missing} with no address":
        "{cards} tarjetas creadas · {ready} listas para enviar · "
        "{missing} sin dirección",
    "Something went wrong: {error}": "Algo salió mal: {error}",
    "Send the e-mails\n\nThis will e-mail {count} operator(s) — for real.\n\n"
    "Anyone who already received their card will be skipped.\n\nSend now?":
        "Enviar los correos\n\nEsto le va a enviar un correo a {count} "
        "operador(es) — de verdad.\n\nSe va a saltear a quien ya recibió su "
        "tarjeta.\n\n¿Enviar ahora?",
    "This build of Python has no tkinter, so the window cannot open.\n"
    "On Windows, install Python from python.org (tkinter is included).":
        "Esta instalación de Python no tiene tkinter, así que no se puede abrir "
        "la ventana.\nEn Windows, instalá Python desde python.org (incluye tkinter).",
}

_CATALOGUES: dict[str, dict[str, str]] = {"en": {}, "es": _ES}

_active = DEFAULT_LANGUAGE


def _normalise(tag: str | None) -> str | None:
    """'es-AR', 'es_AR.UTF-8', 'Spanish' -> 'es', if supported."""
    if not tag:
        return None
    tag = tag.strip().replace("_", "-").split(".")[0].lower()
    if not tag or tag in ("c", "posix"):
        return None
    primary = tag.split("-")[0]
    return primary if primary in SUPPORTED else None


def _windows_language() -> str | None:
    try:
        import ctypes

        # The language Windows' own menus are displayed in.
        lang_id = ctypes.windll.kernel32.GetUserDefaultUILanguage()  # type: ignore[attr-defined]
        buf = ctypes.create_unicode_buffer(85)
        if ctypes.windll.kernel32.LCIDToLocaleName(lang_id, buf, 85, 0):  # type: ignore[attr-defined]
            return buf.value
        # Fall back to the primary-language bits of the LCID (0x0A == Spanish).
        return {0x0A: "es", 0x09: "en"}.get(lang_id & 0x3FF)
    except Exception:
        return None


def _macos_language() -> str | None:
    try:
        import subprocess

        out = subprocess.run(
            ["defaults", "read", "-g", "AppleLanguages"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        for line in out.stdout.splitlines():
            tag = line.strip().strip('(),"').strip()
            got = _normalise(tag)
            if got:
                return got
    except Exception:
        return None
    return None


def _posix_language() -> str | None:
    for key in ("LC_ALL", "LC_MESSAGES", "LANG", "LANGUAGE"):
        got = _normalise(os.environ.get(key, "").split(":")[0])
        if got:
            return got
    return None


def detect_language() -> str:
    """The language to use, honouring an explicit override first."""
    forced = _normalise(os.environ.get("QSL_SEND_LANG"))
    if forced:
        return forced

    if sys.platform.startswith("win"):
        found = _windows_language() or _posix_language()
        found = _normalise(found) if found and found not in SUPPORTED else found
    elif sys.platform == "darwin":
        found = _macos_language() or _posix_language()
    else:
        found = _posix_language()
    return found or DEFAULT_LANGUAGE


def set_language(language: str | None) -> str:
    """Set the active language. Falls back to detection, then English."""
    global _active
    _active = _normalise(language) or detect_language()
    return _active


def get_language() -> str:
    return _active


def t(text: str, **kwargs) -> str:
    """Translate `text`, then fill in any {placeholders}."""
    out = _CATALOGUES.get(_active, {}).get(text, text)
    if kwargs:
        try:
            return out.format(**kwargs)
        except (KeyError, IndexError):
            return text.format(**kwargs)
    return out
