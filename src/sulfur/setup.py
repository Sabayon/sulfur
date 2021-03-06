# -*- coding: utf-8 -*-
#    Sulfur (Entropy Interface)
#    Copyright: (C) 2007-2009 Fabio Erculiani < lxnay<AT>sabayonlinux<DOT>org >
#
#    This program is free software; you can redistribute it and/or modify
#    it under the terms of the GNU General Public License as published by
#    the Free Software Foundation; either version 2 of the License, or
#    (at your option) any later version.
#
#    This program is distributed in the hope that it will be useful,
#    but WITHOUT ANY WARRANTY; without even the implied warranty of
#    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#    GNU General Public License for more details.
#
#    You should have received a copy of the GNU General Public License
#    along with this program; if not, write to the Free Software
#    Foundation, Inc., 675 Mass Ave, Cambridge, MA 02139, USA.

import os
import sys
from entropy.const import etpConst
from entropy.i18n import _
import entropy.tools

class const:

    __sulfur_version__   = etpConst['entropyversion']

    DAY_IN_SECONDS = 86400
    # Page -> Notebook page numbers
    PAGE_REPOS = 1
    PAGE_PKG = 0
    PAGE_OUTPUT = 4
    PAGE_FILESCONF = 2
    PAGE_PREFERENCES = 3
    PAGES = {
       'packages'  : PAGE_PKG,
       'repos'     : PAGE_REPOS,
       'output'    : PAGE_OUTPUT,
       'filesconf' : PAGE_FILESCONF,
       'preferences': PAGE_PREFERENCES
    }

    PREF_PAGE_SYSTEM = 0
    PREF_PAGE_NETWORKING = 1
    PREF_PAGE_UGC = 2
    PREF_PAGE_COLORS = 3
    PREF_PAGES = {
        'system': PREF_PAGE_SYSTEM,
        'networking': PREF_PAGE_NETWORKING,
        'ugc': PREF_PAGE_UGC,
        'colors': PREF_PAGE_COLORS
    }

    PACKAGE_PROGRESS_STEPS = ( 0.1, # Depsolve
                               0.5, # Download
                               0.1, # Transaction Test
                               0.3 ) # Running Transaction

    SETUP_PROGRESS_STEPS = ( 0.1, # Yum Config
                             0.2, # Repo Setup
                             0.1, # Sacksetup
                             0.2, # Updates
                             0.1, # Group
                             0.3) # get package Lists

    CREDITS = (
           (('Sulfur Package Manager - %s' % __sulfur_version__),
           ('Copyright 2007-2009', 'Fabio Erculiani')),

           (_("Programming:"),
           ("Fabio Erculiani",)),

           (_("Translation:"),
            (
                "ca - Roger Calvó",
                "de - Karl Kochs",
                "es - Daniel Halens Rodriguez",
                "fr - Suffys Nicolas",
                "fr_CA - Benjamin Guay",
                "it - Fabio Erculiani",
                "nl - Andre Parhan",
		"pl - Enlik",
                "pt - Lucas Paulino Azevedo",
                "ru - Maksim Belyanovskiy",
                "sk - Bystrík Pešl",
                "sv - Patrik Karlsson",
                "zh - N/A",
                )
            ),


           (_("Dedicated to:"),
                ("Sergio Erculiani",)
           )

          )

    debug = '--debug' in sys.argv
    if os.getenv('SULFUR_DEBUG') is not None:
        debug = True

    home = os.getenv("HOME")
    if not home:
        home = "/tmp"
    SETTINGS_FILE = os.path.join(home, ".config/entropy/sulfur.conf")

    MAIN_PATH = os.path.abspath( os.path.dirname( sys.argv[0] ) )
    GLADE_FILE = MAIN_PATH+'/sulfur.glade'

    if not os.path.isfile(GLADE_FILE):
        GLADE_FILE = MAIN_PATH+'/sulfur/sulfur.glade'

    if not os.path.isfile(GLADE_FILE):
        MAIN_PATH = '/usr/lib/entropy/sulfur'
        GLADE_FILE = MAIN_PATH+'/sulfur/sulfur.glade'

    ORIG_PIXMAPS_PATH = '/usr/share/pixmaps/sulfur'
    ORIG_ICONS_PATH = '/usr/share/pixmaps/sulfur'
    PIXMAPS_PATH = None
    ICONS_PATH = None
    pkg_pixmap = None
    ugc_small_pixmap = None
    ugc_pixmap = None
    ugc_pixmap_small = None
    refresh_pixmap = None
    star_normal_pixmap = None
    star_selected_pixmap = None
    star_half_pixmap = None
    star_empty_pixmap = None
    empty_background = None
    loading_pix = None
    loading_pix_small = None
    ugc_ok_pix = None
    ugc_error_pix = None
    ugc_generic_pix = None
    ugc_text_pix = None
    ugc_video_pix = None
    ugc_image_pix = None
    ugc_view_pix = None

    @staticmethod
    def setup():

        if const.MAIN_PATH == '/usr/lib/entropy/sulfur':
            const.ICONS_PATH = const.ORIG_ICONS_PATH
        else:
            const.ICONS_PATH = const.MAIN_PATH+'/pixmaps'
            if (not os.access(const.ICONS_PATH, os.R_OK)) and \
                os.access(const.ORIG_ICONS_PATH, os.R_OK):
                const.ICONS_PATH = const.ORIG_ICONS_PATH

        if const.MAIN_PATH == '/usr/lib/entropy/sulfur':
            const.PIXMAPS_PATH = const.ORIG_PIXMAPS_PATH
        else:
            const.PIXMAPS_PATH = const.MAIN_PATH+'/../gfx'
            if (not os.access(const.PIXMAPS_PATH, os.R_OK)) and \
                os.access(const.ORIG_PIXMAPS_PATH, os.R_OK):
                const.PIXMAPS_PATH = const.ORIG_PIXMAPS_PATH

        const.pkg_pixmap = const.PIXMAPS_PATH+'/package-x-generic.png'
        const.ugc_small_pixmap = const.PIXMAPS_PATH+'/ugc.png'
        const.ugc_pixmap = const.PIXMAPS_PATH+'/ugc/icon.png'
        const.ugc_pixmap_small = const.PIXMAPS_PATH+'/ugc/icon_small.png'
        const.refresh_pixmap = const.PIXMAPS_PATH+'/ugc/refresh.png'
        const.star_normal_pixmap = const.PIXMAPS_PATH+'/star.png'
        const.star_selected_pixmap = const.PIXMAPS_PATH+'/star_selected.png'
        const.star_half_pixmap = const.PIXMAPS_PATH+'/star_half.png'
        const.star_empty_pixmap = const.PIXMAPS_PATH+'/star_empty.png'
        const.empty_background = const.PIXMAPS_PATH+'/empty.png'
        const.loading_pix = const.PIXMAPS_PATH+'/loading.gif'
        const.loading_pix_small = const.PIXMAPS_PATH+'/loading_small.gif'

        const.ugc_ok_pix = const.PIXMAPS_PATH+'/ugc/ok.png'
        const.ugc_error_pix = const.PIXMAPS_PATH+'/ugc/error.png'
        const.ugc_generic_pix = const.PIXMAPS_PATH+'/ugc/generic.png'
        const.ugc_text_pix = const.PIXMAPS_PATH+'/ugc/text.png'
        const.ugc_video_pix = const.PIXMAPS_PATH+'/ugc/video.png'
        const.ugc_image_pix = const.PIXMAPS_PATH+'/ugc/image.png'
        const.ugc_view_pix = const.PIXMAPS_PATH+'/ugc/view.png'

