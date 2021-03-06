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

import sys
import time
import shutil
import subprocess

import gtk
import gobject
import pango

from entropy.i18n import _, _LOCALE
from entropy.output import decolorize
from entropy.exceptions import *
from entropy.const import *
from entropy.misc import ParallelTask
from entropy.services.client import WebService
from entropy.client.services.interfaces import Document, DocumentList, \
    DocumentFactory, ClientWebService

import entropy.dep
import entropy.tools

from sulfur.event import SulfurSignals
from sulfur.core import UI, busy_cursor, normal_cursor, \
    resize_image, resize_image_height, load_url, get_entropy_webservice, \
        Privileges
from sulfur.setup import const, cleanMarkupString, SulfurConf

class MenuSkel:

    def _getAllMethods(self):
        result = {}
        allAttrNames = list(self.__dict__.keys()) + self._getAllClassAttributes()
        for name in allAttrNames:
            value = getattr(self, name)
            if hasattr(value, '__call__'):
                result[name] = value
        return result

    def _getAllClassAttributes(self):
        nameSet = {}
        for currClass in self._getAllClasses():
            nameSet.update(currClass.__dict__)
        result = list(nameSet.keys())
        return result

    def _getAllClasses(self):
        result = [self.__class__]
        i = 0
        while i < len(result):
            currClass = result[i]
            result.extend(list(currClass.__bases__))
            i = i + 1
        return result

class TipsWindow(MenuSkel):

    TIPS = [
        _("Did you know that you can comment, vote and add documents to applications like in a wiki?"),
        _("Did you know that you can add icons or files to applications by simply dropping images from your Desktop onto them?"),
        _("Did you know that Sulfur has an Advanced mode, just click Sulfur -> Advanced mode?"),
        _("Did you know that the guy who wrote this tip was really asleep at the time?"),
        _("Did you know that you can backup your installed application repository by enabling Advanced mode and going to Preferences tab?"),
        _("Did you know that you can customize interface colors by enabling Advanced mode and going to Preferences tab?"),
    ]

    def __init__(self, parent):
        self._tips_index = 0
        self.tips_ui = UI( const.GLADE_FILE, 'sulfurTips', 'entropy' )
        self.tips_ui.signal_autoconnect(self._getAllMethods())
        self.tips_ui.sulfurTips.set_transient_for(parent)
        self.window = self.tips_ui.sulfurTips
        self.label = self.tips_ui.sulfurTipsLabel
        self.label.set_markup(TipsWindow.TIPS[self._tips_index])
        self.tips_ui.sulfurTipShowStartup.set_active(
            SulfurConf.show_startup_tips)

    def show(self):
        self.window.present()

    def on_sulfurTipShowStartup_toggled(self, widget):
        if SulfurConf.show_startup_tips == 0:
            SulfurConf.show_startup_tips = 1
        else:
            SulfurConf.show_startup_tips = 0
        SulfurConf.save()

    def on_sulfurTipsPrevButton_clicked(self, widget):
        self._tips_index = (self._tips_index - 1) % len(TipsWindow.TIPS)
        self.label.set_markup(TipsWindow.TIPS[self._tips_index])

    def on_sulfurTipsNextButton_clicked(self, widget):
        self._tips_index = (self._tips_index + 1) % len(TipsWindow.TIPS)
        self.label.set_markup(TipsWindow.TIPS[self._tips_index])

    def on_sulfurTipsCloseButton_clicked(self, widget):
        self.window.hide()
        return True

    def on_sulfurTips_delete_event(self, *args):
        self.window.hide()
        return True

class AddRepositoryWindow(MenuSkel):

    def __init__(self, application, window, entropy):

        from sulfur.views import EntropyRepositoryMirrorsView
        self.addrepo_ui = UI( const.GLADE_FILE, 'addRepoWin', 'entropy' )
        self.addrepo_ui.signal_autoconnect(self._getAllMethods())
        self.repoMirrorsView = EntropyRepositoryMirrorsView(
            self.addrepo_ui.mirrorsView)
        self.addrepo_ui.addRepoWin.set_transient_for(window)
        self._entropy = entropy
        self.Sulfur = application
        self.window = window
        self.addrepo_ui.repoSubmit.show()
        self.addrepo_ui.repoSubmitEdit.hide()
        self.addrepo_ui.repoInsert.show()
        self.addrepo_ui.repoidEntry.set_editable(True)
        self.addrepo_ui.repodbcformatEntry.set_active(0)
        self.addrepo_ui.repoidEntry.set_text("")
        self.addrepo_ui.repoDescEntry.set_text("")
        self.addrepo_ui.repodbEntry.set_text("")
        self.repoMirrorsView.populate()

    def load(self):
        self.addrepo_ui.addRepoWin.show()

    def _load_repo_data(self, repodata):

        self.addrepo_ui.repoidEntry.set_text(repodata['repoid'])
        self.addrepo_ui.repoDescEntry.set_text(repodata['description'])
        self.repoMirrorsView.store.clear()
        for x in repodata['plain_packages']:
            self.repoMirrorsView.add(x)
        idx = 0
        # XXX hackish way fix it
        while idx < 100:
            self.addrepo_ui.repodbcformatEntry.set_active(idx)
            dbc_format_entry = self.addrepo_ui.repodbcformatEntry
            if repodata['dbcformat'] == dbc_format_entry.get_active_text():
                break
            idx += 1
        self.addrepo_ui.repodbEntry.set_text(repodata['plain_database'])

    def _get_repo_data(self):
        repodata = {}
        repodata['repoid'] = self.addrepo_ui.repoidEntry.get_text()
        repodata['description'] = self.addrepo_ui.repoDescEntry.get_text()
        repodata['plain_packages'] = self.repoMirrorsView.get_all()
        repodata['dbcformat'] = self.addrepo_ui.repodbcformatEntry.get_active_text()
        repodata['plain_database'] = self.addrepo_ui.repodbEntry.get_text()
        return repodata

    def _validate_repo_submit(self, repodata, edit = False):

        errors = []
        if not repodata['repoid']:
            errors.append(_('No Repository Identifier'))

        if repodata['repoid'] and repodata['repoid'] in self._entropy.Settings()['repositories']['available']:
            if not edit:
                errors.append(_('Duplicated Repository Identifier'))

        if repodata['repoid']:
            valid = entropy.tools.validate_repository_id(repodata['repoid'])
            if not valid:
                errors.append(_("Invalid Repository Identifier"))

        if not repodata['description']:
            repodata['description'] = "No description"

        if not repodata['plain_packages']:
            errors.append(_("No download mirrors"))

        if not repodata['plain_database'] or \
            (not entropy.tools.is_valid_uri(repodata['plain_database'])):

            errors.append(_("Repository URL must be a valid URL"))

        return errors

    def on_mirrorDown_clicked( self, widget ):
        selection = self.repoMirrorsView.view.get_selection()
        urldata = selection.get_selected()
        # get text
        if urldata[1] != None:
            next = urldata[0].iter_next(urldata[1])
            if next:
                self.repoMirrorsView.store.swap(urldata[1], next)

    def on_mirrorUp_clicked( self, widget ):
        selection = self.repoMirrorsView.view.get_selection()
        urldata = selection.get_selected()
        # get text
        if urldata[1] != None:
            path = urldata[0].get_path(urldata[1])[0]
            if path > 0:
                # get next iter
                prev = urldata[0].get_iter(path-1)
                self.repoMirrorsView.store.swap(urldata[1], prev)

    def on_repoMirrorEdit_clicked( self, widget ):
        selection = self.repoMirrorsView.view.get_selection()
        urldata = selection.get_selected()
        # get text
        if urldata[1] != None:
            text = self.repoMirrorsView.get_text(urldata)
            self.repoMirrorsView.remove(urldata)
            text = input_box(self.addrepo_ui.addRepoWin, _("Insert URL"),
                _("Enter a download mirror, HTTP or FTP")+"   ",
                input_text = text)
            # call liststore and tell to add
            self.repoMirrorsView.add(text)

    def on_repoMirrorRemove_clicked( self, widget ):
        selection = self.repoMirrorsView.view.get_selection()
        urldata = selection.get_selected()
        if urldata[1] != None:
            self.repoMirrorsView.remove(urldata)

    def on_repoMirrorAdd_clicked( self, widget ):

        text = input_box(self.addrepo_ui.addRepoWin, _("Insert URL"),
            _("Enter a download mirror URL")+"   ")
        # call liststore and tell to add
        if text:
            # validate url
            if not entropy.tools.is_valid_uri(text):
                okDialog( self.addrepo_ui.addRepoWin,
                    _("You must enter either a valid URL.") )
            else:
                self.repoMirrorsView.add(text)

    def on_repoInsert_clicked( self, widget ):
        text = input_box(self.addrepo_ui.addRepoWin, _("Insert Repository"),
            _("Insert Repository identification string")+"   ")
        if text:
            current_branch = self._entropy.Settings()['repositories']['branch']
            current_product = self._entropy.Settings()['repositories']['product']
            try:
                repoid, repodata = \
                    self._entropy.Settings()._analyze_client_repo_string(text,
                        current_branch, current_product)
                self._load_repo_data(repodata)
            except AttributeError:
                okDialog( self.addrepo_ui.addRepoWin,
                    _("This Repository identification string is malformed") )

    def on_repoCancel_clicked( self, widget ):
        self.addrepo_ui.addRepoWin.hide()
        self.addrepo_ui.addRepoWin.destroy()

    def on_repoSubmit_clicked( self, widget ):
        repodata = self._get_repo_data()
        # validate
        errors = self._validate_repo_submit(repodata)
        if not errors:
            added = self._entropy.add_repository(repodata)
            if not added:
                okDialog(self.addrepo_ui.addRepoWin,
                    _("Unable to add repository"))
            self.Sulfur.reset_cache_status()
            self.Sulfur.setup_repoView()
            self.addrepo_ui.addRepoWin.hide()
        else:
            msg = "%s: %s" % (_("Wrong entries, errors"), ', '.join(errors),)
            okDialog( self.addrepo_ui.addRepoWin, msg )

    def on_repoSubmitEdit_clicked( self, widget ):
        repodata = self._get_repo_data()
        errors = self._validate_repo_submit(repodata, edit = True)
        if errors:
            msg = "%s: %s" % (_("Wrong entries, errors"), ', '.join(errors),)
            okDialog( self.addrepo_ui.addRepoWin, msg )
            return True
        else:
            disable = False
            repo_excluded = self._entropy.Settings()['repositories']['excluded']
            if repodata['repoid'] in repo_excluded:
                disable = True
            removed = self._entropy.remove_repository(
                repodata['repoid'], disable = disable)
            if not removed:
                okDialog(self.addrepo_ui.addRepoWin,
                         _("Unable to remove/disable repository"))
            if not disable:
                added = self._entropy.add_repository(repodata)
                if not added:
                    okDialog(self.addrepo_ui.addRepoWin,
                             _("Unable to add repository"))
            self.Sulfur.reset_cache_status()

            self.Sulfur.setup_repoView()
            self.addrepo_ui.addRepoWin.hide()


class NoticeBoardWindow(MenuSkel):

    def __init__( self, window, entropy ):

        self.Entropy = entropy
        self.window = window

        self.nb_ui = UI( const.GLADE_FILE, 'noticeBoardWindow', 'entropy' )
        self.nb_ui.signal_autoconnect(self._getAllMethods())
        self.nb_ui.noticeBoardWindow.set_transient_for(self.window)

        mytxt = "<big><b>%s</b></big>\n<small>%s</small>" % (
            _("Repositories Notice Board"),
            _("Here below you will find a list of important news directly issued by your applications maintainers.\n" \
                "Double click on each item to retrieve detailed info."),
        )
        self.nb_ui.noticeBoardLabel.set_markup(mytxt)
        self.view = self.nb_ui.noticeView
        self.model = self.setup_view()

    def load(self, repoids, auto_hide = True):
        self.repoids = repoids
        self.show_data()

        # check if we actually pushed something to show
        do_show = True
        if auto_hide and (not self.model.get_iter_first()):
            do_show = False

        if do_show:
            self.view.expand_all()
            self.nb_ui.noticeBoardStfu.set_active(
                self.Entropy.are_noticeboards_marked_as_read())
            self.nb_ui.noticeBoardWindow.show()
        else:
            self.nb_ui.noticeBoardWindow.destroy()
            del self.nb_ui

    def setup_view(self):
        model = gtk.TreeStore( gobject.TYPE_PYOBJECT )
        self.view.set_model( model )

        self.create_text_column( _( "Notice" ), size = 200, expand = True,
            set_height = 40 )

        # Create read status pixmap
        cell = gtk.CellRendererPixbuf()
        column = gtk.TreeViewColumn( _("Status"), cell )
        column.set_cell_data_func( cell, self.status_pixbuf )
        column.set_sizing( gtk.TREE_VIEW_COLUMN_FIXED )
        column.set_fixed_width( 40 )
        self.view.append_column( column )

        return model

    def text_data_func( self, column, cell, model, iterator ):
        obj = model.get_value(iterator, 0)
        if obj:
            if 'is_repo' in obj:
                cell.set_property('markup',
                    "<big><b>%s</b></big>\n<small>%s</small>" % (
                        cleanMarkupString(obj['name']),
                            cleanMarkupString(obj['desc']),))
            else:
                mytxt = '<b><u>%s</u></b>\n<small><b>%s</b>: %s</small>' % (
                    cleanMarkupString(obj['pubDate']),
                    _("Title"),
                    cleanMarkupString(obj['title']),
                )
                cell.set_property('markup', mytxt)
            cell.set_property('cell-background', obj['color'])

    def status_pixbuf( self, column, cell, model, myiter ):
        obj = model.get_value( myiter, 0 ) or {}
        if obj.get('is_repo'):
            cell.set_property('stock-id', None)
        elif obj['read']:
            cell.set_property('stock-id', 'gtk-apply')
        else:
            cell.set_property('stock-id', 'gtk-cancel')
        cell.set_property('cell-background', obj['color'])

    def create_text_column( self, hdr, size = None, expand = False, set_height = 0 ):
        cell = gtk.CellRendererText()
        if set_height: cell.set_property('height', set_height)
        column = gtk.TreeViewColumn( hdr, cell )
        column.set_cell_data_func( cell, self.text_data_func )
        if size != None:
            column.set_sizing( gtk.TREE_VIEW_COLUMN_FIXED )
            column.set_fixed_width( size )
        column.set_resizable( False )
        column.set_expand( expand )
        self.view.append_column( column )

    def on_noticeBoardStfu_toggled(self, widget):
        for repoid in self.repoids:
            if widget.get_active():
                self.Entropy.mark_noticeboard_items_as_read(repoid)
            else:
                self.Entropy.unmark_noticeboard_items_as_read(repoid)

    def on_noticeBoardWindow_delete_event(self, *myargs):

        # store noticeboard items read status back to hd
        for mod_obj in self.model:
            for children in mod_obj.iterchildren():
                for obj in children:
                    if not obj:
                        continue
                    self.Entropy.set_noticeboard_item_read_status(
                        obj['repoid'], obj['id'], obj['read'])

        self.model.clear()
        self.nb_ui.noticeBoardWindow.destroy()
        del self.nb_ui

    def on_closeNoticeBoardButton_clicked(self, widget):
        self.on_noticeBoardWindow_delete_event(widget)

    def on_noticeView_row_activated(self, widget, iterator, path):
        ( model, iterator ) = widget.get_selection().get_selected()
        if model != None and iterator != None:
            obj = model.get_value(iterator, 0)
            if 'is_repo' not in obj:
                my = RmNoticeBoardMenu(self.nb_ui.noticeBoardWindow)
                my.load(obj)

    def show_data(self):
        self.model.clear()
        colors = ["#CDEEFF", "#AFCBDA"]
        avail_repos = self.Entropy.Settings()['repositories']['available']
        for repoid in self.repoids:

            items = self.Entropy.get_noticeboard(repoid).copy()
            if not items:
                continue

            counter = 0
            master_dict = {
                'is_repo': True,
                'name': repoid,
                'desc': avail_repos[repoid].get('description'),
                'path': self.repoids[repoid],
                'color': colors[0],
                'read': False,
                'repoid': repoid,
            }
            parent = self.model.append( None, (master_dict,) )
            read_items = self.Entropy.get_noticeboard_item_read_status(repoid)
            for key in sorted(items):
                counter += 1
                mydict = items[key].copy()
                mydict['color'] = colors[counter%len(colors)]
                mydict['id'] = key
                mydict['read'] = key in read_items
                mydict['repoid'] = repoid
                self.model.append( parent, (mydict,) )


