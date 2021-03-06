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

# Base Python Imports
import os
import sys
import pty
import random
import signal
import time
import threading
import errno

# Entropy Imports
if "../../lib" not in sys.path:
    sys.path.insert(0, "../../lib")
if "../../client" not in sys.path:
    sys.path.insert(1, "../../client")
if "/usr/lib/entropy/lib" not in sys.path:
    sys.path.insert(2, "/usr/lib/entropy/lib")
if "/usr/lib/entropy/client" not in sys.path:
    sys.path.insert(3, "/usr/lib/entropy/client")
if "/usr/lib/entropy/sulfur" not in sys.path:
    sys.path.insert(4, "/usr/lib/entropy/sulfur")

os.environ["ENTROPY_CLIENT_ENABLE_OLD_FILEUPDATES"] = "1"

from entropy.exceptions import OnlineMirrorError, PermissionDenied
import entropy.tools
from entropy.const import etpConst, const_get_stringtype, \
    initconfig_entropy_constants, const_convert_to_unicode, \
    const_debug_write
from entropy.i18n import _, ngettext
from entropy.misc import ParallelTask
from entropy.cache import EntropyCacher, MtimePingus
from entropy.output import print_generic
from entropy.db.exceptions import ProgrammingError, OperationalError
from entropy.core.settings.base import SystemSettings
from entropy.services.client import WebService
from entropy.client.interfaces.client import ClientSystemSettingsPlugin

# Sulfur Imports
import gtk, gobject
from sulfur.packages import EntropyPackages, Queue
from sulfur.entropyapi import Equo, QueueExecutor
from sulfur.setup import SulfurConf, const, fakeoutfile, fakeinfile, \
    cleanMarkupString
from sulfur.widgets import SulfurConsole
from sulfur.core import UI, Controller, \
    busy_cursor, normal_cursor, get_entropy_webservice, Privileges
from sulfur.views import *
from sulfur.filters import Filter
from sulfur.dialogs import *
from sulfur.progress import Base as BaseProgress
from sulfur.events import SulfurApplicationEventsMixin
from sulfur.event import SulfurSignals

