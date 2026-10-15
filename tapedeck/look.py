"""The bundled look: TAPEDECK brings its own GTK theme, icons and fonts (share/, made by
tools/vendor-look), so it looks the same on every desktop instead of inheriting whatever theme
the user runs. Only the window frame still comes from the window manager.

prepare() must run before Gtk is imported: GTK finds themes through XDG_DATA_DIRS, which GLib
reads once and caches. The variable is put back afterwards, so child processes (librespot,
systemctl, the browser for login) see the user's own environment.
"""
import ctypes
import ctypes.util
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SHARE = os.path.join(ROOT, "share")
GTK_THEME = "TAPEDECK-IndigoMagic"
ICON_THEME = "TAPEDECK-SE98"
UI_FONT = "Fira Code 10"
FONTS = ("VT323-Regular.ttf", "FiraCode-Regular.ttf", "FiraCode-Bold.ttf")


def _add_fonts():
    """Register the bundled fonts with fontconfig for this process only (nothing is installed)."""
    lib = ctypes.util.find_library("fontconfig")
    if not lib:
        return
    fc = ctypes.CDLL(lib)
    fc.FcConfigAppFontAddFile.argtypes = [ctypes.c_void_p, ctypes.c_char_p]
    for name in FONTS:
        fc.FcConfigAppFontAddFile(None, os.path.join(SHARE, "fonts", name).encode())


def prepare():
    if os.environ.get("TAPEDECK_SYSTEM_THEME"):     # opt out: inherit the desktop's theme
        return
    _add_fonts()
    old = os.environ.get("XDG_DATA_DIRS")
    os.environ["XDG_DATA_DIRS"] = SHARE + ":" + (old or "/usr/local/share:/usr/share")
    from gi.repository import GLib
    GLib.get_system_data_dirs()                       # GLib caches the list here
    if old is None:
        del os.environ["XDG_DATA_DIRS"]
    else:
        os.environ["XDG_DATA_DIRS"] = old


def apply():
    """After Gtk is imported: select the bundled theme. Application-set values win over XSETTINGS."""
    if os.environ.get("TAPEDECK_SYSTEM_THEME"):
        return
    from gi.repository import Gtk
    s = Gtk.Settings.get_default()
    s.props.gtk_theme_name = GTK_THEME
    s.props.gtk_icon_theme_name = ICON_THEME
    s.props.gtk_font_name = UI_FONT
    s.props.gtk_application_prefer_dark_theme = False