class RmNoticeBoardMenu(MenuSkel):

    def __init__(self, window):

        self.window = window
        self.rm_ui = UI( const.GLADE_FILE, 'rmNoticeBoardInfo', 'entropy' )
        self.rm_ui.signal_autoconnect(self._getAllMethods())
        self.rm_ui.rmNoticeBoardInfo.set_transient_for(self.window)
        self.rm_ui.rmNoticeBoardInfo.add_events(gtk.gdk.BUTTON_PRESS_MASK)
        self.url = None
        self.item = None
        gtk.link_button_set_uri_hook(self.load_url, data=self.url)

    def load_url(self, widget, url, extra):
        if url:
            load_url(url)

    def on_rmNoticeBoardCloseButton_clicked(self, widget):
        self.rm_ui.rmNoticeBoardInfo.hide()
        self.rm_ui.rmNoticeBoardInfo.destroy()

    def on_rmNoticeBoardMarkRead_clicked(self, widget):
        if self.item:
            self.item['read'] = True

    def destroy(self):
        self.rm_ui.rmNoticeBoardInfo.destroy()

    def load(self, item):

        na = _("N/A")
        self.rm_ui.rmNoticeBoardIdLabel.set_text(str(item['id']))
        self.rm_ui.rmNoticeBoardDateLabel.set_text(cleanMarkupString(item['pubDate']))
        self.rm_ui.rmNoticeBoardTitleLabel.set_text(cleanMarkupString(item['title']))
        if item['link']:
            self.rm_ui.rmNoticeBoardLinkLabel.set_label(entropy.tools.spliturl(item['link']).netloc)
            self.rm_ui.rmNoticeBoardLinkLabel.set_uri(item['link'])
            self.url = item['link']
        self.rm_ui.rmNoticeBoardTextLabel.set_text(cleanMarkupString(item['description']))

        bold_items = [
            self.rm_ui.rmNoticeBoardId,
            self.rm_ui.rmNoticeBoardDate,
            self.rm_ui.rmNoticeBoardTitle,
            self.rm_ui.rmNoticeBoardLink
        ]
        small_items = [
            self.rm_ui.rmNoticeBoardIdLabel,
            self.rm_ui.rmNoticeBoardDateLabel,
            self.rm_ui.rmNoticeBoardTitleLabel,
        ]
        for xitem in bold_items:
            t = xitem.get_text()
            xitem.set_markup("<span foreground='%s'><small><b>%s</b></small></span>" % (SulfurConf.color_title, t,))
        for xitem in small_items:
            t = xitem.get_text()
            xitem.set_markup("<span foreground='%s'><small>%s</small></span>" % (SulfurConf.color_pkgsubtitle, t,))
        t = self.rm_ui.rmNoticeBoardTextLabel.get_text()
        self.rm_ui.rmNoticeBoardTextLabel.set_markup("<span foreground='%s'>%s</span>" % (SulfurConf.color_subdesc, t,))
        self.rm_ui.rmNoticeBoardInfo.show_all()
        self.item = item