class SulfurApplication(Controller, SulfurApplicationEventsMixin):

    def __init__(self):

        self.do_debug = False
        self._ugc_status = "--nougc" not in sys.argv

        self._privileges = Privileges()
        # Use this lock when you want to make sure that no other asynchronous
        # executions are being run.
        self._async_event_execution_lock = threading.Lock()

        self._entropy = Equo()
        self._cacher = EntropyCacher()
        self._settings = SystemSettings()
        self._webserv_map = {}

        # support for packages installation on startup
        packages_install, atoms_install, do_fetch = \
            self.__scan_packages_install()

        resources_locked = "--locked" in sys.argv
        if resources_locked:
            locked = True
        else:
            # we don't want to interleave equo or entropy services with
            # sulfur. People just cannot deal with it.
            locked = not entropy.tools.acquire_entropy_locks(
                self._entropy, max_tries = 5)
        self._effective_root = os.getuid() == 0
        if self._effective_root:
            self._privileges.drop()

        try:
            with self._privileges:
                permissions_ok = True
        except OSError as err:
            if err.errno != errno.EPERM:
                raise
            # user doesn't have privileges to run the application
            permissions_ok = False

        if not permissions_ok:
            self._entropy.shutdown()
            okDialog(None,
                _("Access denied. You don't have enough privileges to run Sulfur.") )
            raise PermissionDenied("not enough privileges")

        if locked or (not self._effective_root):
            if locked:
                self._entropy.shutdown()
                okDialog(None,
                    _("Another Entropy application is running. Sorry.") )
                raise PermissionDenied("another entropy running")

        self.safe_mode_txt = ''
        # check if we'are running in safe mode
        if self._entropy.safe_mode:
            reason = etpConst['safemodereasons'].get(self._entropy.safe_mode)
            okDialog( None, "%s: %s. %s" % (
                _("Entropy is running in safe mode"), reason,
                _("Please fix as soon as possible"),)
            )
            self.safe_mode_txt = _("Safe Mode")

        if entropy.tools.islive():
            okDialog(None, "%s, %s" % (
                _("Entropy Store is running off a Live System"),
                _("performance could get severely compromised"),)
            )

        self._startup_packages_install = None
        if not self._entropy.safe_mode:
            if packages_install or atoms_install:
                self._startup_packages_install = (packages_install,
                    atoms_install, do_fetch)

        self.isBusy = False
        self.etpbase = EntropyPackages(self._entropy)

        # Create and ui object contains the widgets.
        ui = UI( const.GLADE_FILE, 'main', 'entropy' )
        # init the Controller Class to connect signals.
        Controller.__init__( self, ui )

    def _get_webservice(self, repository_id):
        webserv = self._webserv_map.get(repository_id)
        if webserv == -1:
            # not available
            return None
        if webserv is not None:
            return webserv

        with self._privileges:
            # so that the correct auth store file is fetched
            # NOTE: other areas don't do the same, be careful
            try:
                webserv = get_entropy_webservice(self._entropy, repository_id)
            except WebService.UnsupportedService as err:
                webserv = None

        if webserv is None:
            self._webserv_map[repository_id] = -1
            # not available
            return

        try:
            available = webserv.service_available()
        except WebService.WebServiceException:
            available = False

        if not available:
            self._webserv_map[repository_id] = -1
            # not available
            return

        self._webserv_map[repository_id] = webserv
        return webserv

    def __scan_packages_install(self):
        packages_install = os.environ.get("SULFUR_PACKAGES", '').split(";")
        atoms_install = []
        do_fetch = False
        if "--fetch" in sys.argv:
            do_fetch = True
            sys.argv.remove("--fetch")

        if "--install" in sys.argv:
            atoms_install.extend(sys.argv[sys.argv.index("--install")+1:])

        packages_install = [x for x in packages_install if \
            os.access(x, os.R_OK) and os.path.isfile(x)]

        for arg in sys.argv:
            is_pkg_file = (arg.endswith(etpConst['packagesext']) or \
                arg.endswith(etpConst['packagesext_webinstall']))
            if is_pkg_file and os.access(arg, os.R_OK) and os.path.isfile(arg):
                arg = os.path.realpath(arg)
                packages_install.append(arg)

        if os.getenv("SULFUR_SYS_UPDATE"):
            # sulfur has been respawned and there is a system update request
            packages_install = []
            atoms_install = ["@upgrade"]

        return packages_install, atoms_install, do_fetch

    def init(self):

        self.setup_gui()

        if entropy.tools.is_april_first():
            okDialog( self.ui.main,
                _("April 1st, w0000h0000! Gonna erase your hard disk!"))
        elif entropy.tools.is_st_valentine():
            okDialog( self.ui.main, _("Love love love... <3"))
        elif entropy.tools.is_xmas():
            okDialog( self.ui.main, _("Oh oh ooooh... Merry Xmas!"))

        self.start_working()
        self.ui_lock(True)
        self.gtk_loop()

        # show UI
        if "--maximize" in sys.argv:
            self.ui.main.maximize()

        def _pkg_install():
            self.ui.main.hide()
            try:
                pkg_installing = self.__packages_install()
                self.ui_lock(False)
                self.end_working()
            finally:
                self.ui.main.show()

            if not pkg_installing:
                self.warn_repositories()
                if "--nonoticeboard" not in sys.argv:
                    if not self._entropy.are_noticeboards_marked_as_read():
                        self.show_notice_board(force = False)
                    else:
                        self.show_sulfur_tips()
                self.show_packages()
        self.gtk_loop()
        gobject.idle_add(_pkg_install)

    def _get_file_updates(self):
        # delayed loading, use cache.
        if not hasattr(self, "_file_updates"):
            self._file_updates = self._entropy.PackageFileUpdates()
        return self._file_updates

    def quit(self, widget = None, event = None, sysexit = 0):

        SulfurSignals.emit('application_quit')
        const_debug_write(__name__, "\n\t\t application_quit signal sent \n\n")

        if hasattr(self, '_entropy'):
            entropy.tools.release_entropy_locks(self._entropy)
            self._entropy.shutdown()

        if sysexit != -1:
            self.exit_now()
            if isinstance(sysexit, int):
                raise SystemExit(sysexit)
            raise SystemExit(0)

    def exit_now(self):
        entropy.tools.kill_threads()
        try:
            gtk.main_quit()
        except RuntimeError:
            pass

    def gtk_loop(self):
        while gtk.events_pending():
           gtk.main_iteration()

    class VteFakeoutfile(fakeoutfile):
        def write(self, s):
            # workaround for raw input coming without \r
            if "\r" not in s:
                s = s.replace("\n", "\n\r")
            return fakeoutfile.write(self, s)

    def setup_gui(self):

        self.pty = pty.openpty()
        self.std_output = self.VteFakeoutfile(self.pty[1])
        self.input = fakeinfile(self.pty[1])
        self.do_debug = const.debug

        if not self.do_debug:
            sys.stdout = self.std_output
            sys.stderr = self.std_output
            sys.stdin = self.input

        # load "loading" pix
        self._loading_pix_small = gtk.image_new_from_file(const.loading_pix_small)

        self.queue = Queue(self)
        self.etpbase.connect_queue(self.queue)
        self.pkgView = EntropyPackageView(self.ui.viewPkg, self.queue, self.ui,
            self.etpbase, self.ui.main, self)
        self.filesView = EntropyFilesView(self.ui.filesView, self.ui.systemVbox)
        self.queue.connect_objects(self._entropy, self.etpbase, self.pkgView, self.ui)
        self.repoView = EntropyRepoView(self.ui.viewRepo, self.ui, self)
        # Left Side Toolbar
        self._notebook_tabs_cache = {}
        self._filterbar_previous_txt = ''
        self.firstButton = None  # first button
        self.activePage = 'repos'
        # Progress bars
        self.progress = BaseProgress(self.ui, self.switch_notebook_page, self)
        # Package Radiobuttons
        self.packageRB = {}
        self.lastPkgPB = 'updates'

        # color settings mapping dictionary
        self.colorSettingsMap = {
            "color_console_font": self.ui.color_console_font_picker,
            "color_normal": self.ui.color_normal_picker,
            "color_update": self.ui.color_update_picker,
            "color_install": self.ui.color_install_picker,
            "color_install": self.ui.color_install_picker,
            "color_remove": self.ui.color_remove_picker,
            "color_reinstall": self.ui.color_reinstall_picker,
            "color_downgrade": self.ui.color_downgrade_picker,
            "color_title": self.ui.color_title_picker,
            "color_title2": self.ui.color_title2_picker,
            "color_pkgdesc": self.ui.color_pkgdesc_picker,
            "color_pkgsubtitle": self.ui.color_pkgsubtitle_picker,
            "color_subdesc": self.ui.color_subdesc_picker,
            "color_error": self.ui.color_error_picker,
            "color_good": self.ui.color_good_picker,
            "color_background_good": self.ui.color_background_good_picker,
            "color_background_error": self.ui.color_background_error_picker,
            "color_good_on_color_background": self.ui.color_good_on_color_background_picker,
            "color_error_on_color_background": self.ui.color_error_on_color_background_picker,
            "color_package_category": self.ui.color_package_category_picker,
        }
        self.colorSettingsReverseMap = {
            self.ui.color_console_font_picker: "color_console_font",
            self.ui.color_normal_picker: "color_normal",
            self.ui.color_update_picker: "color_update",
            self.ui.color_install_picker: "color_install",
            self.ui.color_install_picker: "color_install",
            self.ui.color_remove_picker: "color_remove",
            self.ui.color_reinstall_picker: "color_reinstall",
            self.ui.color_downgrade_picker: "color_downgrade",
            self.ui.color_title_picker: "color_title",
            self.ui.color_title2_picker:  "color_title2",
            self.ui.color_pkgdesc_picker: "color_pkgdesc",
            self.ui.color_pkgsubtitle_picker: "color_pkgsubtitle",
            self.ui.color_subdesc_picker: "color_subdesc",
            self.ui.color_error_picker: "color_error",
            self.ui.color_good_picker: "color_good",
            self.ui.color_background_good_picker: "color_background_good",
            self.ui.color_background_error_picker: "color_background_error",
            self.ui.color_good_on_color_background_picker: "color_good_on_color_background",
            self.ui.color_error_on_color_background_picker: "color_error_on_color_background",
            self.ui.color_package_category_picker: "color_package_category",
        }

        # setup add repository window
        self.console_menu_xml = gtk.glade.XML( const.GLADE_FILE, "terminalMenu",
            domain="entropy" )
        self.console_menu = self.console_menu_xml.get_widget( "terminalMenu" )
        self.console_menu_xml.signal_autoconnect(self)

        self.ui.main.set_title( "%s %s %s" % (SulfurConf.branding_title,
            const.__sulfur_version__, self.safe_mode_txt) )
        self.ui.main.connect("delete-event", self.quit)

        self.ui.main.realize()
        self.setup_page_buttons()        # Setup left side toolbar
        self.switch_notebook_page(self.activePage)

        # put self.console in place
        self.console = SulfurConsole()
        # this is a workaround for buggy vte.Terminal when using
        # file descriptors. This will make fakeoutfile to use
        # our external writer instead of using os.write
        self.std_output.external_writer = self.progress_log_write

        self.console.set_scrollback_lines(1024)
        self.console.set_scroll_on_output(True)
        self.console.connect("button-press-event", self.on_console_click)
        termScroll = gtk.VScrollbar(self.console.get_adjustment())
        self.ui.vteBox.pack_start(self.console, True, True)
        self.ui.termScrollBox.pack_start(termScroll, False)
        self.ui.termHBox.show_all()
        self.setup_packages_filter()

        self.setup_images()

        # init flags
        self.disable_ugc = False

        self._mtime_pingus = MtimePingus()
        self._spawning_ugc = False
        self._preferences = None
        self._orphans_message_shown = False
        self.skipMirrorNow = False
        self.abortQueueNow = False
        self._is_working = False
        self.lastPkgPB = "updates"
        self._entropy.connect_to_gui(self)
        self.setup_editor()
        self.switch_notebook_page("packages")

        # setup Repositories
        self.setup_repoView()
        # setup app
        self.setup_application(on_init = True)

        self.console.set_pty(self.pty[0])
        self.reset_progress_text()
        self.pkgProperties_selected = None
        self.setup_pkg_sorter()
        self.setup_user_generated_content()
        self.ui.systemVbox.show()

        simple_mode = 1
        if "--advanced" in sys.argv:
            simple_mode = 0
        elif not SulfurConf.simple_mode:
            simple_mode = 0
        self.in_mode_loading = True
        self.switch_application_mode(simple_mode)
        self.in_mode_loading = False

        # hide progress Tab by default
        self.ui.progressVBox.hide()

        self.setup_labels()
        self.setup_preferences()
        self.setup_events_handling()

    def setup_labels(self):

        # make Sulfur label look nicer
        self.ui.rbAllSimpleLabel.set_markup("<small>%s</small>" % (
            _("Applications"),))
        self.ui.rbSyncSimpleLabel.set_markup("<small>%s</small>" % (
            _("Sync"),))
        self.ui.rbQueueSimpleLabel.set_markup("<small>%s</small>" % (
            _("Install"),))
        self.ui.repoSearchSimpleLabel.set_markup("<small>%s</small>" % (
            _("Search"),))

        small_widgets = [self.ui.rbRefreshLabel,
            self.ui.rbAvailableLabel, self.ui.rbInstalledLabel,
            self.ui.rbMaskedLabel, self.ui.rbAllLabel,
            self.ui.rbPkgSetsLabel, self.ui.rbPkgSetsLabel1,
            self.ui.repoSearchLabel]
        for widget in small_widgets:
            txt = widget.get_text()
            widget.set_markup("<small>%s</small>" % (txt,))

    def setup_events_handling(self):

        def queue_changed(event, length):
            if not length and self.lastPkgPB == "queued":
                self.set_package_radio("updates")

        def updates_available(event, amount):
            if amount:
                self.ui.updatesButtonbox.show()
            else:
                self.ui.updatesButtonbox.hide()

        # setup queued/installation button events
        SulfurSignals.connect("install_queue_changed", queue_changed)
        SulfurSignals.connect("updates_available", updates_available)

    def switch_application_mode(self, do_simple):
        self.ui.UGCMessageLabel.hide()
        if do_simple:
            self.switch_simple_mode()
            self.ui.advancedMode.set_active(0)
            # switch back to updates
            self.set_package_radio("updates")
        else:
            self.switch_advanced_mode()
            self.ui.advancedMode.set_active(1)
        SulfurConf.simple_mode = do_simple
        SulfurConf.save()

    def switch_simple_mode(self):
        self.ui.servicesMenuItem.hide()
        self.ui.repoRefreshButton.show()
        # self.ui.pkgSorter.hide()
        # self.ui.updateButtonView.hide()
        self.ui.rbAvailable.hide()
        self.ui.rbInstalled.hide()
        self.ui.rbMasked.hide()
        self.ui.rbPkgSets.hide()
        self.ui.rbAll.show()

        if self.filesView.is_filled():
            self.ui.systemVbox.show()
        else:
            self.ui.systemVbox.hide()

        self.ui.prefsVbox.hide()
        self.ui.reposVbox.hide()

        # move top header buttons
        adv_content = self.ui.rbUpdatesAdvancedBox
        if adv_content.get_parent() is self.ui.headerHbox:
            self.ui.headerHbox.remove(adv_content)
            self.ui.rbUpdatesSimpleHbox.pack_start(adv_content, expand = False,
                fill = False)
            self.ui.rbUpdatesSimpleHbox.reorder_child(adv_content, 0)

        # move sorter
        sorter = self.ui.pkgSorter
        if sorter.get_parent() is self.ui.appTopRightVbox:
            self.ui.appTopRightVbox.remove(sorter)
            self.ui.rbUpdatesSimpleHbox.pack_start(sorter)
            self.ui.rbUpdatesSimpleHbox.reorder_child(sorter, -1)

        self.ui.rbSyncSimpleLabel.show()
        self.ui.rbQueueSimpleLabel.show()
        self.ui.rbUpdatesSimpleLabel.show()
        self.ui.repoSearchSimpleLabel.show()
        self.ui.repoSearchLabel.hide()
        self.ui.rbUpdatesLabel.hide()
        self.ui.rbAllSimpleLabel.show()

        self.ui.rbRefreshLabel.hide()
        self.ui.rbAllLabel.hide()
        self.ui.rbPkgSetsLabel1.hide()
        self.ui.pkgFilter.set_size_request(-1, 32)

        # move filterbar
        filter_bar = self.ui.pkgFilter
        if filter_bar.get_parent() is self.ui.appTopRightVbox:
            self.ui.appTopRightVbox.remove(filter_bar)
            self.ui.rbUpdatesSimpleFilterBox.pack_start(filter_bar)
            self.ui.rbUpdatesSimpleFilterBox.reorder_child(filter_bar, 0)

    def switch_advanced_mode(self):
        self.ui.servicesMenuItem.show()
        self.ui.repoRefreshButton.hide()
        # self.ui.pkgSorter.show()
        # self.ui.updateButtonView.show()
        self.ui.rbAvailable.show()
        self.ui.rbInstalled.show()
        self.ui.rbMasked.show()
        self.ui.rbPkgSets.show()
        self.ui.rbAll.hide()

        self.ui.systemVbox.show()
        self.ui.prefsVbox.show()
        self.ui.reposVbox.show()

        # move top header buttons
        adv_content = self.ui.rbUpdatesAdvancedBox
        if adv_content.get_parent() is self.ui.rbUpdatesSimpleHbox:
            self.ui.rbUpdatesSimpleHbox.remove(adv_content)
            self.ui.headerHbox.pack_start(adv_content, expand = False,
                fill = False)
            self.ui.headerHbox.reorder_child(adv_content, 0)

        sorter = self.ui.pkgSorter
        if sorter.get_parent() is self.ui.rbUpdatesSimpleHbox:
            self.ui.rbUpdatesSimpleHbox.remove(sorter)
            self.ui.appTopRightVbox.pack_start(sorter)
            self.ui.appTopRightVbox.reorder_child(sorter, 0)

        self.ui.rbSyncSimpleLabel.hide()
        self.ui.rbQueueSimpleLabel.hide()
        self.ui.rbUpdatesSimpleLabel.hide()
        self.ui.rbUpdatesLabel.show()
        self.ui.repoSearchSimpleLabel.hide()
        self.ui.repoSearchLabel.show()
        self.ui.rbAllSimpleLabel.hide()

        self.ui.rbRefreshLabel.show()
        self.ui.rbAllLabel.show()
        self.ui.rbPkgSetsLabel1.show()
        self.ui.pkgFilter.set_size_request(-1, 26)

        # move filterbar
        filter_bar = self.ui.pkgFilter
        if filter_bar.get_parent() is self.ui.rbUpdatesSimpleFilterBox:
            self.ui.rbUpdatesSimpleFilterBox.remove(filter_bar)
            self.ui.appTopRightVbox.pack_start(filter_bar, expand = True,
                fill = True)
            self.ui.appTopRightVbox.reorder_child(filter_bar, -1)

    def setup_pkg_sorter(self):

        self.avail_pkg_sorters = {
            'default': DefaultPackageViewModelInjector,
            'name_az': NameSortPackageViewModelInjector,
            'name_za': NameRevSortPackageViewModelInjector,
            'downloads': DownloadSortPackageViewModelInjector,
            'votes': VoteSortPackageViewModelInjector,
            'repository': RepoSortPackageViewModelInjector,
            'date': DateSortPackageViewModelInjector,
            'date_grouped': DateGroupedSortPackageViewModelInjector,
            'license': LicenseSortPackageViewModelInjector,
            'groups': GroupSortPackageViewModelInjector,
        }
        self.pkg_sorters_desc = {
            'default': _("Default packages sorting"),
            'name_az': _("Sort by name [A-Z]"),
            'name_za': _("Sort by name [Z-A]"),
            'downloads': _("Sort by downloads"),
            'votes': _("Sort by votes"),
            'repository': _("Sort by repository"),
            'date': _("Sort by date (simple)"),
            'date_grouped': _("Sort by date (grouped)"),
            'license': _("Sort by license (grouped)"),
            'groups': _("Sort by Groups"),
        }
        self.pkg_sorters_id = {
            0: 'default',
            1: 'name_az',
            2: 'name_za',
            3: 'downloads',
            4: 'votes',
            5: 'repository',
            6: 'date',
            7: 'date_grouped',
            8: 'license',
            9: 'groups',
        }
        self.pkg_sorters_id_inverse = dict((y, x,) for x, y in \
            list(self.pkg_sorters_id.items()))

        self.pkg_sorters_img_ids = {
            0: gtk.STOCK_PRINT_PREVIEW,
            1: gtk.STOCK_SORT_DESCENDING,
            2: gtk.STOCK_SORT_ASCENDING,
            3: gtk.STOCK_GOTO_BOTTOM,
            4: gtk.STOCK_INFO,
            5: gtk.STOCK_CONNECT,
            6: gtk.STOCK_MEDIA_PLAY,
            7: gtk.STOCK_MEDIA_PLAY,
            8: gtk.STOCK_EDIT,
            9: gtk.STOCK_CDROM,
        }

        # setup package sorter
        sorter_model = gtk.ListStore(gobject.TYPE_STRING, gobject.TYPE_STRING)
        sorter = self.ui.pkgSorter
        sorter.set_model(sorter_model)

        sorter_img_cell = gtk.CellRendererPixbuf()
        sorter.pack_start(sorter_img_cell, False)
        sorter.add_attribute(sorter_img_cell, 'stock-id', 0)

        sorter_cell = gtk.CellRendererText()
        sorter.pack_start(sorter_cell, False)
        sorter.add_attribute(sorter_cell, 'text', 1)

        first = True
        for s_id in sorted(self.pkg_sorters_id):
            s_id_name = self.pkg_sorters_id.get(s_id)
            s_id_desc = self.pkg_sorters_desc.get(s_id_name)
            stock_img_id = self.pkg_sorters_img_ids.get(s_id)
            item = sorter_model.append( (stock_img_id, s_id_desc,) )
            if first:
                sorter.set_active_iter(item)
                first = False

    def warn_repositories(self):
        all_repos = self._settings['repositories']['order']
        valid_repos = self._entropy.repositories()
        invalid_repos = [x for x in all_repos if x not in valid_repos]
        invalid_repos = [x for x in invalid_repos if \
            (self._entropy.get_repository(x).revision(x) == -1)]
        if invalid_repos:
            mydialog = ConfirmationDialog(self.ui.main, invalid_repos,
                top_text = _("The repositories listed below are configured but not available. They should be downloaded."),
                sub_text = _("If you don't do this now, you won't be able to use them."), # the repositories
                simpleList = True)
            mydialog.okbutton.set_label(_("Download now"))
            mydialog.cancelbutton.set_label(_("Skip"))
            rc = mydialog.run()
            mydialog.destroy()
            if rc == -5:
                self.do_repo_refresh(invalid_repos)

    def _parse_entropy_action_string(self, action_bar_str):

        # entropy://amarok,foo2,foo3 install from filter bar
        if action_bar_str.startswith(SulfurConf.entropy_uri):
            atoms = action_bar_str[len(SulfurConf.entropy_uri):].split(",")
            if atoms:
                self.atoms_install(atoms)
                return True

        return False

    def atoms_install(self, atoms, fetch = False):

        matches = []
        if "@upgrade" in atoms:
            updates = self.etpbase.get_groups("updates")
            if not updates:
                return
            matches += [x.matched_atom for x in updates]
        else:
            for atom in self._entropy.packages_expand(atoms):
                pkg_id, repo_id = self._entropy.atom_match(atom)
                if pkg_id == -1:
                    return
                matches.append((pkg_id, repo_id,))

        if not matches:
            return

        self.switch_notebook_page('output')

        self.install_queue(fetch = fetch, direct_install_matches = matches)
        self.reset_queue_progress_bars()

    def __packages_install(self):

        if not self._startup_packages_install:
            return

        packages_install, atoms_install, do_fetch = \
            self._startup_packages_install

        if packages_install:
            fn = packages_install[0]
            with self._privileges:
                st = self.on_installPackageItem_activate(None, fn,
                    get_st = True)
            if not st:
                self._startup_packages_install = None
            return st

        elif atoms_install: # --install <atom1> <atom2> ... support
            self.atoms_install(atoms_install, fetch = do_fetch)
            return True
        # it will be reset by the packages install function
        #self._startup_packages_install = None

        return False

    def setup_packages_filter(self):

        self.setup_package_radio_buttons(self.ui.rbUpdates, "updates")
        self.setup_package_radio_buttons(self.ui.rbAvailable, "available")
        self.setup_package_radio_buttons(self.ui.rbInstalled, "installed")
        self.setup_package_radio_buttons(self.ui.rbMasked, "masked")
        self.setup_package_radio_buttons(self.ui.rbAll, "all")
        self.setup_package_radio_buttons(self.ui.rbPkgSets, "pkgsets")
        self.setup_package_radio_buttons(self.ui.rbPkgQueued, "queued")
        self.setup_package_radio_buttons(self.ui.rbPkgSearch, "search")
        self.setup_package_radio_buttons(self.ui.repoRefreshButton, "refresh",
            callback = False)
        self.setup_package_radio_buttons(self.ui.rbPkgQueued, "install",
            callback = False)

    def setup_package_radio_buttons(self, widget, tag, callback = True):
        if callback:
            widget.connect('clicked', self.on_pkgFilter_toggled, tag)

        #widget.set_relief( gtk.RELIEF_NONE )
        if hasattr(widget, 'set_mode'):
            widget.set_mode(False)

        pix = None
        if tag == "updates":
            pix = self.ui.rbUpdatesImage
        elif tag == "available":
            pix = self.ui.rbAvailableImage
        elif tag == "installed":
            pix = self.ui.rbInstalledImage
        elif tag == "masked":
            pix = self.ui.rbMaskedImage
        elif tag == "pkgsets":
            pix = self.ui.rbPackageSetsImage
        elif tag == "all":
            pix = self.ui.rbAllImage
        elif tag == "search":
            pix = self.ui.rbSearchImage
        elif tag == "refresh":
            pix = self.ui.rbRefreshImage
        elif tag == "install":
            pix = self.ui.rbQueuedImage

        if pix is not None:
            pix_path = os.path.join(const.PIXMAPS_PATH, tag+".png")
            try:
                p = gtk.gdk.pixbuf_new_from_file(pix_path)
                pix.set_from_pixbuf(p)
                pix.show()
            except gobject.GError as err:
                if self.do_debug:
                    print_generic("Error loading %s: %s" % (pix_path, err,))

        self.packageRB[tag] = widget

    def setup_page_buttons(self):

        # Setup Vertical Toolbar
        self.create_sidebar_button(self.ui.sideRadioPkgImage,
            "button-packages.png", 'packages')

        self.create_sidebar_button(self.ui.sideRadioReposImage,
            "button-repo.png", 'repos' )

        self.create_sidebar_button(self.ui.sideRadioSystemImage,
            "button-conf.png", 'filesconf' )

        self.create_sidebar_button(self.ui.sideRadioPrefsImage,
            "preferences.png", 'preferences' )

        self.create_sidebar_button(self.ui.sideRadioInstallImage,
            "button-output.png", 'output' )

    def create_sidebar_button( self, image, icon, page):

        iconpath = os.path.join(const.PIXMAPS_PATH, icon)
        if os.path.isfile(iconpath) and os.access(iconpath, os.R_OK):
            try:
                p = gtk.gdk.pixbuf_new_from_file(iconpath)
                image.set_from_pixbuf(p)
                image.show()
            except gobject.GError as err:
                if self.do_debug:
                    print_generic("Error loading %s: %s" % (iconpath, err,))

        page_widget = self.ui.notebook.get_nth_page(const.PAGES[page])
        self._notebook_tabs_cache[page] = page_widget

    def setup_images(self):
        """ setup misc application images """

        iconpath = os.path.join(const.PIXMAPS_PATH, "sabayon.png")
        if os.path.isfile(iconpath) and os.access(iconpath, os.R_OK):
            try:
                p = gtk.gdk.pixbuf_new_from_file(iconpath)
                self.ui.progressImage.set_from_pixbuf(p)
            except gobject.GError as err:
                if self.do_debug:
                    print_generic("Error loading %s: %s" % (iconpath, err,))

        # setup Update All icon
        iconpath = os.path.join(const.PIXMAPS_PATH, "update-all.png")
        if os.path.isfile(iconpath) and os.access(iconpath, os.R_OK):
            try:
                p = gtk.gdk.pixbuf_new_from_file(iconpath)
                self.ui.updateAllImage.set_from_pixbuf(p)
            except gobject.GError:
                pass

    def setup_user_generated_content(self):

        if self._ugc_status:
            gobject.timeout_add(20*1000,
                self.spawn_user_generated_content_first)
            gobject.timeout_add(7200*1000, # 2 hours
                self.spawn_user_generated_content, False)

    def spawn_user_generated_content_first(self):
        self.spawn_user_generated_content(force = False)
        # this makes the whole thing to terminate
        return False

    def spawn_user_generated_content(self, force = True):

        if self.do_debug:
            print_generic("entering UGC")

        if self._spawning_ugc or self.disable_ugc:
            return

        if not force:
            webserv_repos = []
            for repoid in self._entropy.repositories():
                webserv = self._get_webservice(repoid)
                if webserv is None:
                    continue
                try:
                    aware = webserv.service_available()
                except WebService.WebServiceException:
                    continue
                if aware:
                    webserv_repos.append((webserv, repoid))

            cache_available = True
            for webserv, repoid in webserv_repos:
                cache_available = True
                try:
                    webserv.get_available_votes(cache = True, cached = True)
                except WebService.CacheMiss:
                    cache_available = False
                if cache_available:
                    # also check downloads
                    try:
                        webserv.get_available_downloads(cache = True,
                            cached = True)
                    except WebService.CacheMiss:
                        cache_available = False
                if not cache_available:
                    break

            pingus_id = "sulfur_ugc_content_spawn"
            # check if at least 2 hours are passed since last check
            if not self._mtime_pingus.hours_passed(pingus_id, 6) and \
                cache_available:

                if self.do_debug:
                    print_generic("UGC not syncing, 6 hours not passed")
                return
            self._mtime_pingus.ping(pingus_id)

        def emit_ugc_update():
            # emit ugc update signal
            self._spawning_ugc = False
            SulfurSignals.emit('ugc_data_update')
            if self.do_debug:
                print_generic("UGC data update signal emitted")
            return False

        def do_ugc_sync():
            self._ugc_update()
            self._cacher.sync()
            if self.do_debug:
                print_generic("UGC child process done")
            emit_ugc_update()

        self._spawning_ugc = True
        th = ParallelTask(do_ugc_sync)
        th.start()

        if self.do_debug:
            print_generic("quitting UGC")

        return True

    def _ugc_update(self):

        def _update_available_cache(repository_id):
            webserv = self._get_webservice(repository_id)
            if webserv is None:
                return

            # fetch vote cache first
            try:
                webserv.get_available_votes(cache = False)
            except WebService.WebServiceException as err:
                const_debug_write(__name__,
                    "_ugc_update.get_available_votes: ouch %s" % (err,))
                return
            # drop get_votes cache completely
            # this enforces EntropyPackage.vote* to use available_votes cache
            webserv._drop_cached("get_votes")

            try:
                webserv.get_available_downloads(cache = False)
            except WebService.WebServiceException as err:
                const_debug_write(__name__,
                    "_ugc_update.get_available_downloads: ouch %s" % (err,))
                return
            # drop get_downloads cache completely
            # this enforces EntropyPackage.down* to use available_downloads
            # cache
            webserv._drop_cached("get_downloads")


        for repo in self._entropy.repositories():
            t1 = time.time()
            const_debug_write(__name__,
                "working UGC update for %s" % (repo,))

            _update_available_cache(repo)

            t2 = time.time()
            td = t2 - t1
            const_debug_write(__name__,
                "completed UGC update for %s, took %s" % (
                    repo, td,))

    def fill_pref_db_backup_page(self):
        self.dbBackupStore.clear()
        backed_up_dbs = self._entropy.installed_repository_backups()
        for mypath in backed_up_dbs:
            mymtime = os.path.getmtime(mypath)
            mytime = entropy.tools.convert_unix_time_to_human_time(mymtime)
            self.dbBackupStore.append(
                (mypath, os.path.basename(mypath), mytime,) )

    def setup_preferences(self):

        # dep resolution algorithm combo
        dep_combo = self.ui.depResAlgoCombo
        if SulfurConf.relaxed_deps:
            dep_combo.set_active(1)
        else:
            dep_combo.set_active(0)

        # config protect
        self.configProtectView = self.ui.configProtectView
        for mycol in self.configProtectView.get_columns():
            self.configProtectView.remove_column(mycol)
        self.configProtectModel = gtk.ListStore( gobject.TYPE_STRING )
        cell = gtk.CellRendererText()
        column = gtk.TreeViewColumn( _( "Item" ), cell, markup = 0 )
        self.configProtectView.append_column( column )
        self.configProtectView.set_model( self.configProtectModel )

        # config protect mask
        self.configProtectMaskView = self.ui.configProtectMaskView
        for mycol in self.configProtectMaskView.get_columns():
            self.configProtectMaskView.remove_column(mycol)
        self.configProtectMaskModel = gtk.ListStore( gobject.TYPE_STRING )
        cell = gtk.CellRendererText()
        column = gtk.TreeViewColumn( _( "Item" ), cell, markup = 0 )
        self.configProtectMaskView.append_column( column )
        self.configProtectMaskView.set_model( self.configProtectMaskModel )

        # config protect skip
        self.configProtectSkipView = self.ui.configProtectSkipView
        for mycol in self.configProtectSkipView.get_columns():
            self.configProtectSkipView.remove_column(mycol)
        self.configProtectSkipModel = gtk.ListStore( gobject.TYPE_STRING )
        cell = gtk.CellRendererText()
        column = gtk.TreeViewColumn( _( "Item" ), cell, markup = 0 )
        self.configProtectSkipView.append_column( column )
        self.configProtectSkipView.set_model( self.configProtectSkipModel )

        # database backup tool
        self.dbBackupView = self.ui.dbBackupView
        self.dbBackupStore = gtk.ListStore( gobject.TYPE_STRING,
            gobject.TYPE_STRING, gobject.TYPE_STRING )
        cell = gtk.CellRendererText()
        column = gtk.TreeViewColumn( _( "Database" ), cell, markup = 1 )
        self.dbBackupView.append_column( column )
        cell = gtk.CellRendererText()
        column = gtk.TreeViewColumn( _( "Date" ), cell, markup = 2 )
        self.dbBackupView.append_column( column )
        self.dbBackupView.set_model( self.dbBackupStore )
        self.fill_pref_db_backup_page()

        # UGC repositories

        def get_ugc_repo_text( column, cell, model, myiter ):
            obj = model.get_value( myiter, 0 )
            if obj:
                t = "[<b>%s</b>] %s" % (obj['repoid'], obj['description'],)
                cell.set_property('markup', t)

        def get_ugc_logged_text( column, cell, model, myiter ):
            obj = model.get_value( myiter, 0 )
            if obj:
                t = "<i>%s</i>" % (_("Not logged in"),)
                webserv = self._get_webservice(obj['repoid'])
                if webserv is None:
                    t = "<i>%s</i>" % (_("Not available"),)
                else:
                    with self._privileges:
                        username = webserv.get_credentials()
                    if username is not None:
                        t = "<i>%s</i>" % (username,)
                cell.set_property('markup', t)

        def get_ugc_status_pix( column, cell, model, myiter ):
            if not self._ugc_status:
                cell.set_property('icon-name', 'gtk-cancel')
                return
            obj = model.get_value( myiter, 0 )
            if obj:
                webserv = self._get_webservice(obj['repoid'])
                if webserv is None:
                    cell.set_property( 'icon-name', 'gtk-cancel' )
                    return
                try:
                    available = webserv.service_available()
                except WebService.WebServiceException:
                    available = False
                if available:
                    cell.set_property( 'icon-name', 'gtk-apply' )
                else:
                    cell.set_property( 'icon-name', 'gtk-cancel' )
                return
            cell.set_property( 'icon-name', 'gtk-cancel' )

        self.ugcRepositoriesView = self.ui.ugcRepositoriesView
        self.ugcRepositoriesModel = gtk.ListStore( gobject.TYPE_PYOBJECT )

        cell = gtk.CellRendererText()
        column = gtk.TreeViewColumn( _( "Repository" ), cell )
        column.set_sizing( gtk.TREE_VIEW_COLUMN_FIXED )
        column.set_fixed_width( 300 )
        column.set_expand(True)
        column.set_cell_data_func( cell, get_ugc_repo_text )
        self.ugcRepositoriesView.append_column( column )

        cell = gtk.CellRendererText()
        column = gtk.TreeViewColumn( _( "Logged in as" ), cell )
        column.set_sizing( gtk.TREE_VIEW_COLUMN_FIXED )
        column.set_fixed_width( 150 )
        column.set_cell_data_func( cell, get_ugc_logged_text )
        self.ugcRepositoriesView.append_column( column )

        cell = gtk.CellRendererPixbuf()
        column = gtk.TreeViewColumn( _( "UGC Status" ), cell)
        column.set_cell_data_func( cell, get_ugc_status_pix )
        column.set_sizing( gtk.TREE_VIEW_COLUMN_FIXED )
        column.set_fixed_width( 120 )

        self.ugcRepositoriesView.append_column( column )
        self.ugcRepositoriesView.set_model( self.ugcRepositoriesModel )

        # prepare generic config to allow filling of data
        def fill_setting_view(model, view, data):
            model.clear()
            view.set_model(model)
            view.set_property('headers-visible', False)
            for item in data:
                model.append([item])
            view.expand_all()

        def fill_setting(name, mytype, wgwrite, data):
            if not isinstance(data, mytype):
                if data == None: # empty parameter
                    return
                errorMessage(
                    self.ui.main,
                    cleanMarkupString("%s: %s") % (_("Error setting parameter"),
                        name,),
                    _("An issue occured while loading a preference"),
                    "%s %s %s: %s, %s: %s" % (_("Parameter"), name,
                        _("must be of type"), mytype, _("got"), type(data),),
                )
                return
            wgwrite(data)

        def fill_sulfurconf(name, mytype, wgwrite, data):
            setattr(SulfurConf, name, data)

        def save_sulfurconf(config_file, name, myvariable, mytype, data):
            setattr(SulfurConf, name, data)
            SulfurConf.save()
            return True

        def save_setting_view(config_file, name, setting, mytype, model, view):

            data = []
            iterator = model.get_iter_first()
            while iterator != None:
                item = model.get_value( iterator, 0 )
                if item:
                    data.append(item)
                iterator = model.iter_next( iterator )

            return saveSetting(config_file, name, setting, mytype, data)


        def saveSetting(config_file, name, myvariable, mytype, data):
            # saving setting
            writedata = ''
            if (not isinstance(data, mytype)) and (data != None):
                errorMessage(
                    self.ui.main,
                    cleanMarkupString("%s: %s") % (_("Error setting parameter"),
                        name,),
                    _("An issue occured while saving a preference"),
                    "%s %s %s: %s, %s: %s" % (_("Parameter"), name,
                        _("must be of type"), mytype, _("got"), type(data),),
                )
                return False

            if isinstance(data, int):
                writedata = str(data)
            elif isinstance(data, list):
                writedata = ' '.join(data)
            elif isinstance(data, bool):
                writedata = "disable"
                if data: writedata = "enable"
            elif isinstance(data, const_get_stringtype()):
                writedata = data
            return save_parameter(config_file, name, writedata)

        def save_parameter(config_file, name, data):
            return entropy.tools.write_parameter_to_file(config_file, name, data)

        sys_settings_plg_id = \
            etpConst['system_settings_plugins_ids']['client_plugin']
        conf_files = self._settings.get_setting_files_data()
        client_conf = ClientSystemSettingsPlugin.client_conf_path()
        self._preferences = {
            conf_files['system']: [
                (
                    'ftp-proxy',
                    self._settings['system']['proxy']['ftp'],
                    const_get_stringtype(),
                    fill_setting,
                    saveSetting,
                    self.ui.ftpProxyEntry.set_text,
                    self.ui.ftpProxyEntry.get_text,
                ),
                (
                    'http-proxy',
                    self._settings['system']['proxy']['http'],
                    const_get_stringtype(),
                    fill_setting,
                    saveSetting,
                    self.ui.httpProxyEntry.set_text,
                    self.ui.httpProxyEntry.get_text,
                ),
                (
                    'proxy-username',
                    self._settings['system']['proxy']['username'],
                    const_get_stringtype(),
                    fill_setting,
                    saveSetting,
                    self.ui.usernameProxyEntry.set_text,
                    self.ui.usernameProxyEntry.get_text,
                ),
                (
                    'proxy-password',
                    self._settings['system']['proxy']['password'],
                    const_get_stringtype(),
                    fill_setting,
                    saveSetting,
                    self.ui.passwordProxyEntry.set_text,
                    self.ui.passwordProxyEntry.get_text,
                ),
                (
                    'nice-level',
                    etpConst['current_nice'],
                    int,
                    fill_setting,
                    saveSetting,
                    self.ui.niceSpinSelect.set_value,
                    self.ui.niceSpinSelect.get_value_as_int,
                )
            ],
            client_conf: [
                (
                    'collision-protect',
                    self._settings[sys_settings_plg_id]['misc']['collisionprotect'],
                    int,
                    fill_setting,
                    saveSetting,
                    self.ui.collisionProtectionCombo.set_active,
                    self.ui.collisionProtectionCombo.get_active,
                ),
                (
                    'config-protect',
                    self._settings[sys_settings_plg_id]['misc']['configprotect'],
                    list,
                    fill_setting_view,
                    save_setting_view,
                    self.configProtectModel,
                    self.configProtectView,
                ),
                (
                    'config-protect-mask',
                    self._settings[sys_settings_plg_id]['misc']['configprotectmask'],
                    list,
                    fill_setting_view,
                    save_setting_view,
                    self.configProtectMaskModel,
                    self.configProtectMaskView,
                ),
                (
                    'config-protect-skip',
                    self._settings[sys_settings_plg_id]['misc']['configprotectskip'],
                    list,
                    fill_setting_view,
                    save_setting_view,
                    self.configProtectSkipModel,
                    self.configProtectSkipView,
                ),
                (
                    'files-backup',
                    self._settings[sys_settings_plg_id]['misc']['filesbackup'],
                    bool,
                    fill_setting,
                    saveSetting,
                    self.ui.filesBackupCheckbutton.set_active,
                    self.ui.filesBackupCheckbutton.get_active,
                ),
                (
                    'relaxed_deps',
                    SulfurConf.relaxed_deps,
                    int,
                    fill_sulfurconf,
                    save_sulfurconf,
                    self.ui.depResAlgoCombo.set_active,
                    self.ui.depResAlgoCombo.get_active,
                ),
            ],
            conf_files['repositories']: [
                (
                    'download-speed-limit',
                    self._settings['repositories']['transfer_limit'],
                    int,
                    fill_setting,
                    saveSetting,
                    self.ui.speedLimitSpin.set_value,
                    self.ui.speedLimitSpin.get_value_as_int,
                )
            ],
        }

        # load data
        for config_file in self._preferences:
            for name, setting, mytype, fillfunc, savefunc, wgwrite, wgread in \
                self._preferences[config_file]:

                if mytype == list:
                    fillfunc(wgwrite, wgread, setting)
                else:
                    fillfunc(name, mytype, wgwrite, setting)

        rc, e = SulfurConf.save()
        if not rc:
            okDialog( self.ui.main, "%s: %s" % (_("Error saving preferences"), e) )
        self.on_Preferences_toggled(None, False)

    def setup_masked_pkgs_warning_box(self):
        mytxt = "<b><big><span foreground='#FF0000'>%s</span></big></b>\n%s" % (
            _("Attention"),
            _("These packages are masked either by default or due to your choice. Please be careful, at least."),
        )
        self.ui.maskedWarningLabel.set_markup(mytxt)

    def setup_editor(self):

        pathenv = os.getenv("PATH")
        if os.path.isfile("/etc/profile.env"):
            f = open("/etc/profile.env")
            env_file = f.readlines()
            for line in env_file:
                line = line.strip()
                if line.startswith("export PATH='"):
                    line = line[len("export PATH='"):]
                    line = line.rstrip("'")
                    for path in line.split(":"):
                        pathenv += ":"+path
                    break
        os.environ['PATH'] = pathenv

        self._file_editor = '/usr/bin/xterm -e $EDITOR'
        de_session = os.getenv('DESKTOP_SESSION')
        if de_session == None: de_session = ''
        path = os.getenv('PATH').split(":")
        if os.access("/usr/bin/xdg-open", os.X_OK):
            self._file_editor = "/usr/bin/xdg-open"
        if de_session.find("kde") != -1:
            for item in path:
                itempath = os.path.join(item, 'kwrite')
                itempath2 = os.path.join(item, 'kedit')
                itempath3 = os.path.join(item, 'kate')
                if os.access(itempath, os.X_OK):
                    self._file_editor = itempath
                    break
                elif os.access(itempath2, os.X_OK):
                    self._file_editor = itempath2
                    break
                elif os.access(itempath3, os.X_OK):
                    self._file_editor = itempath3
                    break
        else:
            if os.access('/usr/bin/gedit', os.X_OK):
                self._file_editor = '/usr/bin/gedit'

    def start_working(self, do_busy = True):
        self._is_working = True
        if do_busy:
            busy_cursor(self.ui.main)
        #self.ui.progressVBox.grab_add()

    def end_working(self):
        self._is_working = False
        #self.ui.progressVBox.grab_remove()
        normal_cursor(self.ui.main)

    def setup_application(self, on_init = False):
        msg = _('Generating metadata. Please wait.')
        self.set_status_ticker(msg)
        count = 30
        while count:
            try:
                self.show_packages(on_init = on_init)
            except ProgrammingError as e:
                self.set_status_ticker("%s: %s, %s" % (
                        _("Error during list population"),
                        e,
                        _("Retrying in 1 second."),
                    )
                )
                time.sleep(1)
                count -= 1
                continue
            break

    def clean_entropy_caches(self):
        self._entropy.clear_cache()
        # clear views
        self.etpbase.clear_groups()
        self.etpbase.clear_cache()
        self.setup_application()

    def _populate_files_update(self):
        # load filesUpdate interface and fill self.filesView
        with self._privileges:
            file_updates = self._get_file_updates()
            cached = file_updates.scan(quiet = True)
            if cached:
                self.filesView.populate(cached)

    def show_sulfur_tips(self):
        if SulfurConf.show_startup_tips:
            win = TipsWindow(self.ui.main)
            win.show()

    def show_notice_board(self, force = True):
        repoids = {}
        for repoid in self._entropy.repositories():
            if self._entropy.is_noticeboard_marked_as_read(repoid) and not force:
                continue
            avail_repos = self._settings['repositories']['available']
            board_file = avail_repos[repoid]['local_notice_board']
            if not (os.path.isfile(board_file) and \
                os.access(board_file, os.R_OK)):
                continue
            if entropy.tools.get_file_size(board_file) < 10:
                continue
            repoids[repoid] = board_file
        if repoids:
            self.load_notice_board(repoids)
        else:
            self.show_sulfur_tips()

    def load_notice_board(self, repoids):
        my = NoticeBoardWindow(self.ui.main, self._entropy)
        my.load(repoids)

    def update_repositories(self, repos, complete_cb = None):

        def _update_repos_done(rc, repoConn):

            for repo in repos:
                # inform UGC that we are syncing this repo
                webserv = self._get_webservice(repo)
                if webserv is None:
                    continue
                try:
                    available = webserv.service_available()
                except WebService.WebServiceException:
                    continue
                if not available:
                    continue
                try:
                    webserv.add_downloads([repo])
                except WebService.WebServiceException as err:
                    const_debug_write(__name__, repr(err))
                    continue

            if repoConn.sync_errors or (rc != 0):
                self.progress.set_mainLabel(_('Errors updating repositories.'))
                self.progress.set_subLabel(
                    _('Please check logs below for more info'))
            else:
                self.progress.set_mainLabel(
                    _('Repositories updated successfully'))
                if repoConn.new_entropy:
                    self.progress.set_extraLabel(
                        _('sys-apps/entropy needs to be updated as soon as possible.'))

            self._entropy.unlock_resources()
            self.end_working()

            self.progress.reset_progress()
            self.reset_cache_status()
            self.setup_repoView()
            self.gtk_loop()
            self.setup_application()
            self.set_package_radio('updates')
            self.ui_lock(False)

            self.disable_ugc = False
            self.show_notebook_tabs_after_install()
            if self._ugc_status:
                gobject.timeout_add(20*1000,
                    self.spawn_user_generated_content_first)

        with self._privileges:

            self.disable_ugc = True
            # acquire Entropy resources here to avoid surpises afterwards
            # this might be superfluous
            acquired = self._entropy.lock_resources()
            if not acquired:
                okDialog(self.ui.main,
                    _("Another Entropy instance is locking this task at the moment. Try in a few minutes."))
                self.disable_ugc = False
                return False

            force = self.ui.forceRepoUpdate.get_active()
            try:
                repoConn = self._entropy.Repositories(repos, force = force)
            except AttributeError:
                repo_conf = self._settings.get_setting_files_data(
                    )['repositories']
                msg = "%s: %s" % (_('No repositories specified in'),
                    repo_conf,)
                self.progress_log( msg, extra = "repositories")
                self._entropy.unlock_resources()
                self.disable_ugc = False
                return 127
            except Exception as e:
                msg = "%s: %s" % (_('Unhandled exception'), e,)
                self.progress_log(msg, extra = "repositories")
                self._entropy.unlock_resources()
                self.disable_ugc = False
                return 2

            # this is in EXACT order to avoid GTK complaining

            self.show_progress_bars()
            self.progress.set_mainLabel(_('Updating repositories...'))

            self.hide_notebook_tabs_for_install()
            self.set_status_ticker(_("Running tasks"))

            self.start_working(do_busy = True)
            normal_cursor(self.ui.main)
            self.progress.show()
            self.switch_notebook_page('output')
            self.ui_lock(True)

            def run_up():
                with self._privileges:
                    rc = repoConn.sync()
                    gobject.idle_add(_update_repos_done, rc, repoConn)

            t = ParallelTask(run_up)
            t.start()

    def dependencies_test(self):

        self.show_progress_bars()
        self.progress.set_mainLabel(_('Testing dependencies...'))

        self.hide_notebook_tabs_for_install()
        self.set_status_ticker(_("Running tasks"))

        self.start_working(do_busy = True)
        normal_cursor(self.ui.main)
        self.progress.show()
        self.switch_notebook_page('output')
        self.ui_lock(True)

        def deptest_reset_all():
            self.end_working()
            self.progress.reset_progress()
            self.show_notebook_tabs_after_install()
            self.ui_lock(False)
            self.gtk_loop()

        def _deptest_done(deps_not_matched):
            if not deps_not_matched:
                okDialog(self.ui.main, _("No missing dependencies found."))
                deptest_reset_all()
                self.switch_notebook_page('preferences')
                return

            c_repo = self._entropy.installed_repository()
            found_matches = set()
            not_all = False
            for dep in deps_not_matched:
                match = self._entropy.atom_match(dep)
                if match[0] != -1:
                    found_matches.add(match)
                    continue
                else:
                    iddep = c_repo.searchDependency(dep)
                    if iddep == -1:
                        continue
                    c_idpackages = c_repo.searchPackageIdFromDependencyId(
                        iddep)
                    for c_idpackage in c_idpackages:
                        key, slot = c_repo.retrieveKeySlot(
                            c_idpackage)
                        match = self._entropy.atom_match(key, match_slot = slot)
                        cmpstat = 0
                        if match[0] != -1:
                            cmpstat = self._entropy.get_package_action(match)
                        if cmpstat != 0:
                            found_matches.add(match)
                            continue
                        else:
                            not_all = True
                    continue

                not_all = True

            if not found_matches:
                okDialog(self.ui.main,
                    _("Missing dependencies found, but none of them are on the repositories."))
                self.switch_notebook_page('preferences')
                deptest_reset_all()
                return

            if not_all:
                okDialog(self.ui.main,
                    _("Some missing dependencies have not been matched, others are going to be added to the queue."))
            else:
                okDialog(self.ui.main,
                    _("All the missing dependencies are going to be added to the queue"))

            self.add_atoms_to_queue([], matches = found_matches)
            self.switch_notebook_page("preferences")
            deptest_reset_all()

        def run_up():
            with self._async_event_execution_lock:
                rc = self._entropy.dependencies_test()
                gobject.idle_add(_deptest_done, rc)

        t = ParallelTask(run_up)
        t.start()

    def libraries_test(self):

        self.show_progress_bars()
        self.progress.set_mainLabel(_('Testing libraries...'))

        self.hide_notebook_tabs_for_install()
        self.set_status_ticker(_("Running tasks"))

        self.start_working(do_busy = True)
        normal_cursor(self.ui.main)
        self.ui.abortQueue.show()
        self.progress.show()
        self.switch_notebook_page('output')
        self.ui_lock(True)

        def do_stop():
            self.end_working()
            self.progress.reset_progress()
            self.ui.abortQueue.hide()
            self.show_notebook_tabs_after_install()
            self.ui_lock(False)
            self.gtk_loop()

        def task_bombing():
            if self.abortQueueNow:
                self.abortQueueNow = False
                raise KeyboardInterrupt('Simulated Keyboard Interrupt')

        QA = self._entropy.QA()

        def _libtest_done(packages_matched, broken_execs, abort):
            if self.do_debug and abort:
                print_generic("libraries_test: scan abort")
            if self.do_debug:
                print_generic("libraries_test: done scanning")

            if abort:
                okDialog(self.ui.main, _("Libraries test aborted"))
                do_stop()
                return

            matches = set()
            for key in list(packages_matched.keys()):
                matches |= packages_matched[key]

            if broken_execs:
                okDialog(self.ui.main,
                    _("Some broken packages have not been matched, others are going to be added to the queue."))
            else:
                okDialog(self.ui.main,
                    _("All the broken packages are going to be added to the queue"))

            rc = self.add_atoms_to_queue([], matches = matches)
            self.switch_notebook_page("preferences")

            do_stop()

        def run_up():
            with self._async_event_execution_lock:
                try:
                    packages_matched, broken_execs, z = QA.test_shared_objects(
                        self._entropy.installed_repository(),
                            task_bombing_func = task_bombing)
                    gobject.idle_add(_libtest_done, packages_matched,
                        broken_execs, False)
                except KeyboardInterrupt:
                    gobject.idle_add(_libtest_done, None, None, True)

        t = ParallelTask(run_up)
        t.start()

    def reset_progress_text(self):
        self.progress.set_mainLabel("")
        self.progress.set_subLabel("")
        self.progress.set_extraLabel("")
        self.hide_progress_bars()

    def hide_progress_bars(self):
        self.ui.progressBar.hide()
        #self.progress.hide()

    def show_progress_bars(self):
        self.ui.progressBar.show()
        #self.progress.show()

    def reset_queue_progress_bars(self):
        self.progress.reset_progress()

    def setup_repoView(self):
        self.repoView.populate()

    def set_package_radio(self, tag):
        self.lastPkgPB = tag
        widget = self.packageRB[tag]
        widget.set_active(True)

    def set_notebook_page(self, page):
        ''' Switch to Page in GUI'''
        self.ui.notebook.set_current_page(page)

    def set_status_ticker( self, text ):
        ''' Write Message to Statusbar'''
        def do_set(text):
            context_id = self.ui.status.get_context_id( "Status" )
            self.ui.status.push( context_id, text )
            return False
        gobject.timeout_add(0, do_set, text)

    def progress_log(self, msg, extra = None):
        self.progress.set_subLabel( msg )

        mytxt = []
        slice_count = self.console.get_column_count()
        while msg:
            my = msg[:slice_count]
            msg = msg[slice_count:]
            mytxt.append(my)

        for txt in mytxt:
            if extra:
                self.console.feed_child("%s: %s\n\r" % (extra, txt,))
                continue
            self.console.feed_child("%s\n\r" % (txt,))

    def progress_log_write(self, msg):
        self.console.feed_child(msg + "\n\r")

    def enable_skip_mirror(self):
        self.ui.skipMirror.show()
        self.skipMirror = True

    def disable_skip_mirror(self):
        self.ui.skipMirror.hide()
        self.skipMirror = False

    def add_to_queue(self, pkgs, action, always_ask, accept = False):

        q_cache = {}
        for obj in pkgs:
            q_cache[obj.matched_atom] = obj.queued
            obj.queued = action

        status, myaction = self.queue.add(pkgs, always_ask = always_ask,
            accept = accept)
        if status != 0:
            for obj in pkgs:
                obj.queued = q_cache.get(obj.matched_atom)
            return False

        return True

    def _show_orphans_message(self, orphans, syspkg_orphans, unavail_repo_pkgs):

        if orphans:
            confirm = ConfirmationDialog(self.ui.main,
                orphans,
                top_text = _("These packages are no longer available"),
                sub_text = _("These packages should be removed (if you agree) because support has been dropped. Do you want to remove them?"),
                bottom_text = '',
                bottom_data = ''
            )
            result = confirm.run()
            ok = False
            if result == -5: # ok
                ok = True
            confirm.destroy()

            if ok:
                self.add_to_queue(orphans, "r", False, accept = True)

        if syspkg_orphans:
            d = ConfirmationDialog(self.ui.main, syspkg_orphans,
                top_text = _("These are orphaned vital packages"),
                sub_text = _("You should make sure that they are no longer needed and remove manually."),
                bottom_text = '',
                bottom_data = '',
                cancel = False)
            d.run()
            d.destroy()
        if unavail_repo_pkgs:
            d = ConfirmationDialog(self.ui.main, unavail_repo_pkgs,
                top_text = _("These are packages from unavailable repositories"),
                sub_text = _("You are not going to receive updates for the following packages."),
                bottom_text = '',
                bottom_data = '',
                cancel = False)
            d.run()
            d.destroy()

        return False

    def _set_updates_label(self, updates_count):
        # set both simple and advanced mode labels
        txt_simple = "<b>%s</b>" % (updates_count,)
        txt_adv = txt_simple + " <small>%s</small>" % (_("updates"),)
        self.ui.rbUpdatesSimpleLabel.set_markup(txt_adv)
        self.ui.rbUpdatesLabel.set_markup(txt_adv)

    def _show_packages_group_caching(self):
        for k in ("installed", "reinstallable", "masked",
            "user_unmasked", "downgrade"):
            try:
                self.etpbase.get_groups(k)
            except (ProgrammingError, OperationalError):
                continue

    def show_packages(self, back_to_page = None, on_init = False):

        if self._startup_packages_install:
            # don't do anything on startup if packages install is triggered
            return

        action = self.lastPkgPB
        self.disable_ugc = True

        if action == "search":
            loading_data = self.etpbase.get_groups('loading')
            self.pkgView.populate(loading_data, empty = True)
            self.gtk_loop()

        allpkgs = self.etpbase.get_groups(action)

        if action == "updates":
            # speed up first queue taint iteration
            self.etpbase.get_groups("available")
            def _do_cached_timeout():
                gobject.idle_add(self._show_packages_group_caching,
                    priority = gobject.PRIORITY_LOW)
            gobject.timeout_add(2000, _do_cached_timeout)

            # set updates label
            raw_updates = len(self.etpbase.get_raw_groups('updates'))
            self._set_updates_label(raw_updates)

        empty = False
        do_switch_to = None
        if on_init and (not allpkgs) and action == "updates":
            # directly show available pkgs if no updates are available
            # at startup
            if SulfurConf.simple_mode:
                do_switch_to = "all"
            else:
                do_switch_to = "available"

        elif not allpkgs and action == "updates":
            allpkgs = self.etpbase.get_groups('fake_updates')
            empty = True

        self.set_status_ticker("%s: %s %s" % (
            _("Showing"), len(allpkgs), ngettext("item", "items", len(allpkgs)),))

        show_pkgsets = False
        if action == "pkgsets":
            show_pkgsets = True

        if not allpkgs:
            self.ui.updatesButtonboxAddRemove.hide()
        else:
            self.ui.updatesButtonboxAddRemove.show()

        if not allpkgs or (self.lastPkgPB == "pkgsets"):
            self.ui.pkgSorter.set_property('sensitive', False)
        elif allpkgs and (self.lastPkgPB != "pkgsets"):
            self.ui.pkgSorter.set_property('sensitive', True)

        self.pkgView.populate(allpkgs, empty = empty, pkgsets = show_pkgsets)

        if back_to_page:
            self.switch_notebook_page(back_to_page)

        # reset labels
        self.reset_queue_progress_bars()
        self.disable_ugc = False

        if do_switch_to:
            rb = self.packageRB[do_switch_to]
            gobject.timeout_add(200, rb.clicked)

    def add_atoms_to_queue(self, atoms, always_ask = False, matches = None):

        if matches is None:
            matches = set()

        if not matches:
            # resolve atoms ?
            for atom in atoms:
                match = self._entropy.atom_match(atom)
                if match[0] != -1:
                    matches.add(match)
        if not matches:
            okDialog( self.ui.main,
                _("No packages need or can be queued at the moment.") )
            return

        resolved = []

        self.etpbase.get_groups('installed')
        self.etpbase.get_groups('available')
        self.etpbase.get_groups('reinstallable')
        self.etpbase.get_groups('updates')
        self.etpbase.get_groups("downgrade")

        for match in matches:
            resolved.append(self.etpbase.get_package_item(match)[0])

        found_objs = []
        master_queue = []
        for key in self.queue.packages:
            master_queue += self.queue.packages[key]
        for obj in resolved:
            if obj in master_queue:
                continue
            found_objs.append(obj)

        if found_objs:
            return self.add_to_queue(found_objs, "u", always_ask)
        return True

    def reset_cache_status(self, quick = False):
        self.pkgView.clear()
        self.etpbase.clear_groups()
        self.etpbase.clear_cache()
        self.queue.clear()
        if quick:
            return
        # re-scan system settings, useful
        # if there are packages that have been
        # live masked, and anyway, better wasting
        # 2-3 more cycles than having unattended
        # behaviours
        self._settings.clear()
        self._entropy._validate_repositories()
        self._entropy.close_repositories()

    def hide_notebook_tabs_for_install(self):
        self.ui.prefsVbox.hide()
        self.ui.reposVbox.hide()
        self.ui.systemVbox.hide()
        self.ui.packagesVbox.hide()
        self.ui.progressVBox.show()

    def show_notebook_tabs_after_install(self):
        self.ui.systemVbox.show()
        self.ui.packagesVbox.show()
        self.switch_application_mode(SulfurConf.simple_mode)

    def run_search_package_dialog(self):

        def fake_callback(s):
            return s

        def do_name_search(keyword):
            keyword = const_convert_to_unicode(keyword)
            matches = []
            for repoid in self._entropy.repositories():
                dbconn = self._entropy.open_repository(repoid)
                try:
                    results = dbconn.searchPackages(keyword, just_id = True,
                        order_by = "atom")
                except OperationalError:
                    continue
                matches += [(x, repoid) for x in results]
            # disabled due to duplicated entries annoyance
            #results = self._entropy.installed_repository().searchPackages(keyword,
            #    just_id = True)
            #matches += [(x, 0) for x in results]
            return matches

        def do_name_desc_search(keyword):
            keyword = const_convert_to_unicode(keyword)
            matches = []
            for repoid in self._entropy.repositories():
                dbconn = self._entropy.open_repository(repoid)
                try:
                    results = dbconn.searchDescription(keyword)
                except OperationalError:
                    continue
                matches += [(x, repoid) for atom, x in results]
            # disabled due to duplicated entries annoyance
            #results = self._entropy.installed_repository().searchDescription(
            #    keyword)
            #matches += [(x, 0) for atom, x in results]
            return matches

        search_reference = {
            0: do_name_search,
            1: do_name_desc_search,
        }
        search_types = [_("Name"), _("Name and description")]
        input_params = [
            ('search_string', _('Search string'), fake_callback, False),
            ('search_type', ('combo', (_('Search type'), search_types),), fake_callback, False)
        ]
        data = self._entropy.input_box(
            _('Entropy Search'),
            input_params,
            cancel_button = True
        )
        if data is None:
            return

        # clear filter bar
        self.ui.pkgFilter.set_text("")

        keyword = data.get('search_string', "").strip()
        if keyword:
            fn = search_reference[data['search_type'][0]]
            self.etpbase.set_search(fn, keyword)
            self.show_packages()

    def check_restart_needed(self, to_be_installed_matches):

        entropy_pkg = "sys-apps/entropy"

        etp_matches, etp_rc = self._entropy.atom_match(entropy_pkg,
            multi_match = True, multi_repo = True)
        if etp_rc != 0:
            return False

        found_match = None
        for etp_match in etp_matches:
            if etp_match in to_be_installed_matches:
                found_match = etp_match
                break

        if not found_match:
            return False
        rc, pkg_match = self._entropy.check_package_update(entropy_pkg, deep = True)
        if rc:
            return True
        return False

    def critical_updates_warning(self, install_queue):
        sys_set_client_plg_id = \
            etpConst['system_settings_plugins_ids']['client_plugin']
        misc_set = self._settings[sys_set_client_plg_id]['misc']
        if misc_set.get('forcedupdates'):
            crit_atoms, crit_mtchs = self._entropy.calculate_critical_updates()
            if crit_atoms:
                crit_objs = []
                for crit_match in crit_mtchs:
                    if crit_match in install_queue:
                        # it's already in the install queue, skip.
                        continue
                    crit_obj, c_new = self.etpbase.get_package_item(
                        crit_match)
                    if crit_obj:
                        crit_objs.append(crit_obj)

                if crit_objs:
                    crit_dialog = ConfirmationDialog(
                        self.ui.main,
                        crit_objs,
                        top_text = _("Please update the following critical packages"),
                        bottom_text = _("You should install them as soon as possible"),
                        simpleList = True
                    )
                    crit_dialog.okbutton.set_label(_("Abort action"))
                    crit_dialog.cancelbutton.set_label(_("Ignore"))
                    result = crit_dialog.run()
                    crit_dialog.destroy()
                    if result == -5: # ok
                        return True, True

            return False, len(crit_mtchs) > 0
        return False, False

    def install_queue(self, fetch = False, download_sources = False,
        remove_repos = None, direct_install_matches = None,
        direct_remove_matches = None, status_cb = None):
        try:
            self._process_queue(self.queue.packages,
                fetch_only = fetch, remove_repos = remove_repos,
                download_sources = download_sources,
                direct_install_matches = direct_install_matches,
                direct_remove_matches = direct_remove_matches,
                status_cb = status_cb)
        except SystemExit:
            raise
        except:
            if self.do_debug:
                entropy.tools.print_traceback()
                import pdb; pdb.set_trace()
            else:
                raise

    def _process_queue(self, pkgs, remove_repos = None, fetch_only = False,
            download_sources = False, direct_remove_matches = None,
            direct_install_matches = None, status_cb = None):

        if remove_repos is None:
            remove_repos = []
        if direct_remove_matches is None:
            direct_remove_matches = []
        if direct_install_matches is None:
            direct_install_matches = []
        self.show_progress_bars()
        file_updates = self._get_file_updates()

        def do_file_updates_check():
            file_updates.scan(dcache = False, quiet = True)
            fs_data = file_updates.scan()
            if fs_data:
                if len(fs_data) > 0:
                    switch_back_page = 'filesconf'

        def _post_install_cleanup(state):
            self.show_notebook_tabs_after_install()
            self.disable_ugc = False
            if switch_back_page is not None:
                self.switch_notebook_page(switch_back_page)
            elif state:
                self.switch_notebook_page('packages')
                # switch back to updates tab also
                rb = self.packageRB["updates"]
                gobject.timeout_add(0, rb.clicked)

            self._entropy.unlock_resources()

            if state:
                self.progress.set_mainLabel(_("Tasks completed successfully."))
                self.progress.set_subLabel(_("Please make sure to read all the messages in the terminal below."))
                self.progress.set_extraLabel("Have phun!")
            else:
                self.progress.set_mainLabel(_("Oh, a fairytale gone bad!"))
                self.progress.set_subLabel(_("Something bad happened, have a look at the messages in the terminal below."))
                self.progress.set_extraLabel(_("Don't feel guilty, it's all my fault!"))

        def _show_orphans_message(state):

            if not self._entropy.repositories():
                # ignore orphan message
                return

            if not state:
                return
            if self._orphans_message_shown:
                return

            orphans = None
            syspkg_orphans = None
            unavail_repo_pkgs = None
            if not self.etpbase.get_raw_groups('updates'):

                orphans = self.etpbase.get_raw_groups('orphans')
                syspkg_orphans = self.etpbase.get_raw_groups('syspkg_orphans')
                unavail_repo_pkgs = self.etpbase.get_raw_groups('unavail_orphans')
                if self.do_debug:
                    print_generic("_show_orphans_message: found orphans %s" % (orphans,))
                    print_generic("_show_orphans_message: found syspkg orphans %s" % (
                        syspkg_orphans,))
                    print_generic("_show_orphans_message: found unavail repo pkgs %s" % (
                        unavail_repo_pkgs,))
                self._orphans_message_shown = True

            if orphans or syspkg_orphans or unavail_repo_pkgs:
                # enqueue in the main loop, better!
                # avoid actions button to not show up
                gobject.timeout_add(2000, self._show_orphans_message, orphans,
                    syspkg_orphans, unavail_repo_pkgs)

        def _install_done(err, restart_needed, critical_updates):
            state = True

            if self.do_debug:
                print_generic("process_queue: left all")

            self.ui.skipMirror.hide()
            self.ui.abortQueue.hide()
            if self.do_debug:
                print_generic("process_queue: buttons now hidden")

            # deactivate UI lock
            if self.do_debug:
                print_generic("process_queue: unlocking gui?")
            self.ui_lock(False)
            if self.do_debug:
                print_generic("process_queue: gui unlocked")

            if (err == 0) and ((not fetch_only) and (not download_sources)):
                # this triggers post-branch upgrade function inside
                # Entropy Client SystemSettings plugin
                self._settings.clear()

            if err == 1: # install failed
                okDialog(self.ui.main,
                    _("Attention. An error occured while processing the queue."
                    "\nPlease have a look at the terminal.")
                )
                self.reset_cache_status()
                state = False
            elif err in (2, 3, 4):
                # 2: masked package cannot be unmasked
                # 3: license not accepted, move back to queue page
                # 4: conflicting dependencies were pulled in
                switch_back_page = 'packages'
                state = False
                if err == 4:
                    self.reset_cache_status()
            elif err != 0:
                # wtf?
                okDialog(self.ui.main,
                    _("Attention. Something really bad happened."
                    "\nPlease have a look at the terminal.")
                )
                self.reset_cache_status()
                state = False

            elif (err == 0) and (restart_needed or critical_updates) and \
                ((not fetch_only) and (not download_sources)):
                exit_st = 99
                if critical_updates:
                    okDialog(self.ui.main,
                        _("Attention. Other updates that must be installed."
                        "\nSulfur will be reloaded.")
                    )
                    exit_st = 98
                elif restart_needed:
                    okDialog(self.ui.main,
                        _("Attention. You have updated Entropy."
                        "\nSulfur will be reloaded.")
                    )
                self._entropy.unlock_resources()
                self.quit(sysexit = exit_st)

            if self.do_debug:
                print_generic("process_queue: end_working?")
            self.end_working()
            self.progress.reset_progress()
            if self.do_debug:
                print_generic("process_queue: end_working")

            if (not fetch_only) and (not download_sources) and not \
                (direct_install_matches or direct_remove_matches):

                if self.do_debug:
                    print_generic("process_queue: cleared caches")

                for myrepo in remove_repos:
                    self._entropy.remove_repository(myrepo) # ignore outcome

                self.reset_cache_status()
                if self.do_debug:
                    print_generic("process_queue: closed repo dbs")
                self._entropy.reopen_installed_repository()
                if self.do_debug:
                    print_generic("process_queue: cleared caches (again)")
                # regenerate packages information
                if self.do_debug:
                    print_generic("process_queue: setting up Sulfur")
                self.setup_application()
                if self.do_debug:
                    print_generic("process_queue: scanning for new files")
                do_file_updates_check()
                if self.do_debug:
                    print_generic("process_queue: all done")

            if direct_install_matches or direct_remove_matches:
                do_file_updates_check()
            _post_install_cleanup(state)
            if state:
                self.queue.clear()
            if status_cb is not None:
                status_cb(state)
            _show_orphans_message(state)
            if self._startup_packages_install:
                self._startup_packages_install = None
                self.gtk_loop()
                def do_show():
                    self.show_packages(on_init = True)
                gobject.idle_add(do_show)


        with self._privileges:

            self.disable_ugc = True
            # acquire Entropy resources here to avoid surpises afterwards
            # this might be superfluous
            acquired = self._entropy.lock_resources()
            if not acquired:
                okDialog(self.ui.main,
                    _("Another Entropy instance is locking this task at the moment. Try in a few minutes."))
                self.disable_ugc = False
                return False

            switch_back_page = None
            self.hide_notebook_tabs_for_install()
            self.set_status_ticker(_("Running tasks"))
            total = 0
            if direct_install_matches or direct_remove_matches:
                total = len(direct_install_matches) + len(direct_remove_matches)
            else:
                for key in pkgs:
                    total += len(pkgs[key])

            if total > 0:

                self.start_working(do_busy = True)
                normal_cursor(self.ui.main)
                self.progress.show()
                self.progress.set_mainLabel( _( "Processing Packages in queue" ) )
                self.switch_notebook_page('output')

                if direct_install_matches or direct_remove_matches:
                    install_queue = direct_install_matches
                    selected_by_user = set(install_queue)
                    removal_queue = direct_remove_matches
                    do_purge_cache = set()
                else:
                    queue = []
                    for key in pkgs:
                        if key == "r":
                            continue
                        queue += pkgs[key]
                    install_queue = [x.matched_atom for x in queue]
                    selected_by_user = set([x.matched_atom for x in queue if \
                        x.selected_by_user])
                    removal_queue = [x.matched_atom[0] for x in pkgs['r']]
                    do_purge_cache = set([x.matched_atom[0] for x in pkgs['r'] if \
                        x.do_purge])

                # look for critical updates
                crit_block = False
                crit_updates = False
                if install_queue and ((not fetch_only) and (not download_sources)):
                    crit_block, crit_updates = self.critical_updates_warning(
                        install_queue)
                # check if we also need to restart this application
                restart_needed = self.check_restart_needed(install_queue)

                if (install_queue or removal_queue) and not crit_block:

                    # activate UI lock
                    self.ui_lock(True)

                    controller = QueueExecutor(self)
                    def spawn_install():
                        with self._async_event_execution_lock:
                            with self._privileges:
                                try:
                                    e = controller.run(install_queue[:],
                                        removal_queue[:], do_purge_cache,
                                        fetch_only = fetch_only,
                                        download_sources = download_sources,
                                        selected_by_user = selected_by_user)
                                except:
                                    entropy.tools.print_traceback()
                                    e, i = 1, None
                                gobject.idle_add(_install_done, e,
                                    restart_needed, crit_updates)

                    t = ParallelTask(spawn_install)
                    t.start()

            else:
                self.set_status_ticker( _( "No packages selected" ) )
                _post_install_cleanup(True)

    def ui_lock(self, lock):
        self.ui.menubar.set_sensitive(not lock)

    def switch_notebook_page(self, page):
        self.on_PageButton_changed(None, page)