const.setup()

class SulfurConf:

    autorefresh = True
    recentdays = 14
    debug = False
    plugins = True
    usecache = False
    relaxed_deps = 0
    proxy = ""
    font_console = 'Monospace 8'
    font_pkgdesc = 'Monospace 8'
    entropy_uri = 'entropy://'

    color_console_font = '#FFFFFF' # black
    color_normal = '#000000' # black
    color_install = '#418C0F' # dark green
    color_update = '#418C0F' #  dark green
    color_remove = '#A71B1B' # red
    color_reinstall = '#A71B1B'
    color_downgrade = '#A71B1B'
    color_title = '#A71B1B' # red
    color_title2 = '#E03ADE' # light purple
    # description below package atoms
    color_pkgdesc = '#9c7234' # brown
    # description for masked packages and for pkg description in dialogs, notice board desc items
    color_pkgsubtitle = '#418C0F' # dark green
    color_subdesc = '#837350' # brown
    color_error = '#A71B1B' # red
    color_good = '#418C0F' # dark green
    color_background_good = '#418C0F' # red
    color_background_error = '#A71B1B' # dark green
    color_good_on_color_background = '#FFFFFF'
    color_error_on_color_background = '#FFFFFF'
    color_package_category = '#9C7234' # brown
    simple_mode = 1
    show_startup_tips = 1

    filelist = True
    changelog = False
    disable_repo_page = False
    branding_title = 'Entropy Store'
    dummy_empty = 0
    dummy_category = 1

    @staticmethod
    def getconf_validators():

        def validate_color_conf(s):
            try:
                import gtk
                gtk.gdk.color_parse(s)
                return True
            except ValueError:
                return False

        def foo_validator(s):
            return True

        config_data = {
            "color_console_font": validate_color_conf,
            "color_normal": validate_color_conf,
            "color_install": validate_color_conf,
            "color_update": validate_color_conf,
            "color_remove": validate_color_conf,
            "color_reinstall": validate_color_conf,
            "color_downgrade": validate_color_conf,
            "color_title": validate_color_conf,
            "color_title2": validate_color_conf,
            "color_pkgdesc": validate_color_conf,
            "color_pkgsubtitle": validate_color_conf,
            "color_subdesc": validate_color_conf,
            "color_error": validate_color_conf,
            "color_good": validate_color_conf,
            "color_background_good": validate_color_conf,
            "color_background_error": validate_color_conf,
            "color_good_on_color_background": validate_color_conf,
            "color_error_on_color_background": validate_color_conf,
            "color_package_category": validate_color_conf,
            "simple_mode": foo_validator,
            "relaxed_deps": foo_validator,
            "show_startup_tips": foo_validator,
        }
        return config_data

    @staticmethod
    def getconf():

        config_data = {
            "color_console_font": SulfurConf.color_console_font,
            "color_normal": SulfurConf.color_normal,
            "color_install": SulfurConf.color_install,
            "color_update": SulfurConf.color_update,
            "color_remove": SulfurConf.color_remove,
            "color_reinstall": SulfurConf.color_reinstall,
            "color_downgrade": SulfurConf.color_downgrade,
            "color_title": SulfurConf.color_title,
            "color_title2": SulfurConf.color_title2,
            "color_pkgdesc": SulfurConf.color_pkgdesc,
            "color_pkgsubtitle": SulfurConf.color_pkgsubtitle,
            "color_subdesc": SulfurConf.color_subdesc,
            "color_error": SulfurConf.color_error,
            "color_good": SulfurConf.color_good,
            "color_background_good": SulfurConf.color_background_good,
            "color_background_error": SulfurConf.color_background_error,
            "color_good_on_color_background": SulfurConf.color_good_on_color_background,
            "color_error_on_color_background": SulfurConf.color_error_on_color_background,
            "color_package_category": SulfurConf.color_package_category,
            "simple_mode": SulfurConf.simple_mode,
            "relaxed_deps": SulfurConf.relaxed_deps,
            "show_startup_tips": SulfurConf.show_startup_tips,
        }
        return config_data

    @staticmethod
    def save():

        def do_save():
            if not os.path.isdir(os.path.dirname(const.SETTINGS_FILE)):
                os.makedirs(os.path.dirname(const.SETTINGS_FILE), 0o755)
            myxml = entropy.tools.xml_from_dict_extended(SulfurConf.getconf())
            try:
                f = open(const.SETTINGS_FILE, "w")
            except (IOError, OSError,) as e:
                return False, e
            f.write(myxml+"\n")
            f.flush()
            f.close()
            return True, None

        try:
            return do_save()
        except Exception as e:
            entropy.tools.print_traceback()
            return False, e
        return True, None

    @staticmethod
    def read():

        def do_read():
            if os.path.isfile(const.SETTINGS_FILE) and os.access(const.SETTINGS_FILE, os.R_OK):
                f = open(const.SETTINGS_FILE, "r")
                xml_string = f.read()
                f.close()
                return entropy.tools.dict_from_xml_extended(xml_string)

        try:
            return do_read()
        except:
            entropy.tools.print_traceback()
            return None

    @staticmethod
    # update config reading it from user settings
    def update():
        saved_conf = SulfurConf.read()
        validators = SulfurConf.getconf_validators()
        if not saved_conf: return
        if not isinstance(saved_conf, dict): return
        for key, val in list(saved_conf.items()):
            if not hasattr(SulfurConf, key): continue
            vf = validators.get(key)
            if not hasattr(vf, '__call__'):
                sys.stderr.write("WARNING: SulfurConf, no callable validator for %s" % (key,))
                continue
            valid = vf(val)
            if not valid: continue
            setattr(SulfurConf, key, val)