class PkgInfoMenu(MenuSkel):

    def __init__(self, Entropy, pkg, window):

        self._pkg_meta = None
        self.pkg_pixmap = const.pkg_pixmap
        self.ugc_small_pixmap = const.ugc_small_pixmap
        self.ugc_pixmap = const.ugc_pixmap
        self.refresh_pixmap = const.refresh_pixmap
        self.star_normal_pixmap = const.star_normal_pixmap
        self.star_selected_pixmap = const.star_selected_pixmap
        self.star_empty_pixmap = const.star_empty_pixmap

        self._ugc_row_height = 48
        self._ugc_icon_store_path = None
        self.ugc_update_event_handler_id = None
        self.loading_pix = gtk.image_new_from_file(const.loading_pix)
        self.ugc_data = None
        self.ugc_status_message = None
        self.pkg = pkg
        self.vote = 0
        self.window = window
        self.Entropy = Entropy
        self.repository = None
        self.pkgkey = None
        self.__webserv = None

        self._page_tabs_map = {
            1: "details",
            2: "references",
            3: "dependencies",
            4: "other",
            5: "ugc"
        }
        self._page_tabs_data = {
            "details": {
                'loaded': False,
                'loader': self._details_page_loader,
            },
            "references": {
                'loaded': False,
                'loader': self._references_page_loader,
            },
            "dependencies": {
                'loaded': False,
                'loader': self._dependencies_page_loader,
            },
            "other": {
                'loaded': False,
                'loader': self._other_page_loader,
            },
            "ugc": {
                'loaded': False,
                'loader': self._ugc_page_loader,
            }
        }
        self.pkginfo_ui = UI( const.GLADE_FILE, 'pkgInfo', 'entropy' )
        self.pkginfo_ui.signal_autoconnect(self._getAllMethods())
        if self.window:
            self.pkginfo_ui.pkgInfo.set_transient_for(self.window)
        self.pkginfo_ui.pkgInfo.add_events(gtk.gdk.BUTTON_PRESS_MASK)
        # noeeees! otherwise voting won't work
        #self.pkginfo_ui.pkgInfo.connect('button-press-event', self.on_button_press)
        self.setupPkgPropertiesView()

        self.ugc_tab_clicked_signal_handler_id = \
            SulfurSignals.connect('pkg_properties__ugc_tab_clicked',
                self._ugc_tab_clicked)

    @property
    def _webserv(self):
        if self.repository is None:
            # cannot load !
            return None

        if self.__webserv == -1:
            # unsupported
            return None
        if self.__webserv is not None:
            return self.__webserv

        with Privileges():
            try:
                webserv = get_entropy_webservice(self.Entropy, self.repository)
            except WebService.UnsupportedService as err:
                webserv = None

            if webserv is None:
                self.__webserv = -1
                # not available
                return None

            try:
                available = webserv.service_available()
            except WebService.WebServiceException:
                available = False

        if not available:
            self.__webserv = -1
            # not available
            return

        self.__webserv = webserv
        return webserv

    def _set_pixbuf_to_cell(self, cell, path):
        try:
            pixbuf = gtk.gdk.pixbuf_new_from_file(path)
            cell.set_property( 'pixbuf', pixbuf )
        except gobject.GError:
            pass

    def ugc_pixbuf( self, column, cell, model, myiter ):
        obj = model.get_value( myiter, 0 )
        if isinstance(obj, dict):
            if obj.get('preview_path') is not None:
                self._set_pixbuf_to_cell(cell, obj['preview_path'])
            elif obj['image_path']:
                self._set_pixbuf_to_cell(cell, obj['image_path'])
            self._set_colors_to_cell(cell, obj)

    def ugc_content(self, column, cell, model, myiter):
        obj = model.get_value(myiter, 0)
        if obj is None:
            return

        self._set_colors_to_cell(cell, obj)

        if 'is_cat' in obj:
            cell.set_property('markup', "<b>%s</b>\n<small>%s</small>" % (
                obj['parent_desc'], _("Expand to browse"),))
        else:

            document_id = obj.document_id()
            document_type = obj.document_type()

            title = _("N/A")
            title_s = obj.get(Document.DOCUMENT_TITLE_ID)
            if title_s:
                title = const_convert_to_unicode(title_s).rstrip()

            description = _("N/A")
            description_s = obj.get(Document.DOCUMENT_DESCRIPTION_ID)
            if description_s:
                description = description_s

            desc_t = _("Description") + ": "
            if obj.is_comment():
                description = obj.document_data()
                description = cleanMarkupString(
                    const_convert_to_unicode(description))
                desc_t = "\n"

            first_txt = "<small>"
            username = obj.get(DocumentFactory.DOCUMENT_USERNAME_ID) or _("N/A")
            ts = obj.document_timestamp()
            ts = entropy.tools.convert_unix_time_to_human_time(ts)
            second_txt = "<b>%s</b>: %s, <i>%s</i>\n" % (
                _("Author"),
                username,
                ts,
            )
            third_txt = "<b>%s</b>: %s\n<b>%s</b><i>%s</i>" % (
                _("Title"),
                title,
                desc_t,
                description,
            )
            doc_keywords = obj.document_keywords().strip()
            if doc_keywords:
                keywords = doc_keywords.split()
                fourth_txt = "\n<b>%s</b>: %s</small>" % (
                    _("Keywords"),
                    ', '.join(keywords),
                )
            else:
                fourth_txt = "</small>"

            mytxt = first_txt + second_txt + third_txt + fourth_txt
            cell.set_property('markup', mytxt)

    def _set_colors_to_cell(self, cell, obj):
        odd = 0
        if 'counter' in obj:
            odd = obj['counter'] % 2
        if 'background' in obj:
            cell.set_property('cell-background', obj['background'][odd])
        else:
            cell.set_property('cell-background', None)
        try:
            if 'foreground' in obj:
                cell.set_property('foreground', obj['foreground'])
            else:
                cell.set_property('foreground', None)
        except TypeError:
            pass

    def on_button_press(self, widget, event):
        self.pkginfo_ui.pkgInfo.begin_move_drag(
                        event.button,
                        int(event.x_root),
                        int(event.y_root),
                        event.time)

    def disconnect_event_signals(self):
        # disconnect signals
        if self.ugc_update_event_handler_id is not None:
            SulfurSignals.disconnect(self.ugc_update_event_handler_id)
        if self.ugc_tab_clicked_signal_handler_id is not None:
            SulfurSignals.disconnect(self.ugc_tab_clicked_signal_handler_id)

    def on_closeInfo_clicked(self, widget):
        self.disconnect_event_signals()
        self.ugc_data = None
        self.pkginfo_ui.pkgInfo.hide()

    def on_pkgInfo_delete_event(self, widget, path):
        self.disconnect_event_signals()
        self.ugc_data = None
        self.pkginfo_ui.pkgInfo.hide()
        if isinstance(self._pkg_meta, dict):
            self._pkg_meta.clear()
        return True

    def on_loadUgcButton_clicked(self, widget, force = True):
        self.spawn_ugc_load(force = force)

    def on_ugcRemoveButton_released(self, widget):
        if self.repository is None:
            return
        if self._webserv is None:
            return
        model, myiter = self.ugcView.get_selection().get_selected()
        if myiter is None:
            return
        doc = model.get_value( myiter, 0 )
        if not isinstance(doc, Document):
            return

        document_id = doc.document_id()
        self.show_loading()
        with Privileges():
            try:
                # requires authentication
                removed = self._webserv.remove_document(document_id)
            except WebService.AuthenticationRequired:
                gobject.idle_add(self._ugc_login)
                removed = False
            except WebService.WebServiceException:
                removed = False
            finally:
                self.hide_loading()

        if removed:
            self.ugc_data = None
            self.spawn_ugc_load(force = True)
            SulfurSignals.emit('ugc_cache_clear')
            self.refresh_ugc_view()

    def on_ugc_doubleclick(self, widget, path, view):
        self.on_ugcShowButton_clicked(widget)

    def on_ugcShowButton_clicked(self, widget):
        if self.repository is None:
            return
        if self._webserv is None:
            return
        model, myiter = self.ugcView.get_selection().get_selected()
        if myiter is None:
            return
        obj = model.get_value( myiter, 0 )
        if not isinstance(obj, Document):
            return
        my = UGCInfoMenu(self.Entropy, obj, self.pkgkey, self.repository,
            self.pkginfo_ui.pkgInfo)
        my.load()

    def on_ugcAddButton_clicked(self, widget):
        if self.repository is None:
            return
        if self.pkgkey is None:
            return
        if self._webserv is None:
            return
        my = UGCAddMenu(self.Entropy, self.pkgkey, self.repository,
            self.pkginfo_ui.pkgInfo, self.refresh_view_cb)
        my.load()

    def refresh_view_cb(self):
        self.spawn_ugc_load(force = True)
        SulfurSignals.emit('ugc_cache_clear')

    def show_loading(self):
        self.pkginfo_ui.ugcButtonBox.hide()
        self.pkginfo_ui.loadUgcButton.set_sensitive(False)
        self.pkginfo_ui.scrolledView.hide()
        self.pkginfo_ui.ugcView.hide()
        self.pkginfo_ui.ugcLoadingEvent.show_all()
        self.pkginfo_ui.ugcLoadingEvent.add(self.loading_pix)
        self.pkginfo_ui.ugcLoadingEvent.show_all()
        self.pkginfo_ui.pkgInfo.queue_draw()

    def hide_loading(self):
        self.pkginfo_ui.ugcLoadingEvent.remove(self.loading_pix)
        self.pkginfo_ui.scrolledView.show()
        self.pkginfo_ui.ugcView.show()
        self.pkginfo_ui.ugcLoadingEvent.hide()
        self.pkginfo_ui.loadUgcButton.set_sensitive(True)
        self.pkginfo_ui.ugcButtonBox.show_all()

    def __get_docs_loop(self, force):
        docs = []
        docs_offset = 0
        with Privileges():
            while True:
                try:
                    docs_list = self._webserv.get_documents([self.pkgkey],
                        cache = not force, cached = not force,
                        offset = docs_offset)[self.pkgkey]
                except WebService.CacheMiss:
                    return None
                except WebService.WebServiceException:
                    return None
                if docs_list is None:
                    # wtf!
                    return None
                docs.extend(docs_list)
                if not docs_list.has_more():
                    break
                docs_offset += len(docs_list)
        return docs

    def ugc_metadata_fetch(self, force = False):
        if self._webserv is None:
            return []

        docs = None
        if not force:
            docs = self.__get_docs_loop(False)
        if docs is None:
            docs = self.__get_docs_loop(True)
        return docs

    def spawn_ugc_load(self, force = False):

        if (self.ugc_data != None) and (not force):
            return
        if not (self.pkgkey and self.repository):
            return

        self.show_loading()
        try:
            docs = self.ugc_metadata_fetch(force = force)
            if docs is None:
                self.ugc_data = None
            else:
                doc_map = {}
                for doc in docs:
                    doc_type = doc.document_type()
                    obj = doc_map.setdefault(doc_type, [])
                    obj.append(doc)
                self.ugc_data = doc_map

            self.refresh_ugc_view()
            th = ParallelTask(self.setup_ugc_icon)
            th.start()
        finally:
            self.hide_loading()

    def refresh_ugc_view(self):
        self.ugcModel.clear()
        if self.ugc_data is None:
            return
        self.populate_ugc_view()

    def prefetch_ugc_icon(self):
        def do_ugc_fetch():
            self.ugc_metadata_fetch()
            self.setup_ugc_icon()
        th = ParallelTask(do_ugc_fetch)
        th.start()

    def setup_ugc_icon(self):
        """
        Setup UGC icon for package if UGC data has been already downloaded
        and prepared by this class.
        """
        if not (self.pkgkey and self.repository):
            return

        webserv = self._webserv
        const_debug_write(__name__,
            "setup_ugc_icon, WebService available: %s" % (webserv,))

        # sorry web service, we need data this way
        with Privileges():
            try:
                icon_docs = webserv.get_icons([self.pkgkey],
                    cache = True, cached = True)[self.pkgkey]
            except WebService.CacheMiss:
                icon_docs = None

        if icon_docs is None:
            # not in cache
            return

        const_debug_write(__name__,
            "setup_ugc_icon, UGC metadata available in cache for (%s, %s): %s" % (
                self.pkgkey, self.repository, icon_docs,))

        # get the first available in cache
        store_path = None
        store_doc = None
        for icon_doc in icon_docs:
            local_path = icon_doc.local_document()
            if local_path is None:
                continue
            store_path = local_path
            store_doc = icon_doc
            # found a good one
            break

        const_debug_write(__name__,
            "setup_ugc_icon, UGC store path for (%s, %s): %s" % (
                self.pkgkey, self.repository, store_path,))

        if store_path is None:
            # cannot get any valid store path
            return

        if not (os.path.isfile(store_path) and os.access(store_path, os.R_OK)):
            # fetch from WWW
            with Privileges():
                try:
                    store_path = webserv.get_document_url(store_doc)
                except ClientWebService.DocumentError:
                    store_path = None
            const_debug_write(__name__,
                "setup_ugc_icon, UGC store path fetched for (%s, %s): %s" % (
                    self.pkgkey, self.repository, store_path,))
        else:
            const_debug_write(__name__,
                "setup_ugc_icon, UGC store path "
                    "available in cache for (%s, %s)" % (
                        self.pkgkey, self.repository,))

        if store_path is None:
            # meh!
            return
        if self._ugc_icon_store_path == store_path:
            # meh! 2
            return

        self._ugc_icon_store_path = store_path
        # if image has __icon__ as title, use as real icon
        icon_path = store_path + ".sulfur_icon"
        if not (os.path.isfile(icon_path) and os.access(icon_path, os.R_OK)):
            try:
                resize_image(48.0, store_path, icon_path)
            except (ValueError, OSError,):
                # image should be a GdkPixbuf or empty
                return # wtf!
        gobject.idle_add(self.pkginfo_ui.pkgImage.set_from_file, icon_path)

    def spawn_docs_fetch(self):

        if self.ugc_data is None:
            return
        if self.repository is None:
            return
        if self._webserv is None:
            return

        try:
            docs_map = self.ugc_data.copy()
        except AttributeError:
            # must be concurrency-free
            return

        for doc_type, docs in docs_map.items():

            if doc_type not in (Document.IMAGE_TYPE_ID, Document.ICON_TYPE_ID):
                continue

            for mydoc in docs:
                with Privileges():
                    try:
                        store_path = self._webserv.get_document_url(mydoc)
                    except ClientWebService.DocumentError:
                        store_path = None

                if store_path is None:
                    continue
                if not (os.path.isfile(store_path) and \
                    os.access(store_path, os.R_OK)):
                    continue

                preview_path = store_path+".sulfur_preview_height"
                try:
                    resize_image_height(self._ugc_row_height - 4, store_path,
                        preview_path)
                except (ValueError, OSError,):
                    continue
                mydoc['preview_path'] = preview_path

    def populate_ugc_view(self):

        if self.ugc_data is None:
            return

        spawn_fetch = False
        doc_types = list(self.ugc_data.keys())
        doc_type_image_map = {
            Document.COMMENT_TYPE_ID: const.ugc_text_pix,
            Document.IMAGE_TYPE_ID: const.ugc_image_pix,
            Document.FILE_TYPE_ID: const.ugc_generic_pix,
            Document.VIDEO_TYPE_ID: const.ugc_video_pix,
            Document.ICON_TYPE_ID: const.ugc_image_pix,
        }
        doc_type_background_map = {
            Document.COMMENT_TYPE_ID: ('#67AB6F', '#599360'),
            Document.IMAGE_TYPE_ID: ('#AB8158', '#CA9968'),
            Document.FILE_TYPE_ID: ('#BBD5B0', '#99AE90'),
            Document.VIDEO_TYPE_ID: ('#A5C0D5', '#8EA5B7'),
            Document.ICON_TYPE_ID: ('#AB8158', '#CA9968'),
        }
        doc_type_foreground_map = {
            Document.COMMENT_TYPE_ID: '#FFFFFF',
            Document.IMAGE_TYPE_ID: '#FFFFFF',
            Document.FILE_TYPE_ID: '#FFFFFF',
            Document.VIDEO_TYPE_ID: '#FFFFFF',
            Document.ICON_TYPE_ID: '#FFFFFF',
        }
        counter = 1
        for doc_type in doc_types:
            spawn_fetch = True
            image_path = doc_type_image_map.get(doc_type)
            cat_dict = {
                'is_cat': True,
                'image_path': image_path,
                'parent_desc': "%s (%s)" % (
                    Document.DESCRIPTION_PLURAL.get(doc_type, _("N/A")),
                    len(self.ugc_data[doc_type]),),
                'foreground': doc_type_foreground_map.get(doc_type),
                'background': doc_type_background_map.get(doc_type),
            }
            parent = self.ugcModel.append( None, (cat_dict,) )
            docs_dates = {}
            for mydoc in self.ugc_data[doc_type]:
                ts = mydoc['ts']
                lst = docs_dates.setdefault(ts, [])
                lst.append(mydoc)

            sorted_dates = sorted(docs_dates.keys())
            for ts in sorted_dates:
                for mydoc in docs_dates[ts]:
                    mydoc['image_path'] = const.ugc_pixmap_small
                    mydoc['foreground'] = doc_type_foreground_map.get(doc_type)
                    mydoc['background'] = doc_type_background_map.get(doc_type)
                    mydoc['counter'] = counter
                    self.ugcModel.append( parent, (mydoc,) )
                    counter += 1

        if spawn_fetch:
            th = ParallelTask(self.spawn_docs_fetch)
            th.start()

        self.ugcView.set_property('headers-visible', True)
        self.ugcView.set_property('enable-search', True)
        self.ugcView.show_all()

    def on_infoBook_switch_page(self, widget, page, page_num):
        page_name = self._page_tabs_map.get(page_num)
        if page_num is None:
            return

        page_data = self._page_tabs_data.get(page_name)
        if page_data is None:
            return # main page?

        if (not page_data['loaded']) and (page_data['loader'] is not None):
            def loader_func():
                page_data['loaded'] = page_data['loader']()
            gobject.idle_add(loader_func)

    def _ugc_page_loader(self):
        SulfurSignals.emit('pkg_properties__ugc_tab_clicked')
        return True

    def _other_page_loader(self):

        # content view
        self.contentModel.clear()
        self.contentView.set_model(self.contentModel)
        self.contentModel.append(None, [_("Please wait..."), ""])
        def _load_cont():
            self.contentModel.clear()
            for path, typ in self._pkg_meta.get('content', {}).items():
                self.contentModel.append(None, [path, typ])
        gobject.idle_add(_load_cont)

        # trigger
        mtrigger = gtk.TextBuffer()
        mtrigger.set_text(self._pkg_meta.get('trigger', ""))
        self.pkginfo_ui.triggerTextView.set_buffer(mtrigger)

        # CONFIG_PROTECT Stuff
        if 'config_protect' in self._pkg_meta:
            for item in self._pkg_meta['config_protect'].split():
                self.configProtectModel.append(None, [item, 'protect'])
        if 'config_protect_mask' in self._pkg_meta:
            for item in self._pkg_meta['config_protect_mask'].split():
                self.configProtectModel.append(None, [item, 'mask'])

        return True

    def _dependencies_page_loader(self):
        # dependencies view
        self.dependenciesModel.clear()
        self.dependenciesView.set_model(self.dependenciesModel)
        deps = sorted(self._pkg_meta.get('dependencies', []),
            key = lambda x: entropy.dep.dep_getkey(x))
        conflicts = sorted(self._pkg_meta.get('conflicts', []),
            key = lambda x: entropy.dep.dep_getkey(x))
        for x in conflicts:
            self.dependenciesModel.append(None, [cleanMarkupString("!"+x)])
        for x in deps:
            self.dependenciesModel.append(None, [cleanMarkupString(x)])

        # needed view
        self.neededModel.clear()
        self.neededView.set_model(self.neededModel)
        for x in sorted(self._pkg_meta['needed']):
            self.neededModel.append(None, [cleanMarkupString(x)])

        # depends view
        self.dependsModel.clear()
        self.dependsView.set_model(self.dependsModel)
        self.dependsModel.append(None, [_("Please wait...")])
        def _load_depends():
            depends = self.pkg.dependsFmt
            self.dependsModel.clear()
            for x in depends:
                self.dependsModel.append(None, [cleanMarkupString(x)])
        gobject.idle_add(_load_depends)

        return True

    def _references_page_loader(self):
        # sources view
        self.sourcesModel.clear()
        self.sourcesView.set_model(self.sourcesModel)
        mirrors = set()
        sources = self._pkg_meta.get("sources", [])
        for x in sources:
            if x.startswith("mirror://"):
                mirrors.add(x.split("/")[2])
            self.sourcesModel.append(None, [x])

        # mirrors view
        self.mirrorsReferenceModel.clear()
        self.mirrorsReferenceView.set_model(self.mirrorsReferenceModel)
        for mirror in mirrors:
            mirrorinfo = self.pkg.dbconn.retrieveMirrorData(mirror)
            if mirrorinfo:
                # add parent
                parent = self.mirrorsReferenceModel.append(None, [mirror])
                for info in mirrorinfo:
                    self.mirrorsReferenceModel.append(parent, [info])

        return True

    def _details_page_loader(self):
        if self._pkg_meta is None:
            return True
        # compile flags
        chost, cflags, cxxflags = self._pkg_meta.get('chost', "N/A"), \
            self._pkg_meta.get('cflags', "N/A"), \
            self._pkg_meta.get('cxxflags', "N/A")
        self.pkginfo_ui.cflags.set_markup( "%s" % (cflags,) )
        self.pkginfo_ui.cxxflags.set_markup( "%s" % (cxxflags,) )
        self.pkginfo_ui.chost.set_markup( "%s" % (chost,) )
        # masked ?
        masked = _("No")
        idpackage_masked, idmasking_reason = \
            self.pkg.dbconn.maskFilter(self.pkg.package_id)
        if idpackage_masked == -1:
            masked = '%s, %s' % (_("Yes"),
                self.Entropy.Settings()['pkg_masking_reasons'][idmasking_reason],)
        self.pkginfo_ui.masked.set_markup( "%s" % (masked,) )

        # license view
        self.licenseModel.clear()
        self.licenseView.set_model(self.licenseModel)
        licenses = self._pkg_meta.get('license', "")
        licenses = licenses.split()
        for x in sorted(licenses):
            self.licenseModel.append(None, [x])

        # package changelog
        changelog = self._pkg_meta.get('changelog')
        if not changelog:
            self.pkginfo_ui.showChangeLogButtonAlign.hide()
            self.pkginfo_ui.changeLogLabel.hide()

        # keywords view
        self.keywordsModel.clear()
        self.keywordsView.set_model(self.keywordsModel)
        for x in sorted(self._pkg_meta.get('keywords', []),
            key = lambda x: x.lstrip("~")):
            self.keywordsModel.append(None, [x])

        # useflags view
        self.useflagsModel.clear()
        self.useflagsView.set_model(self.useflagsModel)
        for x in sorted(self._pkg_meta.get('useflags', [])):
            self.useflagsModel.append([cleanMarkupString(x)])

        return True

    def _ugc_tab_clicked(self, event):
        self.on_loadUgcButton_clicked(None, force = False)

    def on_showChangeLogButton_clicked(self, widget):
        changelog = self._pkg_meta.get('changelog')
        if not changelog:
            return
        mybuffer = gtk.TextBuffer()
        mybuffer.set_text(changelog)
        xml_clread = gtk.glade.XML(const.GLADE_FILE, 'textReadWindow',
                                   domain="entropy")
        read_dialog = xml_clread.get_widget( "textReadWindow" )
        okReadButton = xml_clread.get_widget( "okReadButton" )
        self.changelog_read_dialog = read_dialog
        okReadButton.connect('clicked', self.destroy_changelog_read_dialog)
        clView = xml_clread.get_widget("readTextView")
        clView.set_buffer(mybuffer)
        read_dialog.set_title(_("Package ChangeLog"))
        read_dialog.set_transient_for(self.pkginfo_ui.pkgInfo)
        read_dialog.show()

    def destroy_changelog_read_dialog(self, widget):
        self.changelog_read_dialog.destroy()

    def on_star5_enter_notify_event(self, widget, event):
        self.star_enter(widget, event, 5)

    def on_star4_enter_notify_event(self, widget, event):
        self.star_enter(widget, event, 4)

    def on_star3_enter_notify_event(self, widget, event):
        self.star_enter(widget, event, 3)

    def on_star2_enter_notify_event(self, widget, event):
        self.star_enter(widget, event, 2)

    def on_star1_enter_notify_event(self, widget, event):
        self.star_enter(widget, event, 1)

    def on_starsEvent_leave_notify_event(self, widget, event):
        normal_cursor(self.pkginfo_ui.pkgInfo)
        self.set_stars(self.vote)

    def on_starsEvent_enter_notify_event(self, widget, event):
        busy_cursor(self.pkginfo_ui.pkgInfo, cur = gtk.gdk.Cursor(gtk.gdk.CROSSHAIR))

    def on_starEvent5_button_release_event(self, widget, event):
        self.vote_click(5)

    def on_starEvent4_button_release_event(self, widget, event):
        self.vote_click(4)

    def on_starEvent3_button_release_event(self, widget, event):
        self.vote_click(3)

    def on_starEvent2_button_release_event(self, widget, event):
        self.vote_click(2)

    def on_starEvent1_button_release_event(self, widget, event):
        self.vote_click(1)

    def _ugc_login(self):
        if self.repository is None:
            return False
        if self._webserv is None:
            return False

        def fake_callback(*args, **kwargs):
            return True

        # use input box to read login
        input_params = [
            ('username', _('Username'), fake_callback, False),
            ('password', _('Password'), fake_callback, True)
        ]
        login_data = self.Entropy.input_box(
            "%s %s %s" % (
                _('Please login against'), self.repository, _('repository'),),
            input_params,
            cancel_button = True
        )
        if not login_data:
            return False

        username, password = login_data['username'], login_data['password']
        with Privileges():
            self._webserv.add_credentials(username, password)
            try:
                self._webserv.validate_credentials()
            except WebService.AuthenticationFailed:
                self._webserv.remove_credentials()
                okDialog(self.window,
                    _("Authentication error. Not logged in."))
                return False
            except WebService.RequestError:
                okDialog(self.window,
                    _("Communication error. Not logged in."))
                return False

        okDialog(self.window,
            _("Successfully logged in."))
        return True

    def vote_click(self, vote):
        if not (self.repository and self.pkgkey):
            return

        def _do_vote():
            if self._webserv is None:
                return
            with Privileges():
                try:
                    voted = self._webserv.add_vote(self.pkgkey, vote)
                except WebService.AuthenticationRequired:
                    def _do_login():
                        logged_in = self._ugc_login()
                        if logged_in:
                            # call myself again
                            gobject.idle_add(self.vote_click, vote)
                        return False
                    gobject.idle_add(_do_login)
                    return

            if voted:
                # inform user first
                msg = "<small><span foreground='%s'>%s</span>: %s</small>" % (
                    SulfurConf.color_good,
                        _("Vote registered successfully"), vote,)
            else:
                msg = "<small><span foreground='%s'>%s</span>: %s</small>" % (
                    SulfurConf.color_error, _("Error"), _("Already voted"),)
            gobject.idle_add(self.pkginfo_ui.ugcMessageBox.set_markup, msg)
            if voted:
                with Privileges():
                    # need to refill local cache
                    done = True
                    try:
                        self._webserv.get_votes([self.pkgkey], cache = False)
                    except WebService.WebServiceException as err:
                        # ouch! drop everything completely
                        self._webserv._drop_cached("get_votes")
                        done = False

                    if done:
                        gobject.idle_add(self.set_stars_from_repository)

        th = ParallelTask(_do_vote)
        th.start()


    def star_enter(self, widget, event, number):
        self.set_stars(number, hover = True)

    def setupPkgPropertiesView(self):

        # license view
        self.licenseView = self.pkginfo_ui.licenseView
        self.licenseModel = gtk.TreeStore( gobject.TYPE_STRING )
        cell = gtk.CellRendererText()
        column = gtk.TreeViewColumn( _( "License name" ), cell, markup = 0 )
        self.licenseView.append_column( column )
        self.licenseView.set_model( self.licenseModel )

        # sources view
        self.sourcesView = self.pkginfo_ui.sourcesView
        self.sourcesModel = gtk.TreeStore( gobject.TYPE_STRING )
        cell = gtk.CellRendererText()
        column = gtk.TreeViewColumn( _( "Sources" ), cell, markup = 0 )
        self.sourcesView.append_column( column )
        self.sourcesView.set_model( self.sourcesModel )

        # mirrors view
        self.mirrorsReferenceView = self.pkginfo_ui.mirrorsReferenceView
        self.mirrorsReferenceModel = gtk.TreeStore( gobject.TYPE_STRING )
        cell = gtk.CellRendererText()
        column = gtk.TreeViewColumn( _( "Mirrors" ), cell, markup = 0 )
        self.mirrorsReferenceView.append_column( column )
        self.mirrorsReferenceView.set_model( self.mirrorsReferenceModel )

        # keywords view
        self.keywordsView = self.pkginfo_ui.keywordsView
        self.keywordsModel = gtk.TreeStore( gobject.TYPE_STRING )
        cell = gtk.CellRendererText()
        column = gtk.TreeViewColumn( _( "Keywords" ), cell, markup = 0 )
        self.keywordsView.append_column( column )
        self.keywordsView.set_model( self.keywordsModel )

        # useflags view
        self.useflagsView = self.pkginfo_ui.useflagsView
        self.useflagsModel = gtk.ListStore( gobject.TYPE_STRING )
        cell = gtk.CellRendererText()
        column = gtk.TreeViewColumn( _( "USE flags" ), cell, markup = 0 )
        self.useflagsView.append_column( column )
        self.useflagsView.set_model( self.useflagsModel )

        # dependencies view
        self.dependenciesView = self.pkginfo_ui.dependenciesView
        self.dependenciesModel = gtk.TreeStore( gobject.TYPE_STRING )
        cell = gtk.CellRendererText()
        column = gtk.TreeViewColumn( _( "Dependencies" ), cell, markup = 0 )
        self.dependenciesView.append_column( column )
        self.dependenciesView.set_model( self.dependenciesModel )

        # depends view
        self.dependsView = self.pkginfo_ui.dependsView
        self.dependsModel = gtk.TreeStore( gobject.TYPE_STRING )
        cell = gtk.CellRendererText()
        column = gtk.TreeViewColumn( _( "Depends" ), cell, markup = 0 )
        self.dependsView.append_column( column )
        self.dependsView.set_model( self.dependsModel )

        # needed view
        self.neededView = self.pkginfo_ui.neededView
        self.neededModel = gtk.TreeStore( gobject.TYPE_STRING )
        cell = gtk.CellRendererText()
        column = gtk.TreeViewColumn( _( "Needed libraries" ), cell, markup = 0 )
        self.neededView.append_column( column )
        self.neededView.set_model( self.neededModel )

        # protect view
        self.configProtectView = self.pkginfo_ui.configProtectView1
        self.configProtectModel = gtk.TreeStore( gobject.TYPE_STRING, gobject.TYPE_STRING )
        cell = gtk.CellRendererText()
        column = gtk.TreeViewColumn( _( "Protected item" ), cell, markup = 0 )
        self.configProtectView.append_column( column )
        cell = gtk.CellRendererText()
        column = gtk.TreeViewColumn( _( "Type" ), cell, markup = 1 )
        self.configProtectView.append_column( column )
        self.configProtectView.set_model( self.configProtectModel )

        # content view
        self.contentView = self.pkginfo_ui.contentView
        self.contentModel = gtk.TreeStore( gobject.TYPE_STRING, gobject.TYPE_STRING )
        cell = gtk.CellRendererText()
        column = gtk.TreeViewColumn( _( "File" ), cell, markup = 0 )
        column.set_resizable( True )
        self.contentView.append_column( column )
        cell = gtk.CellRendererText()
        column = gtk.TreeViewColumn( _( "Type" ), cell, markup = 1 )
        column.set_resizable( True )
        self.contentView.append_column( column )
        self.contentView.set_model( self.contentModel )

        # ugc view
        self.ugcView = self.pkginfo_ui.ugcView
        self.ugcModel = gtk.TreeStore( gobject.TYPE_PYOBJECT )

        # Setup image column
        cell = gtk.CellRendererPixbuf()
        cell.set_property('height', self._ugc_row_height)
        column = gtk.TreeViewColumn( _("Type"), cell ) # Document Type
        column.set_cell_data_func( cell, self.ugc_pixbuf )
        column.set_sizing( gtk.TREE_VIEW_COLUMN_FIXED )
        column.set_fixed_width( 120 )
        column.set_sort_column_id( -1 )
        self.ugcView.append_column( column )

        cell = gtk.CellRendererText()
        cell.set_property('wrap-mode', gtk.WRAP_WORD)
        cell.set_property('wrap-width', 340)
        column = gtk.TreeViewColumn(_( "Content" ), cell)
        column.set_resizable(True)
        column.set_cell_data_func(cell, self.ugc_content)
        column.set_sizing(gtk.TREE_VIEW_COLUMN_FIXED)
        column.set_fixed_width(350)
        column.set_expand(True)
        column.set_sort_column_id(-1)
        self.ugcView.append_column(column)
        self.ugcView.set_model(self.ugcModel)

        self.ugcView.set_property('headers-visible', True)
        self.ugcView.set_property('enable-search', True)

    def __update_ugc_event(self, event):
        self.set_stars_from_repository()
        self.set_download_numbers_from_repository()

    def set_stars(self, count, hover = False):
        pix_path = self.star_normal_pixmap
        if hover: pix_path = self.star_selected_pixmap
        pix_path_empty = self.star_empty_pixmap

        widgets = [
        self.pkginfo_ui.vote1,
        self.pkginfo_ui.vote2,
        self.pkginfo_ui.vote3,
        self.pkginfo_ui.vote4,
        self.pkginfo_ui.vote5
        ]
        if count > len(widgets):
            count = len(widgets)
        if count < 0: count = 0
        idx = -1
        while count > -1:
            w = widgets[count-1]
            w.set_from_file(pix_path)
            w.show()
            count -= 1
            idx += 1
        mycount = len(widgets) - idx
        while mycount:
            w = widgets[idx]
            w.set_from_file(pix_path_empty)
            w.show()
            mycount -= 1
            idx += 1

    def set_stars_from_repository(self):
        vote = self.pkg.voteint
        self.set_stars(vote)
        self.vote = vote

    def set_download_numbers_from_repository(self):
        self.pkginfo_ui.ugcDownloaded.set_markup(
            "<small>%s: <b>%s</b></small>" % (_("Number of downloads"),
                self.pkg.downloads,)
        )

    def load(self, remote = False):

        pkg = self.pkg
        dbconn = pkg.dbconn
        avail = False
        if dbconn:
            avail = dbconn.isPackageIdAvailable(pkg.package_id)
        if not avail:
            return

        from_repo = True
        repo = pkg.repository_id
        if isinstance(repo, int):
            from_repo = False
        if from_repo and (repo not in self.Entropy.repositories()) \
            and (not remote):
            return

        self._pkg_meta = pkg.pkgmeta

        # set package image
        pkgatom = self._pkg_meta['atom']
        self.vote = int(pkg.votefloat)
        self.repository = pkg.repoid
        self.pkgkey = entropy.dep.dep_getkey(pkgatom)
        self.set_stars_from_repository()
        self.pkginfo_ui.pkgImage.set_from_file(self.pkg_pixmap)
        self.pkginfo_ui.ugcSmallIcon.set_from_file(self.ugc_small_pixmap)

        self.pkginfo_ui.labelAtom.set_markup("<b>%s</b>" % (
            cleanMarkupString(pkgatom),))
        self.pkginfo_ui.labelDescription.set_markup("<small>%s</small>" % (
            cleanMarkupString(self._pkg_meta['description']),))
        self.set_download_numbers_from_repository()

        bold_items = [  self.pkginfo_ui.locationLabel,
                        self.pkginfo_ui.homepageLabel,
                        self.pkginfo_ui.versionLabel,
                        self.pkginfo_ui.slotLabel,
                        self.pkginfo_ui.tagLabel,
                        self.pkginfo_ui.revisionLabel,
                        self.pkginfo_ui.branchLabel,
                        self.pkginfo_ui.eapiLabel,
                        self.pkginfo_ui.downloadLabel,
                        self.pkginfo_ui.checksumLabel,
                        self.pkginfo_ui.downSizeLabel,
                        self.pkginfo_ui.installSizeLabel,
                        self.pkginfo_ui.creationDateLabel,
                        self.pkginfo_ui.chostLabel,
                        self.pkginfo_ui.cflagsLabel,
                        self.pkginfo_ui.cxxflagsLabel,
                        self.pkginfo_ui.maskedLabel,
                        self.pkginfo_ui.triggerLabel,
                        self.pkginfo_ui.configProtectLabel,
                        self.pkginfo_ui.changeLogLabel
        ]
        for item in bold_items:
            t = item.get_text()
            item.set_markup("<b>%s</b>" % (t,))

        avail_repos = self.Entropy.Settings()['repositories']['available']
        if repo == 0:
            repo = pkg.repoid

        if remote:
            self.pkginfo_ui.location.set_markup(
                "%s: %s" % (_("Remotely"), repo,))
        elif repo in avail_repos:
            self.pkginfo_ui.location.set_markup(
                "%s" % (cleanMarkupString(avail_repos[repo]['description']),))
        else:
            self.pkginfo_ui.location.set_markup(
                "%s: %s" % (_("Removed repository"), repo,))

        self.pkginfo_ui.version.set_markup( "%s" % (
            cleanMarkupString(self._pkg_meta['version']),))
        tag = self._pkg_meta['versiontag']
        if not tag:
            tag = "None"
        self.pkginfo_ui.tag.set_markup( "%s" % (tag,) )
        self.pkginfo_ui.slot.set_markup( "%s" % (self._pkg_meta['slot'],) )
        self.pkginfo_ui.revision.set_markup( "%s" % (self._pkg_meta['revision'],) )
        self.pkginfo_ui.branch.set_markup( "%s" % (self._pkg_meta['branch'],) )
        self.pkginfo_ui.eapi.set_markup( "%s" % (pkg.api,) )
        self.pkginfo_ui.homepage.set_markup( "%s" % (
            cleanMarkupString(self._pkg_meta['homepage']),) )

        self.pkginfo_ui.download.set_markup( "%s" % (self._pkg_meta['download'],))
        self.pkginfo_ui.checksum.set_markup( "%s" % (self._pkg_meta['digest'],))
        size = entropy.tools.bytes_into_human(self._pkg_meta['size'])
        self.pkginfo_ui.pkgsize.set_markup( "%s" % (size,))
        disk_size = entropy.tools.bytes_into_human(self._pkg_meta['disksize'])
        self.pkginfo_ui.instsize.set_markup( "%s" % (disk_size,))
        cr_date = entropy.tools.convert_unix_time_to_human_time(
            float(self._pkg_meta['datecreation']))
        self.pkginfo_ui.creationdate.set_markup( "%s" % (cr_date,))

        # connect events
        self.ugc_update_event_handler_id = \
            SulfurSignals.connect('ugc_data_update', self.__update_ugc_event)

        # Prefetch UGC icon by spawning a parallel process
        # Cannot afford to fail here
        try:
            self.prefetch_ugc_icon()
        except:
            pass

        self.pkginfo_ui.pkgInfo.show()