####### events

    def _get_selected_repo_index( self ):
        selection = self.repoView.view.get_selection()
        repodata = selection.get_selected()
        # get text
        if repodata[1] != None:
            repoid = self.repoView.get_repoid(repodata)
            # do it if it's enabled
            repo_order = self._settings['repositories']['order']
            if repoid in repo_order:
                idx = repo_order.index(repoid)
                return idx, repoid, repodata
        return None, None, None

    def run_editor(self, filename, delete = False):
        cmd = ' '.join([self._file_editor, filename])
        task = ParallelTask(self.__run_editor, cmd, delete, filename)
        task.start()

    def __run_editor(self, cmd, delete, filename):
        os.system(cmd+"&> /dev/null")
        if delete and os.path.isfile(filename) and os.access(filename, os.W_OK):
            try:
                os.remove(filename)
            except OSError:
                pass

    def _get_Edit_filename(self):
        selection = self.filesView.view.get_selection()
        model, iterator = selection.get_selected()
        if model != None and iterator != None:
            identifier = model.get_value( iterator, 0 )
            destination = model.get_value( iterator, 2 )
            source = model.get_value( iterator, 1 )
            source = os.path.join(os.path.dirname(destination), source)
            return identifier, source, destination
        return 0, None, None

    def queue_bombing(self):
        if self.do_debug:
            print_generic("queue_bombing: bomb?")
        if self.abortQueueNow:
            if self.do_debug:
                print_generic("queue_bombing: BOMBING !!!")
            self.abortQueueNow = False
            raise KeyboardInterrupt('Simulated keyboard interrupt')

    def mirror_bombing(self):

        if self.skipMirrorNow:
            self.skipMirrorNow = False
            mytxt = _("Skipping current mirror.")
            raise OnlineMirrorError('OnlineMirrorError %s' % (mytxt,))

        if self.abortQueueNow:
            self.abortQueueNow = False
            if self.do_debug:
                print_generic("mirror_bombing: queue BOMB !!!")
            # do not reset self.abortQueueNow here, we need
            # mirror_bombing to keep crashing
            raise KeyboardInterrupt('Simulated keyboard interrupt')


    def load_ugc_repositories(self):
        self.ugcRepositoriesModel.clear()
        repo_order = self._settings['repositories']['order']
        repo_excluded = self._settings['repositories']['excluded']
        avail_repos = self._settings['repositories']['available']
        for repoid in repo_order+sorted(repo_excluded.keys()):
            repodata = avail_repos.get(repoid)
            if repodata == None:
                repodata = repo_excluded.get(repoid)
            if repodata == None:
                continue # wtf?
            self.ugcRepositoriesModel.append([repodata])

    def load_color_settings(self):
        for key, s_widget in list(self.colorSettingsMap.items()):
            if not hasattr(SulfurConf, key):
                if self.do_debug: print_generic("WARNING: no %s in SulfurConf" % (key,))
                continue
            color = getattr(SulfurConf, key)
            s_widget.set_color(gtk.gdk.color_parse(color))


