#!/usr/bin/python2 -O
# -*- coding: iso-8859-1 -*-
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
import gtk
import gobject
import time

from entropy.exceptions import QueueError
import entropy.tools
from entropy.const import etpConst, const_extract_cli_repo_params, \
    initconfig_entropy_constants
from entropy.i18n import _
from entropy.misc import TimeScheduled, ParallelTask

from sulfur.filters import Filter
from sulfur.setup import SulfurConf, const, cleanMarkupString
from sulfur.dialogs import okDialog, inputBox, TextReadDialog, questionDialog, \
    RepositoryManagerMenu, FileChooser, AboutDialog, errorMessage, \
    AddRepositoryWindow
from sulfur.misc import busyCursor, normalCursor

class SulfurApplicationEventsMixin:

    def on_console_click(self, widget, event):
        self.console_menu.popup( None, None, None, event.button, event.time )
        return True

    def on_dbBackupButton_clicked(self, widget):
        self.wait_window.show()
        self.startWorking()
        status, err_msg = self.Equo.backup_database(
            etpConst['etpdatabaseclientfilepath'])
        self.endWorking()
        if not status:
            self.wait_window.hide()
            okDialog( self.ui.main, "%s: %s" % (_("Error during backup"),
                err_msg,) )
            return
        okDialog( self.ui.main, "%s" % (_("Backup complete"),) )
        self.fillPreferencesDbBackupPage()
        self.dbBackupView.queue_draw()
        self.wait_window.hide()

    def on_dbRestoreButton_clicked(self, widget):
        model, myiter = self.dbBackupView.get_selection().get_selected()
        if myiter == None: return
        dbpath = model.get_value(myiter, 0)
        self.wait_window.show()
        self.startWorking()
        status, err_msg = self.Equo.restore_database(dbpath,
            etpConst['etpdatabaseclientfilepath'])
        self.endWorking()
        self.Equo.reopen_client_repository()
        self.reset_cache_status()
        self.addPackages()
        if not status:
            self.wait_window.hide()
            okDialog( self.ui.main, "%s: %s" % (_("Error during restore"),
                err_msg,) )
            return
        self.fillPreferencesDbBackupPage()
        self.dbBackupView.queue_draw()
        self.wait_window.hide()
        okDialog( self.ui.main, "%s" % (_("Restore complete"),) )

    def on_dbDeleteButton_clicked(self, widget):
        model, myiter = self.dbBackupView.get_selection().get_selected()
        if myiter == None: return
        dbpath = model.get_value(myiter, 0)
        try:
            if os.path.isfile(dbpath) and os.access(dbpath,os.W_OK):
                os.remove(dbpath)
        except OSError, e:
            okDialog( self.ui.main, "%s: %s" % (_("Error during removal"),e,) )
            return
        self.fillPreferencesDbBackupPage()
        self.dbBackupView.queue_draw()

    def on_updateAdvSelected_clicked( self, widget ):

        if not self.etpbase.selected_advisory_item:
            return

        key, affected, data = self.etpbase.selected_advisory_item
        if not affected:
            okDialog( self.ui.main, _("The chosen package is not vulnerable") )
            return
        atoms = set()
        for mykey in data['affected']:
            affected_data = data['affected'][mykey][0]
            atoms |= set(affected_data['unaff_atoms'])

        rc = self.add_atoms_to_queue(atoms, always_ask = True)
        if rc: okDialog( self.ui.main, _("Packages in Advisory have been queued.") )

    def on_updateAdvAll_clicked( self, widget ):

        adv_data = self.Advisories.get_advisories_metadata()
        atoms = set()
        for key in adv_data:
            affected = self.Advisories.is_affected(key)
            if not affected:
                continue
            for mykey in adv_data[key]['affected']:
                affected_data = adv_data[key]['affected'][mykey][0]
                atoms |= set(affected_data['unaff_atoms'])

        rc = self.add_atoms_to_queue(atoms, always_ask = True)
        if rc:
            okDialog( self.ui.main,
                _("Packages in all Advisories have been queued.") )

    def on_advInfoButton_clicked( self, widget ):
        if self.etpbase.selected_advisory_item:
            self.loadAdvInfoMenu(self.etpbase.selected_advisory_item)

    def on_pkgInfoButton_clicked( self, widget ):
        if self.etpbase.selected_treeview_item:
            self.loadPkgInfoMenu(self.etpbase.selected_treeview_item)

    def on_filesDelete_clicked( self, widget ):
        identifier, source, dest = self._get_Edit_filename()
        if not identifier:
            return True
        self.Equo.FileUpdates.remove_file(identifier)
        self.filesView.populate(self.Equo.FileUpdates.scandata)

    def on_filesMerge_clicked( self, widget ):
        identifier, source, dest = self._get_Edit_filename()
        if not identifier:
            return True
        self.Equo.FileUpdates.merge_file(identifier)
        self.filesView.populate(self.Equo.FileUpdates.scandata)

    def on_mergeFiles_clicked( self, widget ):
        self.Equo.FileUpdates.scanfs(dcache = True)
        keys = self.Equo.FileUpdates.scandata.keys()
        for key in keys:
            self.Equo.FileUpdates.merge_file(key)
            # it's cool watching it runtime
        self.filesView.populate(self.Equo.FileUpdates.scandata)

    def on_deleteFiles_clicked( self, widget ):
        self.Equo.FileUpdates.scanfs(dcache = True)
        keys = self.Equo.FileUpdates.scandata.keys()
        for key in keys:
            self.Equo.FileUpdates.remove_file(key)
            # it's cool watching it runtime
        self.filesView.populate(self.Equo.FileUpdates.scandata)

    def on_filesEdit_clicked( self, widget ):
        identifier, source, dest = self._get_Edit_filename()
        if not identifier:
            return True

        """
        if not os.access(source, os.R_OK | os.W_OK | os.F_OK):
            return
        source_f = open(source)
        txt = source_f.read()
        source_f.close()
        TextReadDialog(source, txt, read_only = False, rw_save_path = source)
        """
        self.runEditor(source)

    def on_filesView_row_activated( self, widget, iterator, path ):
        self.on_filesViewChanges_clicked(widget)

    def on_filesViewChanges_clicked( self, widget ):
        import commands
        identifier, source, dest = self._get_Edit_filename()
        if not identifier:
            return True
        diffcmd = "diff -Nu "+dest+" "+source

        mybuffer = gtk.TextBuffer()
        red_tt = mybuffer.create_tag("red", foreground = "red")
        green_tt = mybuffer.create_tag("green", foreground = "darkgreen")

        for line in commands.getoutput(diffcmd).split("\n"):
            myiter = mybuffer.get_end_iter()
            if line.startswith("+"):
                mybuffer.insert_with_tags(myiter, line+"\n", green_tt)
            elif line.startswith("-"):
                mybuffer.insert_with_tags(myiter, line+"\n", red_tt)
            else:
                mybuffer.insert(myiter, line+"\n")
        TextReadDialog(dest, mybuffer)

    def on_filesViewRefresh_clicked( self, widget ):
        self.Equo.FileUpdates.scanfs(dcache = False)
        self.filesView.populate(self.Equo.FileUpdates.scandata)

    def on_shiftUp_clicked( self, widget ):
        idx, repoid, iterdata = self._get_selected_repo_index()
        if idx != None:
            path = iterdata[0].get_path(iterdata[1])[0]
            if path > 0 and idx > 0:
                idx -= 1
                self.Equo.shift_repository(repoid, idx)
                # get next iter
                prev = iterdata[0].get_iter(path-1)
                self.repoView.store.swap(iterdata[1],prev)

    def on_shiftDown_clicked( self, widget ):
        idx, repoid, iterdata = self._get_selected_repo_index()
        if idx != None:
            next = iterdata[0].iter_next(iterdata[1])
            if next:
                idx += 1
                self.Equo.shift_repository(repoid, idx)
                self.repoView.store.swap(iterdata[1],next)

    def on_addRepo_clicked( self, widget ):
        my = AddRepositoryWindow(self, self.ui.main, self.Equo)
        my.load()

    def on_removeRepo_clicked( self, widget ):
        # get selected repo
        selection = self.repoView.view.get_selection()
        repodata = selection.get_selected()
        # get text
        if repodata[1] != None:
            repoid = self.repoView.get_repoid(repodata)
            if repoid == self.Equo.SystemSettings['repositories']['default_repository']:
                okDialog( self.ui.main,
                    _("You! Why do you want to remove the main repository ?"))
                return True
            self.Equo.remove_repository(repoid)
            self.reset_cache_status()
            self.setupRepoView()
            msg = "%s '%s' %s '%s' %s" % (_("You must now either press the"),
                _("Update Repositories"), _("or the"), _("Regenerate Cache"),
                _("now"))
            okDialog( self.ui.main, msg )

    def on_repoEdit_clicked( self, widget ):
        self.addrepo_ui.repoSubmit.hide()
        self.addrepo_ui.repoSubmitEdit.show()
        self.addrepo_ui.repoInsert.hide()
        self.addrepo_ui.repoidEntry.set_editable(False)
        # get selection
        selection = self.repoView.view.get_selection()
        repostuff = selection.get_selected()
        if repostuff[1] != None:
            repoid = self.repoView.get_repoid(repostuff)
            repodata = self.Equo.get_repository_settings(repoid)
            self._load_repo_data(repodata)
            self.addrepo_ui.addRepoWin.show()

    def on_terminal_clear_activate(self, widget):
        self.output.text_written = []
        self.console.reset()

    def on_terminal_copy_activate(self, widget):
        self.clipboard.clear()
        self.clipboard.set_text(''.join(self.output.text_written))

    def on_Preferences_toggled(self, widget, toggle = True):
        self.ui.preferencesSaveButton.set_sensitive(toggle)
        self.ui.preferencesRestoreButton.set_sensitive(toggle)

    def on_preferencesSaveButton_clicked(self, widget):
        sure = questionDialog(self.ui.main, _("Are you sure ?"))
        if not sure:
            return
        for config_file in self.Preferences:
            for name, setting, mytype, fillfunc, savefunc, wgwrite, wgread in self.Preferences[config_file]:
                if mytype == list:
                    savefunc(config_file, name, setting, mytype, wgwrite, wgread)
                else:
                    data = wgread()
                    result = savefunc(config_file, name, setting, mytype, data)
                    if not result:
                        errorMessage(
                            self.ui.main,
                            cleanMarkupString("%s: %s") % (_("Error saving parameter"),name,),
                            _("An issue occured while saving a preference"),
                            "%s %s: %s" % (_("Parameter"),name,_("not saved"),),
                        )
        initconfig_entropy_constants(etpConst['systemroot'])
        # re-read configprotect
        self.reset_cache_status()
        self.addPackages()
        self.Equo.reload_repositories_config()
        self.setupPreferences()

    def on_preferencesRestoreButton_clicked(self, widget):
        self.setupPreferences()

    def on_configProtectNew_clicked(self, widget):
        data = inputBox( self.ui.main, _("New"), _("Please insert a new path"))
        if not data:
            return
        self.configProtectModel.append([data])

    def on_configProtectMaskNew_clicked(self, widget):
        data = inputBox( self.ui.main, _("New"), _("Please insert a new path"))
        if not data:
            return
        self.configProtectMaskModel.append([data])

    def on_configProtectSkipNew_clicked(self, widget):
        data = inputBox( self.ui.main, _("New"), _("Please insert a new path"))
        if not data:
            return
        self.configProtectSkipModel.append([data])

    def on_configProtectDelete_clicked(self, widget):
        model, myiter = self.configProtectView.get_selection().get_selected()
        if myiter:
            model.remove(myiter)

    def on_configProtectMaskDelete_clicked(self, widget):
        model, myiter = self.configProtectMaskView.get_selection().get_selected()
        if myiter:
            model.remove(myiter)

    def on_configProtectSkipDelete_clicked(self, widget):
        model, myiter = self.configProtectSkipView.get_selection().get_selected()
        if myiter:
            model.remove(myiter)

    def on_configProtectEdit_clicked(self, widget):
        model, myiter = self.configProtectView.get_selection().get_selected()
        if myiter:
            item = model.get_value( myiter, 0 )
            data = inputBox( self.ui.main, _("New"),
                _("Please edit the selected path"), input_text = item)
            if not data:
                return
            model.remove(myiter)
            self.configProtectModel.append([data])

    def on_configProtectMaskEdit_clicked(self, widget):
        model, myiter = self.configProtectMaskView.get_selection().get_selected()
        if myiter:
            item = model.get_value( myiter, 0 )
            data = inputBox( self.ui.main, _("New"),
                _("Please edit the selected path"), input_text = item)
            if not data:
                return
            model.remove(myiter)
            self.configProtectMaskModel.append([data])

    def on_configProtectSkipEdit_clicked(self, widget):
        model, myiter = self.configProtectSkipView.get_selection().get_selected()
        if myiter:
            item = model.get_value( myiter, 0 )
            data = inputBox( self.ui.main, _("New"),
                _("Please edit the selected path"), input_text = item)
            if not data:
                return
            model.remove(myiter)
            self.configProtectSkipModel.append([data])

    def on_installPackageItem_activate(self, widget = None, fn = None):

        if (widget and self.isWorking) or self.isBusy:
            return

        if not fn:
            mypattern = '*'+etpConst['packagesext']
            fn = FileChooser(pattern = mypattern)
        if not fn:
            return
        elif not os.access(fn,os.R_OK):
            return

        msg = "%s: %s. %s" % (
            _("You have chosen to install this package"),
            os.path.basename(fn),
            _("Are you supa sure?"),
        )
        rc = questionDialog(self.ui.main, msg)
        if not rc:
            return

        self.pkgView.store.clear()

        newrepo = os.path.basename(fn)
        # we have it !
        status, atomsfound = self.Equo.add_tbz2_to_repos(fn)
        if status != 0:
            errtxt = _("is not a valid Entropy package")
            if status == -3:
                errtxt = _("is not compiled with the same architecture of the system")
            mytxt = "%s %s. %s." % (
                os.path.basename(fn),
                errtxt,
                _("Cannot install"),
            )
            okDialog(self.ui.main, mytxt)
            return

        def clean_n_quit(newrepo):
            self.Equo.remove_repository(newrepo)
            self.reset_cache_status()
            self.Equo.reopen_client_repository()
            # regenerate packages information
            self.setup_application()

        if not atomsfound:
            clean_n_quit(newrepo)
            return

        pkgs = []
        for idpackage, atom in atomsfound:
            yp, new = self.etpbase.getPackageItem((idpackage,newrepo,))
            yp.action = 'i'
            yp.queued = 'i'
            pkgs.append(yp)

        busyCursor(self.ui.main)
        status, myaction = self.queue.add(pkgs)
        if status != 0:
            for obj in pkgs:
                obj.queued = None
            clean_n_quit(newrepo)
            normalCursor(self.ui.main)
            return

        normalCursor(self.ui.main)
        self.setPage('output')

        try:
            rc = self.process_queue(self.queue.packages,
                remove_repos = [newrepo])
        except:
            if self.do_debug:
                entropy.tools.print_traceback()
                import pdb; pdb.set_trace()
            else:
                raise

        self.resetQueueProgressBars()
        if rc:
            self.queue.clear()
            self.queueView.refresh()
            return True
        else: # not done
            clean_n_quit(newrepo)
            return False

    def on_PageButton_changed( self, widget, page ):

        # do not put here actions for 'packages' and 'output'
        # but use on_PageButton_pressed
        if page == "filesconf":
            self.populateFilesUpdate()
        elif page == "glsa":
            self.populateAdvisories(None,'affected')
        self.setNotebookPage(const.PAGES[page])

    def on_queueReviewAndInstall_clicked(self, widget):
        self.switchNotebookPage("queue")

    def on_pkgFilter_toggled(self,rb,action):

        if not rb.get_active(): return

        rb.grab_add()
        self.lastPkgPB = action

        # Only show add/remove all when showing updates
        if action == 'updates': self.ui.updatesButtonbox.show()
        else: self.ui.updatesButtonbox.hide()

        if action == "masked":
            self.setupMaskedPackagesWarningBox()
            self.ui.maskedWarningBox.show()
        else:
            self.ui.maskedWarningBox.hide()

        if action == "pkgsets": self.ui.pkgsetsButtonBox.show()
        else: self.ui.pkgsetsButtonBox.hide()

        if action == "queued": self.ui.queueReviewAndInstallBox.show()
        else: self.ui.queueReviewAndInstallBox.hide()

        self.addPackages()
        rb.grab_remove()

    def on_repoRefresh_clicked(self, widget):
        repos = self.repoView.get_selected()
        if not repos:
            okDialog( self.ui.main, _("Please select at least one repository") )
            return
        return self.do_repo_refresh(repos)

    def do_repo_refresh(self, repos):
        self.setPage('output')
        self.ui.main.queue_draw()
        self.uiLock(True)
        try:
            self.gtk_loop()
            self.startWorking()
            status = self.updateRepositories(repos)
            self.endWorking()
            self.progress.reset_progress()
            self.reset_cache_status()
            self.setupRepoView()
            self.setup_application()
            self.setupAdvisories()
            self.setPage('repos')
            if status:
                self.showNoticeBoard()
        finally:
            self.uiLock(False)

    def on_cacheButton_clicked(self,widget):
        self.repoView.get_selected()
        self.setPage('output')
        self.cleanEntropyCaches(alone = True)
        self.setPage('repos')

    def on_repoDeSelect_clicked(self,widget):
        self.repoView.deselect_all()

    def on_queueProcess_clicked( self, widget ):

        if self.queue.total() == 0: # Check there are any packages in the queue
            self.setStatus(_('No packages in queue'))
            return

        fetch_only = self.ui.queueProcessFetchOnly.get_active()
        download_sources = self.ui.queueProcessDownloadSource.get_active()

        rc = True
        try:
            rc = self.process_queue(self.queue.packages,
                fetch_only = fetch_only, download_sources = download_sources)
        except:
            if self.do_debug:
                entropy.tools.print_traceback()
                import pdb; pdb.set_trace()
            else: raise
        self.resetQueueProgressBars()
        if rc and not fetch_only:
            self.queue.clear()       # Clear package queue
            self.queueView.refresh() # Refresh Package Queue
        #if fetch_only:
        #    self.setPage('queue')

    def on_queueSave_clicked( self, widget ):
        fn = FileChooser(action = gtk.FILE_CHOOSER_ACTION_SAVE, buttons = (
            gtk.STOCK_CANCEL,gtk.RESPONSE_CANCEL,gtk.STOCK_SAVE,gtk.RESPONSE_OK))
        if fn:
            pkgdata = self.queue.get().copy()
            for key in pkgdata.keys():
                if pkgdata[key]: pkgdata[key] = [x.matched_atom for x in pkgdata[key]]
            self.Equo.dumpTools.dumpobj(fn,pkgdata,True)

    def on_queueOpen_clicked( self, widget ):
        fn = FileChooser()
        if fn:

            try:
                pkgdata = self.Equo.dumpTools.loadobj(fn, complete_path = True)
            except:
                return

            if not isinstance(pkgdata,dict):
                return

            collected_items = []
            for key in pkgdata.keys():
                for pkg in pkgdata[key]:
                    try:
                        yp, new = self.etpbase.getPackageItem(pkg)
                    except:
                        okDialog( self.ui.main,
                            _("Queue is too old. Cannot load.") )
                        return
                    collected_items.append((key,yp))

            for key, pkg in collected_items:
                pkg.queued = key
                self.queue.packages[key].append(pkg)

            self.queueView.refresh()

    def on_queueClean_clicked(self, widget):
        self.reset_cache_status()
        self.addPackages()

    def on_adv_doubleclick( self, widget, iterator, path ):
        ( model, iterator ) = widget.get_selection().get_selected()
        if model != None and iterator != None:
            data = model.get_value( iterator, 0 )
            if data:
                self.loadAdvInfoMenu(data)

    def on_pkg_doubleclick( self, widget, iterator, path ):
        objs = self.pkgView.collect_selected_items()
        for obj in objs:
            self.loadPkgInfoMenu(obj)

    def on_license_double_clicked( self, widget, iterator, path ):
        ( model, iterator ) = widget.get_selection().get_selected()
        if model != None and iterator != None:
            license_identifier = model.get_value( iterator, 0 )
            found = False
            license_text = ''
            if license_identifier:
                repoid = self.pkgProperties_selected.matched_atom[1]
                if type(repoid) is int:
                    dbconn = self.Equo.clientDbconn
                else:
                    dbconn = self.Equo.open_repository(repoid)
                if dbconn.isLicensedataKeyAvailable(license_identifier):
                    license_text = dbconn.retrieveLicenseText(license_identifier)
                    found = True
            if found:
                mytitle = "%s -- %s" % (license_identifier, _("license text"),)
                TextReadDialog(mytitle, license_text)

    def on_select_clicked(self,widget):
        self.wait_window.show()
        self.setBusy()
        self.startWorking()
        busyCursor(self.wait_ui.waitWindow)
        self.pkgView.selectAll()
        self.endWorking()
        self.unsetBusy()
        normalCursor(self.wait_ui.waitWindow)
        self.wait_window.hide()

    def on_deselect_clicked(self,widget):
        self.on_clear_clicked(widget)
        self.wait_window.show()
        self.setBusy()
        self.pkgView.deselectAll()
        self.wait_window.hide()
        self.unsetBusy()

    def on_skipMirror_clicked(self,widget):
        self.Equo.MirrorStatus.add_failing_working_mirror(75)
        self.skipMirrorNow = True

    def on_abortQueue_clicked(self,widget):
        msg = _("You have chosen to interrupt the processing. Are you sure you want to do it ?")
        rc = questionDialog(self.ui.main, msg)
        if rc: self.abortQueueNow = True

    def on_search_clicked(self,widget):
        self.etpbase.setFilter(Filter.processFilters)
        ''' Search entry+button handler'''
        txt = self.ui.pkgFilter.get_text()
        flt = Filter.get('KeywordFilter')
        if txt != '':
            flt.activate()
            lst = txt.split()
            flt.setKeys(lst)
            self.ui.pkgClr.show()
        else:
            flt.activate(False)
        action = self.lastPkgPB
        rb = self.packageRB[action]
        self.on_pkgFilter_toggled(rb,action)

    def on_clear_clicked(self,widget):
        self.etpbase.setFilter()
        ''' Search Clear button handler'''
        self.ui.pkgFilter.set_text("")
        self.on_search_clicked(None)
        self.ui.pkgClr.hide()

    def on_FileQuit( self, widget ):
        self.wait_window.show()
        self.quit()

    def on_HelpAbout( self, widget = None ):
        about = AboutDialog(const.PIXMAPS_PATH+'/spritz-about.png',
            const.CREDITS, SulfurConf.branding_title)
        about.show()

    def on_notebook1_switch_page(self, widget, page, page_num):
        if page_num == const.PREF_PAGES['ugc']:
            self.load_ugc_repositories()
        elif page_num == const.PREF_PAGES['colors']:
            self.load_color_settings()

    def on_ugcLoginButton_clicked(self, widget):
        if self.Equo.UGC == None: return
        model, myiter = self.ugcRepositoriesView.get_selection().get_selected()
        if (myiter == None) or (model == None): return
        obj = model.get_value( myiter, 0 )
        if obj:
            #logged_data = self.Equo.UGC.read_login(obj['repoid'])
            self.Equo.UGC.login(obj['repoid'], force = True)
            self.load_ugc_repositories()

    def on_ugcClearLoginButton_clicked(self, widget):
        if self.Equo.UGC == None: return
        model, myiter = self.ugcRepositoriesView.get_selection().get_selected()
        if (myiter == None) or (model == None): return
        obj = model.get_value( myiter, 0 )
        if obj:
            if not self.Equo.UGC.is_repository_eapi3_aware(obj['repoid']):
                return
            logged_data = self.Equo.UGC.read_login(obj['repoid'])
            if logged_data: self.Equo.UGC.remove_login(obj['repoid'])
            self.load_ugc_repositories()

    def on_ugcClearCacheButton_clicked(self, widget):
        if self.Equo.UGC == None: return
        repo_excluded = self.Equo.SystemSettings['repositories']['excluded']
        avail_repos = self.Equo.SystemSettings['repositories']['available']
        for repoid in list(set(avail_repos.keys()+repo_excluded.keys())):
            self.Equo.UGC.UGCCache.clear_cache(repoid)
            self.setStatus("%s: %s ..." % (_("Cleaning UGC cache of"),repoid,))
        self.setStatus("%s" % (_("UGC cache cleared"),))

    def on_ugcClearCredentialsButton_clicked(self, widget):
        if self.Equo.UGC == None:
            return
        repo_excluded = self.Equo.SystemSettings['repositories']['excluded']
        avail_repos = self.Equo.SystemSettings['repositories']['available']
        for repoid in list(set(avail_repos.keys()+repo_excluded.keys())):
            if not self.Equo.UGC.is_repository_eapi3_aware(repoid):
                continue
            logged_data = self.Equo.UGC.read_login(repoid)
            if logged_data: self.Equo.UGC.remove_login(repoid)
        self.load_ugc_repositories()
        self.setStatus("%s" % (_("UGC credentials cleared"),))

    def on_repoManagerMenuItem_activate(self, widget):
        mymenu = RepositoryManagerMenu(self.Equo, self.ui.main)
        rc = mymenu.load()
        if not rc: del mymenu

    def on_noticeBoardMenuItem_activate(self, widget):
        self.showNoticeBoard()

    def on_pkgsetAddButton_clicked(self, widget):

        current_sets = self.Equo.package_set_list()
        def fake_callback(s):
            if (s not in current_sets) and (" " not in s) and \
                (not s.startswith(etpConst['packagesetprefix'])):
                return True
            return False

        def lv_callback(atom):
            c_id, c_rc = self.Equo.clientDbconn.atomMatch(atom)
            if c_id != -1:
                return True
            c_id, c_rc = self.Equo.atom_match(atom)
            if c_id != -1:
                return True
            return False

        input_params = [
            ('name',_("Package Set name"),fake_callback,False),
            ('atoms',('list',(_('Package atoms'),[],),),lv_callback,False)
        ]

        data = self.Equo.inputBox(
            _('Choose what Package Set you want to add'),
            input_params,
            cancel_button = True
        )
        if data == None:
            return

        rc, msg = self.Equo.add_user_package_set(data.get("name"),
            data.get("atoms"))
        if rc != 0:
            okDialog(self.ui.main,"%s: %s" % (_("Error"),msg,))
            return

        self.etpbase.clearPackagesSingle("pkgsets")
        self.addPackages()

    def on_pkgsetRemoveButton_clicked(self, widget):

        def mymf(m):
            set_from, set_name, set_deps = m
            if set_from == etpConst['userpackagesetsid']:
                return set_name
            return 0
        avail_pkgsets = [x for x in map(mymf, self.Equo.package_set_list()) if \
            x != 0]

        def fake_callback(s):
            return s
        input_params = [
            ('pkgset',('combo', (_('Removable Package Set'), avail_pkgsets),),
                fake_callback, False)
        ]

        data = self.Equo.inputBox(
            _('Choose what Package Set you want to remove'),
            input_params,
            cancel_button = True
        )
        if data == None: return
        x_id,set_name = data.get("pkgset")

        rc, msg = self.Equo.remove_user_package_set(set_name)
        if rc != 0:
            okDialog(self.ui.main,"%s: %s" % (_("Error"),msg,))
            return

        self.etpbase.clearPackagesSingle("pkgsets")
        self.addPackages()

    def on_deptestButton_clicked(self, widget):

        self.switchNotebookPage("output")
        self.uiLock(True)
        self.startWorking()
        deps_not_matched = self.Equo.dependencies_test()
        if not deps_not_matched:
            okDialog(self.ui.main,_("No missing dependencies found."))
            self.switchNotebookPage("preferences")
            self.uiLock(False)
            self.endWorking()
            self.progress.reset_progress()
            return

        found_deps = set()
        not_all = False
        for dep in deps_not_matched:
            match = self.Equo.atom_match(dep)
            if match[0] != -1:
                found_deps.add(dep)
                continue
            else:
                iddep = self.Equo.clientDbconn.searchDependency(dep)
                if iddep == -1: continue
                c_idpackages = self.Equo.clientDbconn.searchIdpackageFromIddependency(iddep)
                for c_idpackage in c_idpackages:
                    key, slot = self.Equo.clientDbconn.retrieveKeySlot(c_idpackage)
                    key_slot = "%s:%s" % (key,slot,)
                    match = self.Equo.atom_match(key, matchSlot = slot)
                    cmpstat = 0
                    if match[0] != -1:
                        cmpstat = self.Equo.get_package_action(match)
                    if cmpstat != 0:
                        found_deps.add(key_slot)
                        continue
                    else:
                        not_all = True
                continue
            not_all = True

        if not found_deps:
            okDialog(self.ui.main,
                _("Missing dependencies found, but none of them are on the repositories."))
            self.switchNotebookPage("preferences")
            self.uiLock(False)
            self.endWorking()
            self.progress.reset_progress()
            return

        if not_all:
            okDialog(self.ui.main,
                _("Some missing dependencies have not been matched, others are going to be added to the queue."))
        else:
            okDialog(self.ui.main,
                _("All the missing dependencies are going to be added to the queue"))

        rc = self.add_atoms_to_queue(found_deps)
        if rc: self.switchNotebookPage("queue")
        else: self.switchNotebookPage("preferences")
        self.uiLock(False)
        self.endWorking()
        self.progress.reset_progress()

    def on_libtestButton_clicked(self, widget):

        def do_start():
            self.switchNotebookPage("output")
            self.startWorking()
            self.uiLock(True)
            self.ui.abortQueue.show()

        def do_stop():
            self.endWorking()
            self.ui.abortQueue.hide()
            self.uiLock(False)
            self.progress.reset_progress()

        def task_bombing():
            if self.abortQueueNow:
                self.abortQueueNow = False
                mytxt = _("Aborting queue tasks.")
                self.ui.abortQueue.hide()
                raise QueueError('QueueError %s' % (mytxt,))

        do_start()

        packages_matched, broken_execs = {},set()
        self.libtest_abort = False
        def exec_task():
            try:
                x, y, z = self.Equo.libraries_test(
                    task_bombing_func = task_bombing)
                packages_matched.update(x)
                broken_execs.update(y)
            except QueueError:
                self.libtest_abort = True

        t = ParallelTask(exec_task)
        t.start()
        while t.isAlive():
            time.sleep(0.2)
            self.gtk_loop()

        if self.do_debug and self.libtest_abort:
            print "on_libtestButton_clicked: scan abort"
        if self.do_debug:
            print "on_libtestButton_clicked: done scanning"

        if self.libtest_abort:
            do_stop()
            okDialog(self.ui.main,_("Libraries test aborted"))
            return

        matches = set()
        for key in packages_matched.keys():
            matches |= packages_matched[key]

        if broken_execs:
            okDialog(self.ui.main,
                _("Some broken packages have not been matched, others are going to be added to the queue."))
        else:
            okDialog(self.ui.main,
                _("All the broken packages are going to be added to the queue"))

        rc = self.add_atoms_to_queue([], matches = matches)
        if rc: self.switchNotebookPage("queue")
        else: self.switchNotebookPage("preferences")

        do_stop()

    def on_color_reset(self, widget):
        # get parent
        parent = widget.get_parent()
        if parent == None: return
        col_button = [x for x in parent.get_children() if \
            isinstance(x,gtk.ColorButton)][0]
        setting = self.colorSettingsReverseMap.get(col_button)
        if setting == None: return
        default_color = SulfurConf.default_colors_config.get(setting)
        col_button.set_color(gtk.gdk.color_parse(default_color))
        self.on_Preferences_toggled(None,True)
        setattr(SulfurConf,setting,default_color)

    def on_ui_color_set(self, widget):
        key = self.colorSettingsReverseMap.get(widget)
        if not hasattr(SulfurConf,key):
            print "WARNING: no %s in SulfurConf" % (key,)
            return
        w_col = widget.get_color().to_string()
        self.on_Preferences_toggled(None,True)
        setattr(SulfurConf,key,w_col)

    def on_pkgSorter_changed(self, widget):
        busyCursor(self.ui.main)
        model = widget.get_model()
        sort_id = widget.get_active()
        if sort_id == -1:
            return
        sort_id_name = self.pkg_sorters_id.get(sort_id)
        sorter = self.avail_pkg_sorters.get(sort_id_name)
        self.pkgView.change_model_injector(sorter)
        self.addPackages()
        normalCursor(self.ui.main)