class UGCInfoMenu(MenuSkel):

    def __init__(self, Entropy, obj, package_name, repository, window):

        self.package_name = package_name
        self.repository = repository
        self.window = window
        self.Entropy = Entropy
        self.ugc_doc = obj
        self.ugcinfo_ui = UI( const.GLADE_FILE, 'ugcInfo', 'entropy' )
        self.ugcinfo_ui.signal_autoconnect(self._getAllMethods())
        self.ugcinfo_ui.ugcInfo.set_transient_for(self.window)
        self.ugcinfo_ui.ugcInfo.add_events(gtk.gdk.BUTTON_PRESS_MASK)

    def on_closeInfo_clicked(self, widget, path = None):
        self.ugcinfo_ui.ugcInfo.hide()
        return True

    def on_getButton_clicked(self, widget):
        url = self.ugc_doc.document_url()
        if url is not None:
            load_url(url)

    def load(self):

        pix_path = self.ugc_doc['image_path']
        if self.ugc_doc.get('preview_path') is not None:
            if os.path.isfile(self.ugc_doc['preview_path']) and \
                os.access(self.ugc_doc['preview_path'], os.R_OK):
                pix_path = self.ugc_doc['preview_path']

        self.ugcinfo_ui.ugcImage.set_from_file(pix_path)
        self.ugcinfo_ui.labelKey.set_markup("<b>%s</b>" % (
            self.package_name,))
        doc_type = self.ugc_doc.document_type()
        doc_id = self.ugc_doc.document_id()

        doc_type_desc = Document.DESCRIPTION_SINGULAR.get(doc_type, _("N/A"))
        self.ugcinfo_ui.labelTypedesc.set_markup(
            "<small>[<b>%s</b>:%d] <i>%s</i></small>" % (
                _("Id"),
                doc_id,
                doc_type_desc,
            )
        )
        title = self.ugc_doc.get(Document.DOCUMENT_TITLE_ID, _("N/A"))
        description = self.ugc_doc.get(Document.DOCUMENT_DESCRIPTION_ID,
            _("N/A"))
        username = self.ugc_doc.get(DocumentFactory.DOCUMENT_USERNAME_ID,
            _("N/A"))
        keywords = self.ugc_doc.document_keywords().strip().split()
        ts = self.ugc_doc.document_timestamp()
        ts = entropy.tools.convert_unix_time_to_human_time(ts)

        self.ugcinfo_ui.titleContent.set_markup("%s" % (
            cleanMarkupString(const_convert_to_unicode(title)),))
        self.ugcinfo_ui.descriptionContent.set_markup("%s" % (
            cleanMarkupString(const_convert_to_unicode(description)),))
        self.ugcinfo_ui.authorContent.set_markup("<i>%s</i>" % (
            cleanMarkupString(const_convert_to_unicode(username)),))
        self.ugcinfo_ui.dateContent.set_markup(
            "<u>%s</u>" % (cleanMarkupString(ts),))
        if keywords:
            keywords_str = ", ".join(keywords)
            self.ugcinfo_ui.keywordsContent.set_markup("%s" % (
                cleanMarkupString(const_convert_to_unicode(keywords_str)),))
        else:
            self.ugcinfo_ui.keywordsContent.set_markup(_("No keywords"))

        bold_items = [
            self.ugcinfo_ui.titleLabel,
            self.ugcinfo_ui.descLabel,
            self.ugcinfo_ui.authorLabel,
            self.ugcinfo_ui.dateLabel,
            self.ugcinfo_ui.keywordsLabel
        ]
        for item in bold_items:
            t = item.get_text()
            item.set_markup("<b>%s</b>" % (t,))

        small_items = bold_items
        small_items += [
            self.ugcinfo_ui.titleContent,
            self.ugcinfo_ui.descriptionContent,
            self.ugcinfo_ui.authorContent,
            self.ugcinfo_ui.dateContent,
            self.ugcinfo_ui.keywordsContent
        ]
        for item in small_items:
            t = item.get_label()
            item.set_markup("<small>%s</small>" % (t,))

        if self.ugc_doc.is_comment():
            self.ugcinfo_ui.ugcTable.remove(self.ugcinfo_ui.descLabel)
            self.ugcinfo_ui.ugcTable.remove(self.ugcinfo_ui.descriptionContent)
            self.ugcinfo_ui.buttonBox.hide()
            mybuf = gtk.TextBuffer()
            ###
            # we need to properly handle raw data coming from ddata dict key
            ###
            comment = self.ugc_doc.document_data()
            comment = const_convert_to_unicode(comment)
            mybuf.set_text(comment)
            self.ugcinfo_ui.textContent.set_buffer(mybuf)
        else:
            self.ugcinfo_ui.textFrame.hide()

        self.ugcinfo_ui.ugcInfo.show()