SulfurConf.default_colors_config = SulfurConf.getconf()
SulfurConf.update()

def cleanMarkupString(msg):
    import gobject
    msg = str(msg) # make sure it is a string
    msg = gobject.markup_escape_text(msg)
    return msg

try:
    from html.entities import codepoint2name
except ImportError:
    from htmlentitydefs import codepoint2name
def unicode2htmlentities(u):
   htmlentities = list()
   for c in u:
      if ord(c) < 128:
         htmlentities.append(c)
      else:
         htmlentities.append('&%s;' % codepoint2name[ord(c)])
   return ''.join(htmlentities)

class fakeoutfile:
    """
    A general purpose fake output file object.
    """

    def __init__(self, fn):
        self.fn = fn
        self.external_writer = None

    def close(self):
        pass

    def flush(self):
        pass

    def fileno(self):
        return self.fn

    def isatty(self):
        return False

    def read(self, a):
        return ''

    def readline(self):
        return ''

    def readlines(self):
        return []

    def write(self, s):
        if self.external_writer is None:
            os.write(self.fn, s)
        elif hasattr(self.external_writer, '__call__'):
            self.external_writer(s)

    def write_line(self, s):
        self.write(s)

    def writelines(self, l):
        for s in l:
            self.write(s)

    def seek(self, a):
        raise IOError(29, 'Illegal seek')

    def tell(self):
        raise IOError(29, 'Illegal seek')

    def truncate(self):
        self.tell()

class fakeinfile:
    """
    A general purpose fake input file object.
    """
    def __init__(self, fn):
        self.fn = fn
        self.text_read = ''

    def close(self):
        pass

    def flush(self):
        pass

    def fileno(self):
        return self.fn

    def isatty(self):
        return False

    def read(self, a):
        return self.readline(count = a)

    def readline(self, count = 2048):
        x = os.read(self.fn, count)
        self.text_read += x
        return x

    def readlines(self):
        return self.readline().split("\n")

    def write(self, s):
        raise IOError(29, 'Illegal seek')

    def writelines(self, l):
        raise IOError(29, 'Illegal seek')

    def seek(self, a):
        raise IOError(29, 'Illegal seek')

    def tell(self):
        raise IOError(29, 'Illegal seek')

    truncate = tell