class UGCAddMenu(MenuSkel):

    def __init__(self, Entropy, pkgkey, repository, window, refresh_cb):

        self.loading_pix = gtk.image_new_from_file(const.loading_pix)
        self.repository = repository
        self.pix_path = const.ugc_pixmap
        self.pkgkey = pkgkey
        self.window = window
        self.Entropy = Entropy
        self.ugcadd_ui = UI( const.GLADE_FILE, 'ugcAdd', 'entropy' )
        self.ugcadd_ui.signal_autoconnect(self._getAllMethods())
        self.ugcadd_ui.ugcAdd.set_transient_for(self.window)
        self.ugcadd_ui.ugcAdd.set_position(gtk.WIN_POS_CENTER_ON_PARENT)
        self.ugcadd_ui.ugcAdd.move(*self.window.get_position())
        self.ugcadd_ui.ugcAdd.add_events(gtk.gdk.BUTTON_PRESS_MASK)
        self.store = None
        self.refresh_cb = refresh_cb
        self.text_types = [Document.COMMENT_TYPE_ID]
        self.file_selected = None
        self._combo_doc_types = []

    def on_closeAdd_clicked(self, widget, path = None):
        self.ugcadd_ui.ugcAdd.hide()
        return True

    def on_ugcAddTypeCombo_changed(self, widget):
        myiter = widget.get_active_iter()
        idx = self.store.get_value( myiter, 0 )
        if idx in self.text_types:
            desc = Document.DESCRIPTION_SINGULAR[idx]
            txt = "%s %s" % (_("Write your"), desc,)
            self.setup_text_insert(txt)
        else:
            desc = Document.DESCRIPTION_SINGULAR[idx]
            txt = "%s %s" % (_("Select your"), desc,)
            self.setup_file_insert(txt)

    def on_ugcAddFileChooser_file_set(self, widget):
        self.file_selected = widget.get_filename()

    def _ugc_login(self, webserv):

        def fake_callback(*args, **kwargs):
            return True

        # use input box to read login
        input_params = [
            ('username', _('Username'), fake_callback, False),
            ('password', _('Password'), fake_callback, True)
        ]
        login_data = self.Entropy.input_box(
            "%s %s %s" % (
                _('Please login against'), self.repository, _('repository'),),
            input_params,
            cancel_button = True
        )
        if not login_data:
            return False

        username, password = login_data['username'], login_data['password']
        with Privileges():
            webserv.add_credentials(username, password)
            try:
                webserv.validate_credentials()
            except WebService.AuthenticationFailed:
                webserv.remove_credentials()
                okDialog(self.window,
                    _("Authentication error. Not logged in."))
                return False
            except WebService.RequestError:
                okDialog(self.window,
                    _("Communication error. Not logged in."))
                return False

        return True

    def on_submitButton_clicked(self, widget):

        dialog_title = _("Submit issue")
        myiter = self.ugcadd_ui.ugcAddTypeCombo.get_active_iter()
        doc_type = self.store.get_value( myiter, 0 )
        title = self.ugcadd_ui.ugcAddTitleEntry.get_text()
        description = self.ugcadd_ui.ugcAddDescEntry.get_text()
        keywords_text = self.ugcadd_ui.ugcAddKeywordsEntry.get_text()
        doc_path = None
        if doc_type in self.text_types:
            mybuf = self.ugcadd_ui.ugcAddTextView.get_buffer()
            start_iter = mybuf.get_start_iter()
            end_iter = mybuf.get_end_iter()
            description = mybuf.get_text(start_iter, end_iter)
            if not description:
                okDialog(self.window, _("Empty Document"),
                    title = dialog_title)
                return False
        else:
            if not description:
                okDialog(self.window, _("Invalid Description"),
                    title = dialog_title)
                return False
            doc_path = self.file_selected

        # checking
        if doc_type is None:
            okDialog(self.window, _("Invalid Document Type"),
                title = dialog_title)
            return False
        if not title:
            okDialog(self.window, _("Invalid Title"),
                title = dialog_title)
            return False

        # confirm ?
        rc = self.Entropy.ask_question(_("Do you confirm your submission?"))
        if rc != _("Yes"):
            return False

        self.show_loading()

        try:
            webserv = get_entropy_webservice(self.Entropy, self.repository)
        except WebService.UnsupportedService as err:
            okDialog(self.window, _("Unsupported Service"),
                title = dialog_title)
            return False

        try:
            available = webserv.service_available()
        except WebService.WebServiceException:
            okDialog(self.window, _("Service is unavailable"),
                title = dialog_title)
            return False
        if not available:
            okDialog(self.window, _("Service is unavailable"),
                title = dialog_title)
            return False

        with Privileges():
            # ask user to login
            need_login = False
            if webserv.credentials_available():
                try:
                    webserv.validate_credentials()
                except WebService.AuthenticationFailed:
                    webserv.remove_credentials()
                    need_login = True
                except WebService.RequestError:
                    # SSL Error?
                    need_login = True
            else:
                need_login = True

        if need_login:
            logged_in = self._ugc_login(webserv)
            if not logged_in:
                return False

        # can't be None
        username = webserv.get_credentials()
        webserv._set_transfer_callback(self.do_label_update_progress)

        # Build up the Document object
        doc_factory = DocumentFactory(self.repository)

        doc_f = None
        try:
            if doc_type == Document.COMMENT_TYPE_ID:
                doc = doc_factory.comment(username, description,
                    title, keywords_text)
            elif doc_type == Document.ICON_TYPE_ID:
                doc_f = open(doc_path, "rb")
                doc = doc_factory.icon(username, doc_f, title,
                    description, keywords_text)
            elif doc_type == Document.FILE_TYPE_ID:
                doc_f = open(doc_path, "rb")
                doc = doc_factory.file(username, doc_f, title,
                    description, keywords_text)
            elif doc_type == Document.IMAGE_TYPE_ID:
                doc_f = open(doc_path, "rb")
                doc = doc_factory.image(username, doc_f, title,
                    description, keywords_text)
            elif doc_type == Document.VIDEO_TYPE_ID:
                doc_f = open(doc_path, "rb")
                doc = doc_factory.video(username, doc_f, title,
                    description, keywords_text)
            else:
                # WTF
                raise AssertionError("invalid document type")
        except AssertionError as err:
            okDialog(self.window, "%s: %s" % (_("Invalid fields"), err),
                title = dialog_title)
            if doc_f is not None:
                doc_f.close()
                doc_f = None
            return False

        def _do_add_document(doc, doc_f):
            err_msg = None
            try:
                new_doc = webserv.add_document(self.pkgkey, doc)
            except WebService.WebServiceException as err:
                new_doc = None
                err_msg = str(err)
            finally:
                if doc_f is not None:
                    doc_f.close()
                gobject.idle_add(self.hide_loading)

            if new_doc is not None:
                def _happy_ending():
                    okDialog(self.ugcadd_ui.ugcAdd,
                        _("Document added successfully. Thank you"),
                        title = _("Success!"))
                    self.on_closeAdd_clicked(None, None)
                    self.refresh_cb()
                    return False
                gobject.idle_add(_happy_ending)
            else:
                def _unhappy_ending():
                    txt = "<small><span foreground='%s'><b>%s</b></span>: %s</small>" % (
                        SulfurConf.color_error, _("UGC Error"), err_msg,)
                    self.ugcadd_ui.ugcAddStatusLabel.set_markup(txt)
                    return False
                gobject.idle_add(_unhappy_ending)

        th = ParallelTask(_do_add_document, doc, doc_f)
        th.start()
        return False

    def do_label_update_progress(self, transfered, total, download):

        if download:
            action = _("Downloading")
        else:
            action = _("Uploading")

        percent = 100
        if (total > 0) and (transfered <= total):
            percent = int(round((float(transfered)/total) * 100, 1))

        msg = cleanMarkupString("[%s%s] %s ..." % (percent, "%", action))
        gobject.idle_add(self.ugcadd_ui.ugcAddStatusLabel.set_markup, msg)

    def show_loading(self):
        self.ugcadd_ui.ugcAddButtonBox.hide()
        self.ugcadd_ui.closeAdd.set_sensitive(False)
        self.ugcadd_ui.ugcAddLoadingEvent.show_all()
        self.ugcadd_ui.ugcAddLoadingEvent.add(self.loading_pix)
        self.ugcadd_ui.ugcAddLoadingEvent.show_all()
        self.ugcadd_ui.ugcAdd.queue_draw()

    def hide_loading(self):
        self.ugcadd_ui.ugcAddButtonBox.show()
        self.ugcadd_ui.closeAdd.set_sensitive(True)
        self.ugcadd_ui.ugcAddLoadingEvent.remove(self.loading_pix)
        self.ugcadd_ui.ugcAddLoadingEvent.hide()
        self.ugcadd_ui.ugcAdd.queue_draw()

    def setup_text_insert(self, txt = _("Write your document")):
        self.ugcadd_ui.ugcAddFileChooser.hide()
        self.ugcadd_ui.ugcAddFrame.show()
        self.ugcadd_ui.ugcAddDescLabel.hide()
        self.ugcadd_ui.ugcAddDescEntry.hide()
        self.ugcadd_ui.ugcAddTitleEntry.set_max_length(255)
        self.ugcadd_ui.ugcAddInsertLabel.set_markup(txt)

    def setup_file_insert(self, txt = _("Select your file")):
        self.ugcadd_ui.ugcAddFileChooser.show()
        self.ugcadd_ui.ugcAddFrame.hide()
        self.ugcadd_ui.ugcAddDescLabel.show()
        self.ugcadd_ui.ugcAddDescEntry.show()
        self.ugcadd_ui.ugcAddTitleEntry.set_max_length(60)
        self.ugcadd_ui.ugcAddInsertLabel.set_markup(txt)

    def prepare_image_insert(self, pkg_name, image_path, as_icon = False):
        doc_type = Document.IMAGE_TYPE_ID
        if as_icon:
            doc_type = Document.ICON_TYPE_ID
        self.ugcadd_ui.ugcAddTypeCombo.set_active(
            self._combo_doc_types.index(doc_type))
        self.ugcadd_ui.ugcAddFileChooser.set_filename(image_path)
        self.file_selected = image_path
        if as_icon:
            self.ugcadd_ui.ugcAddTitleEntry.set_text(pkg_name + " icon")
            self.ugcadd_ui.ugcAddDescEntry.set_text("This is the %s icon" % (
                pkg_name,))
        else:
            self.ugcadd_ui.ugcAddTitleEntry.set_text("%s %s" % (
                pkg_name, "image",))
            self.ugcadd_ui.ugcAddDescEntry.set_text("This is the %s image" % (
                pkg_name,))

    def prepare_file_insert(self, pkg_name, file_path):
        self.ugcadd_ui.ugcAddTypeCombo.set_active(
            self._combo_doc_types.index(Document.FILE_TYPE_ID))
        self.ugcadd_ui.ugcAddFileChooser.set_filename(file_path)
        self.file_selected = file_path
        self.ugcadd_ui.ugcAddTitleEntry.set_text("%s document" % (
            pkg_name,))
        self.ugcadd_ui.ugcAddDescEntry.set_text("This is just a %s document" % (
            pkg_name,))

    def load(self):

        self.ugcadd_ui.ugcAddImage.set_from_file(self.pix_path)
        self.ugcadd_ui.labelAddKey.set_markup("<b>%s</b>" % (self.pkgkey,))
        self.ugcadd_ui.labelAddRepo.set_markup("<small>%s: <b>%s</b></small>" % (
            _("On repository"), self.repository,))

        # add types to combo
        self.store = gtk.ListStore(gobject.TYPE_INT, gobject.TYPE_STRING)
        self.ugcadd_ui.ugcAddTypeCombo.set_model(self.store)
        cell = gtk.CellRendererText()
        self.ugcadd_ui.ugcAddTypeCombo.pack_start(cell, True)
        self.ugcadd_ui.ugcAddTypeCombo.add_attribute(cell, 'text', 1)
        del self._combo_doc_types[:]
        for idx in Document.SUPPORTED_TYPES:
            self._combo_doc_types.append(idx)
            self.store.append((idx,  Document.DESCRIPTION_SINGULAR[idx],))
        self.ugcadd_ui.ugcAddTypeCombo.set_active(0)

        # hide file chooser
        self.setup_text_insert()

        bold_items = [
            self.ugcadd_ui.ugcAddTitleLabel,
            self.ugcadd_ui.ugcAddDescLabel,
            self.ugcadd_ui.ugcAddTypeLabel,
            self.ugcadd_ui.ugcAddKeywordsLabel
        ]
        for item in bold_items:
            t = item.get_text()
            item.set_markup("<b>%s</b>" % (t,))

        self.ugcadd_ui.ugcAdd.show()


class MaskedPackagesDialog(MenuSkel):


    def __init__( self, Entropy, etpbase, parent, pkgs, top_text = None, sub_text = None):

        self.pkgs = pkgs
        self.pkgcount = 0
        self.maxcount = len(pkgs)

        self.Entropy = Entropy
        self.etpbase = etpbase
        self.parent = parent
        self.docancel = True
        self.mp_ui = UI( const.GLADE_FILE, 'packageMaskWindow', 'entropy' )
        self.mp_ui.signal_autoconnect(self._getAllMethods())
        self.window = self.mp_ui.packageMaskWindow
        self.mp_ui.packageMaskWindow.set_transient_for(self.parent)
        self.cancelbutton = self.mp_ui.maskDialogCancelButton
        self.okbutton = self.mp_ui.maskDialogOkButton
        self.enableButton = self.mp_ui.maskDialogEnableButton
        self.enableAllButton = self.mp_ui.maskDialogEnableAllButton
        self.propertiesButton = self.mp_ui.maskDialogPropertiesButton
        self.action = self.mp_ui.maskDialogAction
        self.subaction = self.mp_ui.maskDialogSubtext
        self.pkg = self.mp_ui.maskDialogPkg
        self.button_pressed = False
        # backward compat
        self.ok_button_reply = -5
        self.cancel_button_reply = -6
        self.rc = self.cancel_button_reply

        self.okbutton.connect("clicked", self.do_ok)
        self.cancelbutton.connect("clicked", self.do_cancel)
        self.enableButton.connect("clicked", self.enablePackage)
        self.enableAllButton.connect("clicked", self.enableAllPackages)
        self.propertiesButton.connect("clicked", self.openPackageProperties)

        # setup text
        if top_text is None:
            top_text = _("These are the packages that must be enabled to satisfy your request")

        tit = "<b><span foreground='%s' size='large'>%s</span></b>\n" % (SulfurConf.color_title, _("Some packages are masked"),)
        tit += top_text
        self.action.set_markup( tit )
        if sub_text != None:
            self.subaction.set_markup( sub_text )

        # fill
        self.model = self.setup_view( self.pkg )
        self.show_data( self.model, self.pkgs )
        self.pkg.expand_all()

    def get_obj(self):
        model, myiter = self.pkg.get_selection().get_selected()
        if myiter:
            return model.get_value( myiter, 0 )
        return None

    def openPackageProperties(self, widget):
        obj = self.get_obj()
        if not obj:
            return
        mymenu = PkgInfoMenu(self.Entropy, obj, self.window)
        mymenu.load()

    def enablePackage(self, widget, obj = None, do_refresh = True):
        if not obj:
            obj = self.get_obj()
        if not obj: return
        if obj.matched_atom == (0, 0): return
        result = self.Entropy.unmask_package(obj.matched_atom, dry_run = True)
        if result:
            self.etpbase.unmaskingPackages.add(obj.matched_atom)
            self.pkgcount += 1
            if do_refresh:
                self.refresh()
        return result

    def enableAllPackages(self, widget):

        for parent in self.model:
            for child in parent.iterchildren():
                for obj in child:
                    if not obj:
                        continue
                    if obj.dummy_type != None:
                        continue
                    self.enablePackage(None, obj, False)
        self.refresh()

    def refresh(self):
        self.pkg.queue_draw()
        self.pkg.expand_all()

    def do_cancel(self, widget):
        self.button_pressed = True

    def do_ok(self, widget):
        self.rc = self.ok_button_reply
        self.button_pressed = True

    def on_packageMaskWindow_destroy_event(self, *args, **kwargs):
        self.button_pressed = True

    def on_packageMaskWindow_delete_event(self, *args, **kwargs):
        self.button_pressed = True

    def run( self ):

        self.window.show_all()
        self.okbutton.set_sensitive(False)

        while not self.button_pressed:
            time.sleep(0.05)
            while gtk.events_pending():
                gtk.main_iteration()
            continue

        self.window.destroy()

        return self.rc

    def setup_view( self, view ):

        model = gtk.TreeStore( gobject.TYPE_PYOBJECT )
        view.set_model( model )

        cell1 = gtk.CellRendererText()
        column1 = gtk.TreeViewColumn( _( "Masked package" ), cell1 )
        column1.set_cell_data_func( cell1, self.show_pkg )
        column1.set_sizing( gtk.TREE_VIEW_COLUMN_FIXED )
        column1.set_fixed_width( 410 )
        column1.set_resizable( True )
        view.append_column( column1 )

        cell2 = gtk.CellRendererPixbuf()
        column2 = gtk.TreeViewColumn( _("Enabled"), cell2 )
        column2.set_cell_data_func( cell2, self.new_pixbuf )
        column2.set_sizing( gtk.TREE_VIEW_COLUMN_FIXED )
        column2.set_fixed_width( 40 )
        column2.set_sort_column_id( -1 )
        view.append_column( column2 )
        column2.set_clickable( False )

        return model


    def set_pixbuf_to_cell(self, cell, do):
        if do:
            cell.set_property( 'stock-id', 'gtk-apply' )
        elif (not do) and isinstance(do, bool):
            cell.set_property( 'stock-id', 'gtk-cancel' )
        else:
            cell.set_property( 'stock-id', None )

    def new_pixbuf( self, column, cell, model, iterator ):

        if self.pkgcount >= self.maxcount:
            self.okbutton.set_sensitive(True)

        obj = model.get_value( iterator, 0 )
        if obj.matched_atom in self.etpbase.unmaskingPackages:
            self.set_pixbuf_to_cell(cell, True)
        elif obj.dummy_type:
            self.set_pixbuf_to_cell(cell, None)
        else:
            self.set_pixbuf_to_cell(cell, False)
        self.set_line_status(obj, cell, stype = "cell-background")

    def show_pkg( self, column, cell, model, iterator ):
        obj = model.get_value( iterator, 0 )
        mydata = obj.namedesc
        cell.set_property('markup', mydata )
        self.set_line_status(obj, cell)

    def set_line_status(self, obj, cell, stype = "cell-background"):
        if obj.queued == "r":
            cell.set_property(stype, '#FFE2A3')
        elif obj.queued == "u":
            cell.set_property(stype, '#B7BEFF')
        elif obj.queued == "i":
            cell.set_property(stype, '#D895FF')
        elif obj.queued == "rr":
            cell.set_property(stype, '#B7BEFF')
        elif obj.queued == "d":
            cell.set_property(stype, '#A7D0FF')
        elif not obj.queued:
            cell.set_property(stype, None)

    def show_data( self, model, pkgs ):

        model.clear()
        self.pkg.set_model(None)
        self.pkg.set_model(model)

        desc_len = 80
        search_col = 0
        categories = {}

        for po in pkgs:
            mycat = po.cat
            if mycat not in categories:
                categories[mycat] = []
            categories[mycat].append(po)

        from sulfur.package import DummyEntropyPackage

        cats = sorted(categories.keys())
        for category in cats:
            cat_desc = _("No description")
            cat_desc_data = self.Entropy.get_category_description(category)
            if _LOCALE in cat_desc_data:
                cat_desc = cat_desc_data[_LOCALE]
            elif 'en' in cat_desc_data:
                cat_desc = cat_desc_data['en']
            cat_text = "<b><big>%s</big></b>\n<small>%s</small>" % (category, cleanMarkupString(cat_desc),)
            mydummy = DummyEntropyPackage(
                    namedesc = cat_text,
                    dummy_type = SulfurConf.dummy_category,
                    onlyname = category
            )
            mydummy.color = SulfurConf.color_package_category
            parent = model.append( None, (mydummy,) )
            for po in categories[category]:
                model.append( parent, (po,) )

        self.pkg.set_search_column( search_col )
        self.pkg.set_search_equal_func(self.atom_search)
        self.pkg.set_property('headers-visible', True)
        self.pkg.set_property('enable-search', True)

    def atom_search(self, model, column, key, iterator):
        obj = model.get_value( iterator, 0 )
        if obj:
            return not obj.onlyname.startswith(key)
        return True

    def destroy( self ):
        return self.window.destroy()

class TextReadDialog(MenuSkel):


    def __init__(self, title, text, read_only = True, rw_save_path = None):

        self.rw_save_path = rw_save_path
        self.txt_buffer = text
        if not isinstance(text, gtk.TextBuffer):
            self.txt_buffer = gtk.TextBuffer()
            self.txt_buffer.set_text(text)
        if not read_only and (rw_save_path is None):
            raise AttributeError("rw_save_path must be vaild if not read_only")

        xml_read = gtk.glade.XML(const.GLADE_FILE, 'textReadWindow',
            domain="entropy")
        self.__read_dialog = xml_read.get_widget( "textReadWindow" )
        ok_read = xml_read.get_widget( "okReadButton" )
        ok_read.connect( 'clicked', self.ok_button )
        ok_save = xml_read.get_widget("okSaveButton")
        ok_cancel = xml_read.get_widget("okCancelButton")
        self.txt_view = xml_read.get_widget( "readTextView" )
        self.txt_view.set_buffer(self.txt_buffer)
        self.__read_dialog.set_title(title)
        self.__read_dialog.show_all()
        self.done_reading = False

        ok_save.hide()
        ok_cancel.hide()
        if not read_only:
            self.txt_view.set_editable(True)
            self.txt_view.set_cursor_visible(True)
            ok_read.hide()
            ok_save.connect( 'clicked', self.ok_save_button )
            ok_cancel.connect( 'clicked', self.ok_cancel_button )
            ok_save.show()
            ok_cancel.show()

    def get_content(self):
        start = self.txt_buffer.get_start_iter()
        end = self.txt_buffer.get_end_iter()
        return self.txt_buffer.get_text(start, end)

    def ok_save_button(self, widget):
        source_f = open(self.rw_save_path+".etp_tmp", "w")
        cont = self.get_content()
        source_f.write(cont)
        source_f.flush()
        source_f.close()
        os.rename(self.rw_save_path+".etp_tmp", self.rw_save_path)
        self.ok_button(widget)

    def ok_cancel_button(self, widget):
        self.ok_button(widget)

    def ok_button(self, widget):
        self.done_reading = True
        self.__read_dialog.destroy()

    def run( self ):
        """ you don't have to run this if you're looking for non-blocking d. """
        while not self.done_reading:
            time.sleep(0.1)
            while gtk.events_pending():
                gtk.main_iteration()
            continue

class ConfirmationDialog:

    def __init__(self, parent, pkgs, top_text = None, bottom_text = None,
        bottom_data = None, sub_text = None, cancel = True, simpleList = False,
        simpleDict = False):

        self.xml = gtk.glade.XML( const.GLADE_FILE, 'confirmation', domain="entropy" )
        self.dialog = self.xml.get_widget( "confirmation" )
        self.dialog.set_transient_for( parent )
        self.action = self.xml.get_widget( "confAction" )
        self.subaction = self.xml.get_widget( "confSubtext" )
        self.bottomTitle = self.xml.get_widget( "bottomTitle" )
        self.bottomData = self.xml.get_widget( "bottomData" )
        self.cancelbutton = self.xml.get_widget( "cancelbutton2" )
        self.okbutton = self.xml.get_widget( "okbutton2" )
        self.bottomtext = self.xml.get_widget( "bottomTitle" )
        self.lowerhbox = self.xml.get_widget( "hbox63" )

        self.dobottomtext = bottom_text
        self.dobottomdata = bottom_data
        self.docancel = cancel
        self.simpleList = simpleList
        self.simpleDict = simpleDict

        # setup text
        if top_text is None:
            top_text = _("Please confirm the actions above")

        if sub_text is None:
            sub_text = ""

        tit = "<b>%s</b>" % (top_text,)
        self.action.set_markup( tit )
        if bottom_text != None: self.bottomTitle.set_markup( bottom_text )
        if bottom_data != None: self.bottomData.set_text( bottom_data )
        if sub_text != None: self.subaction.set_text( sub_text )

        self.pkgs = pkgs
        self.pkg = self.xml.get_widget( "confPkg" )
        if self.simpleList:
            self.pkgModel = self.setup_simple_view( self.pkg )
            self.show_data_simple( self.pkgModel, pkgs )
        elif self.simpleDict:
            self.pkgModel = self.setup_simple_view( self.pkg )
            self.show_data_simpledict( self.pkgModel, pkgs )
        else:
            self.pkgModel = self.setup_view( self.pkg )
            self.show_data( self.pkgModel, pkgs )
        self.pkg.expand_all()

    def run( self ):
        self.dialog.show_all()
        if not self.docancel:
            self.cancelbutton.hide()
        if not self.dobottomtext:
            self.bottomtext.hide()
        if not self.dobottomdata:
            self.lowerhbox.hide()
        return self.dialog.run()

    def setup_view( self, view ):
        model = gtk.TreeStore( gobject.TYPE_STRING )
        model.set_sort_column_id( 0, gtk.SORT_ASCENDING )
        view.set_model( model )
        self.create_text_column( _( "Package" ), view, 0 )
        return model

    def setup_simple_view(self, view ):
        model = gtk.TreeStore( gobject.TYPE_STRING )
        view.set_model( model )
        self.create_text_column( _( "Item" ), view, 0 )
        return model

    def create_text_column( self, hdr, view, colno, min_width=0, max_width=0 ):
        cell = gtk.CellRendererText()    # Size Column
        column = gtk.TreeViewColumn( hdr, cell, markup=colno )
        column.set_resizable( True )
        if min_width:
            column.set_min_width( min_width )
        if max_width:
            column.set_max_width( max_width )
        view.append_column( column )

    def show_data_simpledict( self, model, pkgs ):
        model.clear()
        if "downgrade" in pkgs:
            if pkgs['downgrade']:
                label = "<b>%s</b>" % _("To be downgraded")
                parent = model.append( None, [label] )
                for pkg in pkgs['downgrade']:
                    model.append( parent, [pkg] )
        if "remove" in pkgs:
            if pkgs['remove']:
                label = "<b>%s</b>" % _("To be removed")
                parent = model.append( None, [label] )
                for pkg in pkgs['remove']:
                    model.append( parent, [pkg] )
        if "reinstall" in pkgs:
            if pkgs['reinstall']:
                label = "<b>%s</b>" % _("To be reinstalled")
                parent = model.append( None, [label] )
                for pkg in pkgs['reinstall']:
                    model.append( parent, [pkg] )
        if "install" in pkgs:
            if pkgs['install']:
                label = "<b>%s</b>" % _("To be installed")
                parent = model.append( None, [label] )
                for pkg in pkgs['install']:
                    model.append( parent, [pkg] )
        if "update" in pkgs:
            if pkgs['update']:
                label = "<b>%s</b>" % _("To be updated")
                parent = model.append( None, [label] )
                for pkg in pkgs['update']:
                    model.append( parent, [pkg] )

    def show_data_simple( self, model, pkgs ):
        model.clear()
        for pkg in pkgs:
            model.append( None, [pkg] )

    def show_data( self, model, pkgs ):
        model.clear()
        desc_len = 80
        install = [x for x in pkgs if x.action == "i"]
        update = [x for x in pkgs if x.action == "u"]
        remove = [x for x in pkgs if x.action == "r"]
        reinstall = [x for x in pkgs if x.action == "rr"]
        downgrade = [x for x in pkgs if x.action == "d"]
        if remove:
            label = "<b>%s</b>" % _("To be removed")
            level1 = model.append( None, [label] )
            for pkg in remove:
                desc = pkg.description[:desc_len].rstrip()+"..."
                desc = cleanMarkupString(desc)
                if not desc.strip():
                    desc = _("No description")
                mydesc = "\n<small><span foreground='%s'>%s</span></small>" % (SulfurConf.color_pkgdesc, desc,)
                mypkg = "<span foreground='%s'>%s</span>" % (SulfurConf.color_remove, str(pkg),)
                model.append( level1, [mypkg+mydesc] )
        if downgrade:
            label = "<b>%s</b>" % _("To be downgraded")
            level1 = model.append( None, [label] )
            for pkg in downgrade:
                desc = pkg.description[:desc_len].rstrip()+"..."
                desc = cleanMarkupString(desc)
                if not desc.strip():
                    desc = _("No description")
                mydesc = "\n<small><span foreground='%s'>%s</span></small>" % (SulfurConf.color_pkgdesc, desc,)
                mypkg = "<span foreground='%s'>%s</span>" % (SulfurConf.color_downgrade, str(pkg),)
                model.append( level1, [mypkg+mydesc] )
        if reinstall:
            label = "<b>%s</b>" % _("To be reinstalled")
            level1 = model.append( None, [label] )
            for pkg in reinstall:
                desc = pkg.description[:desc_len].rstrip()+"..."
                desc = cleanMarkupString(desc)
                if not desc.strip():
                    desc = _("No description")
                mydesc = "\n<small><span foreground='%s'>%s</span></small>" % (SulfurConf.color_pkgdesc, desc,)
                mypkg = "<span foreground='%s'>%s</span>" % (SulfurConf.color_reinstall, str(pkg),)
                model.append( level1, [mypkg+mydesc] )
        if install:
            label = "<b>%s</b>" % _("To be installed")
            level1 = model.append( None, [label] )
            for pkg in install:
                desc = pkg.description[:desc_len].rstrip()+"..."
                desc = cleanMarkupString(desc)
                if not desc.strip():
                    desc = _("No description")
                mydesc = "\n<small><span foreground='%s'>%s</span></small>" % (SulfurConf.color_pkgdesc, desc,)
                mypkg = "<span foreground='%s'>%s</span>" % (SulfurConf.color_install, str(pkg),)
                model.append( level1, [mypkg+mydesc] )
        if update:
            label = "<b>%s</b>" % _("To be updated")
            level1 = model.append( None, [label] )
            for pkg in update:
                desc = pkg.description[:desc_len].rstrip()+"..."
                desc = cleanMarkupString(desc)
                if not desc.strip():
                    desc = _("No description")
                mydesc = "\n<small><span foreground='%s'>%s</span></small>" % (SulfurConf.color_pkgdesc, desc,)
                mypkg = "<span foreground='%s'>%s</span>" % (SulfurConf.color_update, str(pkg),)
                model.append( level1, [mypkg+mydesc] )

    def destroy( self ):
        return self.dialog.destroy()

class ErrorDialog:

    def __init__( self, parent, title, text, longtext, modal ):
        self.xml = gtk.glade.XML( const.GLADE_FILE, "errDialog", domain="entropy" )
        self.dialog = self.xml.get_widget( "errDialog" )
        self.parent = parent
        if parent:
            self.dialog.set_transient_for( parent )
        #self.dialog.set_icon_name( 'gtk-dialog-error' )
        self.dialog.set_title( title )
        self.text = self.xml.get_widget( "errText" )
        self.longtext = self.xml.get_widget( "errTextView" )
        self.nameInput = self.xml.get_widget( "nameEntry" )
        self.mailInput = self.xml.get_widget( "mailEntry" )
        self.reportLabel = self.xml.get_widget( "reportLabel" )
        self.errorButton = self.xml.get_widget( "errorButton" )
        self.actionInput = self.xml.get_widget( "actionEntry" )
        self.reportTable = self.xml.get_widget( "reportTable" )
        self.style_err = gtk.TextTag( "error" )
        self.style_err.set_property( "style", pango.STYLE_ITALIC )
        self.style_err.set_property( "foreground", "#760000" )
        self.style_err.set_property( "family", "Monospace" )
        self.style_err.set_property( "size_points", 8 )
        self.longtext.get_buffer().get_tag_table().add( self.style_err )

        if modal:
            self.dialog.set_modal( True )
        if text != "":
            self.set_text( text )
        if longtext != "" and longtext != None:
            self.set_long_text( longtext )

    def set_text( self, text ):
        self.text.set_markup( text )

    def set_long_text( self, longtext ):
        mybuffer = self.longtext.get_buffer()
        start, end = mybuffer.get_bounds()
        mybuffer.insert_with_tags( end, longtext, self.style_err )

    def run( self, showreport = False ):
        self.dialog.show_all()
        if not showreport:
            self.hide_report_widgets()
        return self.dialog.run()

    def hide_report_widgets(self):
        self.reportTable.hide_all()
        self.errorButton.hide()
        self.reportLabel.hide()

    def get_entries( self ):
        mail = self.mailInput.get_text()
        name = self.nameInput.get_text()
        desc = self.actionInput.get_text()
        return name, mail, desc

    def destroy( self ):
        return self.dialog.destroy()

class infoDialog:
    def __init__( self, parent, title, text ):
        self.xml = gtk.glade.XML( const.GLADE_FILE, "msg", domain="entropy" )
        self.dialog = self.xml.get_widget( "msg" )
        self.parent = parent
        self.dialog.set_transient_for( parent )
        #self.dialog.set_icon_name( 'gtk-dialog-error' )
        self.dialog.set_title( title )
        self.text = self.xml.get_widget( "msgText" )
        self.dialog.set_modal( True )
        self.set_text( text )

    def set_text( self, text ):
        self.text.set_markup( "<span size='large'>%s</span>" % text )

    def run( self ):
        self.dialog.show_all()
        return self.dialog.run()

    def destroy( self ):
        return self.dialog.destroy()


class EntryDialog:
    def __init__( self, parent, title, text ):
        self.xml = gtk.glade.XML( const.GLADE_FILE, "EntryDialog", domain="entropy" )
        self.dialog = self.xml.get_widget( "EntryDialog" )
        self.parent = parent
        #self.dialog.set_transient_for( parent )
        #self.dialog.set_icon_name( 'gtk-dialog-error' )
        self.dialog.set_title( title )
        self.text = self.xml.get_widget( "inputLabel" )
        self.entry = self.xml.get_widget( "inputEntry" )
        self.dialog.set_modal( True )
        self.text.set_text( text )

    def run( self ):
        self.dialog.show_all()
        rc = self.dialog.run()
        if rc == gtk.RESPONSE_OK:
            return self.entry.get_text()
        else:
            return None

    def destroy( self ):
        return self.dialog.destroy()

class AboutDialog(gtk.Window):

    """ Class for a fancy "About" dialog.
        Mostly ripped from the one in gDesklets
    """

    def __init__(self, gfx, creditText, title = "Sulfur Project"):

        self.__is_stopped = True
        self.__scroller_values = ()


        gtk.Window.__init__(self, gtk.WINDOW_TOPLEVEL)
        self.set_type_hint(gtk.gdk.WINDOW_TYPE_HINT_DIALOG)
        self.set_position(gtk.WIN_POS_CENTER)
        self.set_resizable(False)
        self.set_title("%s %s" % (_("About"), title,))
        self.connect("button-press-event", self.__on_close)
        self.connect("key-press-event", self.__on_close)
        self.connect("delete-event", self.__on_close)
        self.add_events(gtk.gdk.BUTTON_PRESS_MASK)
        self.set_decorated(False)

        fixed = gtk.Fixed()
        self.add(fixed)

        img = gtk.Image()
        img.set_from_file(gfx)
        fixed.put(img, 0, 0)

        width, height = img.size_request()

        scroller = gtk.Fixed()
        scroller.set_size_request(width, height - 32)
        fixed.put(scroller, 0, 32)

        text = ""
        for header, body in creditText:
            text += "<b>" + header + "</b>\n\n"
            text += "\n".join(body)
            text += "\n\n\n\n"
        text = "<big>" + text.strip() + "</big>"

        mycredits = gtk.Label("<span foreground='#FFFFFF'>%s</span>" % (text,))
        mycredits.set_use_markup(True)
        mycredits.set_justify(gtk.JUSTIFY_CENTER)

        lbl_width, lbl_height = mycredits.size_request()
        scroller.put(mycredits, (width - lbl_width) / 2, height)

        self.__scroller = scroller
        self.__credits = mycredits

        self.__scroller_values = (height - 32, -lbl_height,
                                  (width - lbl_width) / 2)


    def __scroll(self, ycoord):

        begin, end, xcoord = self.__scroller_values
        self.__scroller.move(self.__credits, xcoord, ycoord)
        ycoord -= 1

        if (ycoord < end):
            ycoord = begin

        if (not self.__is_stopped):
            gobject.timeout_add(50, self.__scroll, ycoord)

        return False


    def __on_close(self, *args):

        self.__is_stopped = True
        self.hide()
        return True


    def show(self):

        if (not self.__is_stopped):
            return

        self.show_all()

        self.__is_stopped = False
        begin, end, xcoord = self.__scroller_values
        gobject.idle_add(self.__scroll, begin)


def input_box( parent, title, text, input_text = None):
    dlg = EntryDialog(parent, title, text)
    if input_text:
        dlg.entry.set_text(input_text)
    rc = dlg.run()
    dlg.destroy()
    return rc

def FileChooser(basedir = None, pattern = None, action = gtk.FILE_CHOOSER_ACTION_OPEN, buttons = (gtk.STOCK_CANCEL, gtk.RESPONSE_CANCEL, gtk.STOCK_OPEN, gtk.RESPONSE_OK)):
    # open file selector
    chooser_title = _("Sulfur file chooser")
    dialog = gtk.FileChooserDialog(
        title = chooser_title,
        action = action,
        buttons = buttons
    )
    if not basedir:
        basedir = os.getenv('HOME')
        if not basedir:
            basedir = "/tmp"

    fn = None
    dialog.set_current_folder(basedir)
    if pattern:
        myfilter = gtk.FileFilter()
        myfilter.add_pattern(pattern)
        dialog.set_filter(myfilter)
    response = dialog.run()
    if response == gtk.RESPONSE_OK:
        fn = dialog.get_filename()
    dialog.destroy()
    return fn

def errorMessage( parent, title, text, longtext=None, modal= True, showreport = False ):
     dlg = ErrorDialog( parent, title, text, longtext, modal )
     rc = dlg.run(showreport)
     entries = dlg.get_entries()
     dlg.destroy()
     return rc, entries

def infoMessage( parent, title, text ):
    dlg = infoDialog( parent, title, text )
    rc = dlg.run()
    dlg.destroy()
    return not rc == gtk.RESPONSE_OK

def questionDialog(parent, msg, title = _("Sulfur Question"), get_response = False):
    dlg = gtk.MessageDialog(
        parent=parent,
        type = gtk.MESSAGE_QUESTION,
        buttons = gtk.BUTTONS_YES_NO,
        message_format = _("Hey!")
    )
    dlg.set_title(title)
    dlg.format_secondary_markup(cleanMarkupString(msg))
    rc = dlg.run()
    dlg.destroy()
    if get_response:
        return rc
    if rc == gtk.RESPONSE_YES:
        return True
    return False

def choiceDialog(parent, msg, title, buttons):
    return MessageDialog(parent, title, msg, type = "custom",
        custom_buttons = buttons).getrc()

def inputDialog(parent, title, input_parameters, cancel):
    w = InputDialog(parent, title, input_parameters, cancel)
    return w.run()

def okDialog(parent, msg, title = None):
    dlg = gtk.MessageDialog(parent=parent,
                            type=gtk.MESSAGE_INFO,
                            buttons=gtk.BUTTONS_OK)
    dlg.set_markup(cleanMarkupString(msg))
    if not title:
        title = _("Attention")
    dlg.set_title(title)
    dlg.run()
    dlg.destroy()

class InputDialog:

    def __init__(self, parent, title, input_parameters, cancel = True):

        self.parameters = {}
        self.button_pressed = False
        mywin = gtk.Window()
        self.main_window = mywin
        self.parent = parent
        self.callback_parent_window = mywin

        mywin.set_title(_("Please fill the following form"))
        myvbox = gtk.VBox()
        mylabel = gtk.Label()
        mylabel.set_markup(cleanMarkupString(title))
        myhbox = gtk.HBox()
        myvbox.pack_start(mylabel, expand = False, fill = False)
        mytable = gtk.Table(rows = len(input_parameters), columns = 2)
        self.identifiers_table = {}
        self.cb_table = {}
        self.entry_text_table = {}
        self.entry_enter_event_widgets = []
        row_count = 0
        for input_id, input_text, input_cb, passworded in input_parameters:

            if isinstance(input_text, tuple):

                input_type, text = input_text
                combo_options = []
                if isinstance(text, tuple):
                    text, combo_options = text

                input_label = gtk.Label()
                input_label.set_line_wrap(True)
                input_label.set_alignment(0.0, 0.5)
                input_label.set_markup(text)

                if input_type == "checkbox":

                    input_widget = gtk.CheckButton(text)
                    input_widget.set_alignment(0.0, 0.5)
                    input_widget.set_active(passworded)

                elif input_type == "combo":

                    input_widget = gtk.combo_box_new_text()
                    for opt in combo_options:
                        input_widget.append_text(opt)
                    if combo_options:
                        input_widget.set_active(0)
                    mytable.attach(input_label, 0, 1, row_count, row_count+1)

                elif input_type == "list":

                    myhbox_l = gtk.HBox()
                    input_widget = gtk.ListStore(gobject.TYPE_STRING)
                    view = gtk.TreeView()
                    cell = gtk.CellRendererText()
                    column = gtk.TreeViewColumn( text, cell, markup = 0 )
                    column.set_resizable( True )
                    column.set_sizing( gtk.TREE_VIEW_COLUMN_FIXED )
                    column.set_expand(True)
                    view.append_column( column )
                    view.set_model(input_widget)
                    for opt in combo_options:
                        input_widget.append((opt,))
                    myhbox_l.pack_start(view, expand = True, fill = True)

                    myvbox_l = gtk.VBox()
                    add_button = gtk.Button()
                    add_image = gtk.Image()
                    add_image.set_from_stock("gtk-add", gtk.ICON_SIZE_BUTTON)
                    add_button.add(add_image)
                    rm_button = gtk.Button()
                    rm_image = gtk.Image()
                    rm_image.set_from_stock("gtk-remove", gtk.ICON_SIZE_BUTTON)
                    rm_button.add(rm_image)
                    myvbox_l.pack_start(add_button, expand = False, fill = False)
                    myvbox_l.pack_start(rm_button, expand = False, fill = False)

                    def on_add_button(widget):
                        mydata = inputDialog(mywin, _("Add atom"),
                            [('atom', _('Atom'), input_cb, False)], True)
                        if mydata is None:
                            return
                        atom = mydata.get('atom')
                        input_widget.append((atom,))

                    def on_remove_button(widget):
                        model, iterator = view.get_selection().get_selected()
                        if iterator is None:
                            return
                        model.remove(iterator)

                    add_button.connect("clicked", on_add_button)
                    rm_button.connect("clicked", on_remove_button)

                    myhbox_l.pack_start(myvbox_l, expand = False, fill = False)
                    mytable.attach(myhbox_l, 0, 2, row_count, row_count+1)

                elif input_type == "filled_text":

                    input_widget = gtk.Entry()
                    self.entry_enter_event_widgets.append(input_widget)
                    input_widget.set_text(combo_options)
                    if passworded:
                        input_widget.set_visibility(False)
                    mytable.attach(input_label, 0, 1, row_count, row_count+1)

                elif input_type == "text":

                    def rescroll_output(adj, scroll):
                        adj.set_value(adj.upper-adj.page_size)
                        scroll.set_vadjustment(adj)

                    scrolled_win = gtk.ScrolledWindow()
                    scrolled_win.set_policy(gtk.POLICY_AUTOMATIC, gtk.POLICY_AUTOMATIC)
                    scrolled_win.set_placement(gtk.CORNER_BOTTOM_LEFT)
                    # textview
                    input_widget = gtk.TextBuffer()
                    output_scroll_vadj = scrolled_win.get_vadjustment()
                    output_scroll_vadj.connect('changed', lambda a, s=scrolled_win: rescroll_output(a, s))

                    my_tv = gtk.TextView()
                    my_tv.set_buffer(input_widget)
                    my_tv.set_wrap_mode(gtk.WRAP_WORD)
                    my_tv.set_editable(True)
                    my_tv.set_accepts_tab(True)
                    scrolled_win.add_with_viewport(my_tv)
                    mytable.attach(input_label, 0, 1, row_count, row_count+1)
                    mytable.attach(scrolled_win, 1, 2, row_count, row_count+1)

                else:
                    continue

                self.entry_text_table[input_id] = text
                self.identifiers_table[input_id] = input_widget

                if input_type in ["list", "text", "combo", "filled_text"]:
                    def my_input_cb(s):
                        return s
                    self.cb_table[input_widget] = my_input_cb
                elif input_type == "checkbox":
                    def my_input_cb(s):
                        return True
                    self.cb_table[input_widget] = my_input_cb


                if input_type not in ["text", "list"]:
                    mytable.attach(input_widget, 1, 2, row_count, row_count+1)


            else:

                input_label = gtk.Label()
                input_label.set_line_wrap(True)
                input_label.set_alignment(0.0, 0.5)
                input_label.set_markup(input_text)
                self.entry_text_table[input_id] = input_text
                mytable.attach(input_label, 0, 1, row_count, row_count+1)
                input_entry = gtk.Entry()
                self.entry_enter_event_widgets.append(input_entry)
                if passworded:
                    input_entry.set_visibility(False)

                self.identifiers_table[input_id] = input_entry
                self.cb_table[input_entry] = input_cb
                mytable.attach(input_entry, 1, 2, row_count, row_count+1)

            row_count += 1
        myvbox.pack_start(mytable)
        bbox = gtk.HButtonBox()
        bbox.set_layout(gtk.BUTTONBOX_END)
        bbox.set_spacing(10)
        myok = gtk.Button(stock = "gtk-ok")
        myok.connect('clicked', self.do_ok )
        bbox.pack_start(myok, padding = 10)
        if cancel:
            mycancel = gtk.Button(stock = "gtk-cancel")
            mycancel.connect('clicked', self.do_cancel )
            bbox.pack_start(mycancel)
        myvbox.pack_start(bbox, expand = False, fill = False)
        myvbox.set_spacing(10)
        myvbox.show()
        myhbox.pack_start(myvbox, padding = 10)
        myhbox.show()
        mywin.add(myhbox)
        mywin.set_keep_above(True)
        mywin.set_urgency_hint(True)
        if parent is None:
            mywin.set_position(gtk.WIN_POS_CENTER)
        else:
            mywin.set_transient_for(parent)
            mywin.set_position(gtk.WIN_POS_CENTER_ON_PARENT)
        mywin.set_default_size(350, -1)

        for entry in self.entry_enter_event_widgets:
            entry.connect("activate", self._got_entry_activate)

        mywin.show_all()


    def _got_entry_activate(self, widget):
        last_one = len(self.entry_enter_event_widgets) == 1
        if not last_one:
            last_one = widget is self.entry_enter_event_widgets[-1]
        if last_one:
            return self.do_ok(widget)

    def do_ok(self, widget):
        # re-allocate parameters if None
        if self.parameters is None:
            self.parameters = {}

        for input_id in self.identifiers_table:
            mywidget = self.identifiers_table.get(input_id)
            if isinstance(mywidget, gtk.Entry):
                content = mywidget.get_text()
            elif isinstance(mywidget, gtk.CheckButton):
                content = mywidget.get_active()
            elif isinstance(mywidget, gtk.ComboBox):
                content = mywidget.get_active(), mywidget.get_active_text()
            elif isinstance(mywidget, gtk.TextBuffer):
                content = mywidget.get_text(mywidget.get_start_iter(),
                    mywidget.get_end_iter(), True)
            elif isinstance(mywidget, (gtk.ListStore, gtk.TreeStore)):
                myiter = mywidget.get_iter_first()
                content = []
                while myiter:
                    content.append(mywidget.get_value(myiter, 0))
                    myiter = mywidget.iter_next(myiter)
            else:
                continue
            verify_cb = self.cb_table.get(mywidget)
            valid = verify_cb(content)
            if not valid:
                okDialog(self.callback_parent_window, "%s: %s" % (
                    _("Invalid entry"),
                    self.entry_text_table[input_id],),
                    title = _("Invalid entry"))
                self.parameters.clear()
                return
            self.parameters[input_id] = content
        self.button_pressed = True

    def do_cancel(self, widget):
        self.parameters = None
        self.button_pressed = True

    def run(self):
        self.parameters.clear()
        while not self.button_pressed:
            time.sleep(0.05)
            while gtk.events_pending():
                gtk.main_iteration()
        self.main_window.destroy()
        return self.parameters

class MessageDialog:

    def getrc(self):
        return self.rc

    def __init__ (self, parent, title, text, type = "ok", default=None,
        custom_buttons=None, custom_icon=None):

        self.rc = None
        docustom = 0
        if type == 'ok':
            buttons = gtk.BUTTONS_OK
            style = gtk.MESSAGE_INFO
        elif type == 'warning':
            buttons = gtk.BUTTONS_OK
            style = gtk.MESSAGE_WARNING
        elif type == 'okcancel':
            buttons = gtk.BUTTONS_OK_CANCEL
            style = gtk.MESSAGE_WARNING
        elif type == 'yesno':
            buttons = gtk.BUTTONS_YES_NO
            style = gtk.MESSAGE_QUESTION
        elif type == 'custom':
            docustom = 1
            buttons = gtk.BUTTONS_NONE
            style = gtk.MESSAGE_QUESTION

        if custom_icon == "warning":
            style = gtk.MESSAGE_WARNING
        elif custom_icon == "question":
            style = gtk.MESSAGE_QUESTION
        elif custom_icon == "error":
            style = gtk.MESSAGE_ERROR
        elif custom_icon == "info":
            style = gtk.MESSAGE_INFO

        dialog = gtk.MessageDialog(parent, 0, style, buttons, text)

        if docustom:
            rid=0
            for button in custom_buttons:
                if button == _("Cancel"):
                    tbutton = "gtk-cancel"
                else:
                    tbutton = button

                widget = dialog.add_button(tbutton, rid)
                rid = rid + 1

            defaultchoice = rid - 1
        else:
            if default == "no":
                defaultchoice = 0
            elif default == "yes" or default == "ok":
                defaultchoice = 1
            else:
                defaultchoice = 0

        dialog.set_title(title)
        #dialog.format_secondary_markup(cleanMarkupString(text))
        dialog.set_position (gtk.WIN_POS_CENTER)
        dialog.set_default_response(defaultchoice)
        dialog.show_all()

        rc = dialog.run()

        if rc == gtk.RESPONSE_OK or rc == gtk.RESPONSE_YES:
            self.rc = 1
        elif (rc == gtk.RESPONSE_CANCEL or rc == gtk.RESPONSE_NO
            or rc == gtk.RESPONSE_CLOSE):
            self.rc = 0
        elif rc == gtk.RESPONSE_DELETE_EVENT:
            self.rc = 0
        else:
            self.rc = rc
        dialog.destroy()

class LicenseDialog:

    def __init__( self, application, entropy, licenses ):

        self.accepted = set()
        self.parent = application.ui.main
        self.Sulfur = application
        self.Entropy = entropy
        self.xml = gtk.glade.XML( const.GLADE_FILE, 'licenseWindow',
            domain = "entropy" )
        self.xml_licread = gtk.glade.XML( const.GLADE_FILE, 'textReadWindow',
            domain = "entropy" )
        self.dialog = self.xml.get_widget( "licenseWindow" )
        self.dialog.set_transient_for( self.parent )
        self.read_dialog = self.xml_licread.get_widget( "textReadWindow" )
        self.read_dialog.connect( 'delete-event', self.close_read_text_window )
        #self.read_dialog.set_transient_for( self.dialog )
        self.licenseView = self.xml_licread.get_widget( "readTextView" )
        self.okReadButton = self.xml_licread.get_widget( "okReadButton" )
        self.okReadButton.connect( "clicked", self.close_read_text )

        self.okButton = self.xml.get_widget( "confirmLicense" )
        self.stopButton = self.xml.get_widget( "discardLicense" )
        self.acceptLicense = self.xml.get_widget( "acceptLicense" )
        self.acceptLicense.connect( "clicked", self.accept_selected_license )
        self.readLicense = self.xml.get_widget( "readLicense" )
        self.readLicense.connect( "clicked", self.read_selected_license )

        self.view = self.xml.get_widget( "licenseView1" )
        self.model = self.setup_view()
        self.show_data( licenses )
        self.view.expand_all()
        self.licenses = licenses


    def close_read_text_window(self, widget, path):
        self.read_dialog.hide()
        return True

    def close_read_text(self, widget ):
        self.read_dialog.hide()

    def run( self ):
        self.dialog.show()
        return self.dialog.run()

    def destroy( self ):
        return self.dialog.destroy()

    def setup_view(self):
        model = gtk.TreeStore( gobject.TYPE_STRING, gobject.TYPE_PYOBJECT )
        self.view.set_model( model )
        self.create_text_column( _( "License" ), 0, size = 200 )

        cell2 = gtk.CellRendererPixbuf()    # new
        column2 = gtk.TreeViewColumn( _("Accepted"), cell2 )
        column2.set_cell_data_func( cell2, self.new_pixbuf )
        column2.set_sizing( gtk.TREE_VIEW_COLUMN_FIXED )
        column2.set_fixed_width( 20 )
        column2.set_sort_column_id( -1 )
        self.view.append_column( column2 )
        column2.set_clickable( False )

        return model

    def set_pixbuf_to_cell(self, cell, do):
        if do:
            cell.set_property( 'stock-id', 'gtk-apply' )
        elif (not do) and isinstance(do, bool):
            cell.set_property( 'stock-id', 'gtk-cancel' )
        else:
            cell.set_property( 'stock-id', None )

    def new_pixbuf( self, column, cell, model, iterator ):
        license_identifier = model.get_value( iterator, 0 )
        chief = model.get_value( iterator, 1 )
        if (license_identifier in self.accepted) and chief:
            self.set_pixbuf_to_cell(cell, True)
        elif chief:
            self.set_pixbuf_to_cell(cell, False)
        elif chief is None:
            self.set_pixbuf_to_cell(cell, None)

    def create_text_column( self, hdr, colno, size = None ):
        cell = gtk.CellRendererText()    # Size Column
        column = gtk.TreeViewColumn( hdr, cell, markup=colno )
        if size != None:
            column.set_sizing( gtk.TREE_VIEW_COLUMN_FIXED )
            column.set_fixed_width( size )
        column.set_resizable( False )
        self.view.append_column( column )

    def read_selected_license(self, widget):
        model, iterator = self.view.get_selection().get_selected()
        if model != None and iterator != None:

            if model.iter_depth(iterator):
                # we need to get its parent
                iterator = model.get_iter_root()

            license_identifier = model.get_value( iterator, 0 )
            # for security reasons
            if license_identifier not in self.licenses:
                return

            packages = self.licenses[license_identifier]
            license_text = ''
            for package in packages:
                repoid = package[1]
                dbconn = self.Entropy.open_repository(repoid)
                if dbconn.isLicenseDataKeyAvailable(license_identifier):
                    license_text = dbconn.retrieveLicenseText(license_identifier)
                    break

            # prepare textview
            mybuffer = gtk.TextBuffer()
            try:
                utf_lic_text = license_text.decode('utf-8')
            except UnicodeDecodeError: # old license text stored, will be rm'ed
                utf_lic_text = const_convert_to_unicode(license_text)
            mybuffer.set_text(utf_lic_text)
            self.licenseView.set_buffer(mybuffer)
            txt = "[%s] %s" % (license_identifier, _("license text"),)
            self.read_dialog.set_title(txt)
            self.read_dialog.show()

    def accept_selected_license(self, widget):
        model, iterator = self.view.get_selection().get_selected()
        if model != None and iterator != None:

            if model.iter_depth(iterator):
                # we need to get its parent
                iterator = model.get_iter_root()

            license_identifier = model.get_value( iterator, 0 )
            chief = model.get_value( iterator, 1 )
            if chief:
                self.accepted.add(license_identifier)
                self.view.queue_draw()
                if len(self.accepted) == len(self.licenses):
                    self.okButton.set_sensitive(True)

    def show_data( self, licenses ):
        self.model.clear()
        for lic in licenses:
            parent = self.model.append( None, [lic, True] )
            packages = licenses[lic]
            for match in packages:
                dbconn = self.Entropy.open_repository(match[1])
                atom = dbconn.retrieveAtom(match[0])
                self.model.append( parent, [atom, None] )

class ExceptionDialog:

    def show(self, errmsg = None, submitmsg = None, exc_data = None):

        if errmsg is None:
            errmsg = entropy.tools.get_traceback()
        if submitmsg is None:
            submitmsg = errmsg
        rc, (name, mail, description) = errorMessage(
            None,
            _( "Exception caught" ),
            _( "Sulfur crashed! An unexpected error occured." ),
            errmsg,
            showreport = True
        )
        if rc == -1:

            from entropy.client.interfaces.qa import UGCErrorReportInterface
            from entropy.core.settings.base import SystemSettings
            repository_id = SystemSettings()['repositories']['default_repository']
            try:
                error = UGCErrorReportInterface(repository_id)
            except (AttributeError, OnlineMirrorError,):
                error = None

            result = None
            if exc_data is None:
                exc_data = []
            if error is not None:
                error.prepare(submitmsg, name, mail,
                    '\n'.join([x for x in exc_data]),
                    description = description)
                result = error.submit()
            if result:
                okDialog(None, _("Your report has been submitted successfully! Thanks a lot."))
            else:
                okDialog(None, _("Cannot submit your report. Not connected to Internet?"))
