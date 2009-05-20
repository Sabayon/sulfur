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

from entropy.i18n import _
from entropy.const import *
from entropy.exceptions import *

from sulfur.setup import SulfurConf, cleanMarkupString
from sulfur.package import EntropyPackage, DummyEntropyPackage

class Queue:

    def __init__(self, SulfurApplication):
        self.packages = {}
        self.before = []
        self.keyslotFilter = set()
        self._keyslotFilter = set()
        self.clear()
        self.Entropy = None
        self.etpbase = None
        self.pkgView = None
        self.queueView = None
        self.Sulfur = SulfurApplication
        import dialogs
        self.dialogs = dialogs


    def connect_objects(self, equo_conn, etpbase, pkgView, ui):
        self.Entropy = equo_conn
        self.etpbase = etpbase
        self.pkgView = pkgView
        self.ui = ui

    def clear( self ):
        self.packages.clear()
        self.packages['i'] = []
        self.packages['u'] = []
        self.packages['r'] = []
        self.packages['rr'] = []
        del self.before[:]
        self.keyslotFilter.clear()

    def get( self, action = None ):
        if action == None:
            return self.packages
        else:
            return self.packages[action]

    def total(self):
        size = 0
        for key in self.packages:
            size += len(self.packages[key])
        return size

    def keySlotFiltering(self, queue):

        blocked = []
        for pkg in queue:
            match = pkg.matched_atom
            if type(match[1]) is int: # installed package
                dbconn = self.Entropy.clientDbconn
            else:
                dbconn = self.Entropy.open_repository(match[1])
            keyslot = dbconn.retrieveKeySlot(match[0])
            if keyslot in self.keyslotFilter:
                blocked.append(pkg)
            else:
                self._keyslotFilter.add(keyslot)

        return blocked

    def showKeySlotErrorMessage(self, blocked):

        confirmDialog = self.dialogs.ConfirmationDialog( self.ui.main,
                    list(blocked),
                    top_text = _("Attention"),
                    sub_text = _("There are packages that can't be installed at the same time, thus are blocking your request:"),
                    bottom_text = "",
                    cancel = False
        )
        confirmDialog.run()
        confirmDialog.destroy()

    def checkSystemPackage(self, pkg):
        # check if it's a system package
        valid = self.Entropy.validate_package_removal(pkg.matched_atom[0])
        if not valid:
            pkg.queued = None
        return valid

    def elaborateReinsert(self, to_be_reinserted, idpackages_queued, accept_reinsert):

        new_proposed_idpackages_queue = [x for x in idpackages_queued if x not in to_be_reinserted]
        if not new_proposed_idpackages_queue:
            return idpackages_queued

        # atoms
        atoms = []
        newdepends = set()
        # get depends tree
        if new_proposed_idpackages_queue:
            newdepends = self.Entropy.get_removal_queue(new_proposed_idpackages_queue)

        for idpackage in to_be_reinserted:
            if idpackage not in newdepends:
                mystring = "<span foreground='%s'>%s</span>\n<small><span foreground='%s'>%s</span></small>" % (
                    SulfurConf.color_title,
                    self.Entropy.clientDbconn.retrieveAtom(idpackage),
                    SulfurConf.color_pkgsubtitle,
                    cleanMarkupString(self.Entropy.clientDbconn.retrieveDescription(idpackage)),
                )
                atoms.append(mystring)
        atoms = sorted(atoms)


        ok = True
        if not accept_reinsert and atoms:
            ok = False
            confirmDialog = self.dialogs.ConfirmationDialog( self.ui.main,
                atoms,
                top_text = _("These are the needed packages"),
                sub_text = _("These packages must be removed from the removal queue because they depend on your last selection. Do you agree?"),
                bottom_text = '',
                bottom_data = '',
                simpleList = True
            )
            result = confirmDialog.run()
            if result == -5: # ok
                ok = True
            confirmDialog.destroy()

        if ok:
            return new_proposed_idpackages_queue
        return idpackages_queued

    def elaborateUndoremove(self, matches_to_be_removed, proposed_matches):

        def flatten(d):
            mynew = set()
            [mynew.update(d[x]) for x in d]
            return mynew

        dep_tree, st = self.Entropy.get_required_packages(proposed_matches[:])
        if st != 0: return proposed_matches, False # wtf?
        if 0 in dep_tree: dep_tree.pop(0)
        new_deptree = flatten(dep_tree)

        crying_items = [x for x in matches_to_be_removed if x in new_deptree]
        if not crying_items:
            return proposed_matches, False

        # we need to get a list of packages that must be "undo-removed"
        crying_items = []
        for match in proposed_matches:
            match_tree, rc = self.Entropy.generate_dependency_tree(match, flat = True)
            if rc != 0: return proposed_matches, False # wtf?
            mm = [x for x in matches_to_be_removed if x in match_tree]
            if mm: crying_items.append(match)

        # just to make sure...
        if not crying_items: return proposed_matches, False

        atoms = []
        for idpackage, repoid in crying_items:
            dbconn = self.Entropy.open_repository(repoid)
            mystring = "<span foreground='%s'>%s</span>\n<small><span foreground='%s'>%s</span></small>" % (
                SulfurConf.color_title,
                dbconn.retrieveAtom(idpackage),
                SulfurConf.color_pkgsubtitle,
                cleanMarkupString(dbconn.retrieveDescription(idpackage)),
            )
            atoms.append(mystring)
        atoms = sorted(atoms)

        ok = False
        confirmDialog = self.dialogs.ConfirmationDialog( self.ui.main,
            atoms,
            top_text = _("These packages must be excluded"),
            sub_text = _("These packages must be removed from the queue because they depend on your last selection. Do you agree?"),
            bottom_text = '',
            bottom_data = '',
            simpleList = True
        )
        result = confirmDialog.run()
        if result == -5: # ok
            ok = True
        confirmDialog.destroy()

        if not ok: return proposed_matches, True

        return [x for x in proposed_matches if x not in crying_items], False

    def remove(self, pkgs, accept = False, accept_reinsert = False, always_ask = False):

        self.Sulfur.wait_window.show()

        try:
            if type(pkgs) is not list:
                pkgs = [pkgs]

            action = [pkgs[0].action]
            if action[0] in ("u","i","rr"): # update/install

                action = ["u","i","rr"]
                pkgs_matches = [x.matched_atom for x in pkgs]
                myq = [x.matched_atom for x in self.packages['u']+self.packages['i']+self.packages['rr']]
                xlist = [x for x in myq if x not in pkgs_matches]

                xlist, abort = self.elaborateUndoremove(pkgs_matches, xlist)
                if abort: return -10,0

                self.before = self.packages['u'][:]+self.packages['i'][:]+self.packages['rr'][:]
                for pkg in self.before: pkg.queued = None
                del self.packages['u'][:]
                del self.packages['i'][:]
                del self.packages['rr'][:]

                mybefore = set([x.keyslot for x in self.before])
                self.keyslotFilter -= mybefore

                if xlist:
                    status = self.elaborateInstall(xlist,action,False,accept,always_ask)
                    del self.before[:]
                    return status,0

                del self.before[:]
                return 0,0

            else:

                xlist = [x.matched_atom[0] for x in self.packages[action[0]] if x not in pkgs]
                #toberemoved_idpackages = [x.matched_atom[0] for x in pkgs]
                mydepends = set(self.Entropy.get_removal_queue([x.matched_atom[0] for x in pkgs]))
                mydependencies = set()
                myQA = self.Entropy.QA()
                for pkg in pkgs:
                    mydeps = myQA._get_deep_dependency_list(self.Entropy.clientDbconn, pkg.matched_atom[0])
                    mydependencies |= set([x for x in mydeps if x in xlist])
                # what are in queue?
                mylist = set(xlist)
                mylist -= mydepends
                mylist |= mydependencies
                if mylist:
                    xlist = self.elaborateReinsert(mylist, xlist, accept_reinsert)

                self.before = self.packages[action[0]][:]
                # clean, will be refilled
                for pkg in self.before:
                    pkg.queued = None
                del self.packages[action[0]][:]

                if xlist:

                    status = self.elaborateRemoval(xlist,False,accept,always_ask)
                    if status == -10:
                        del self.packages[action[0]][:]
                        self.packages[action[0]] = self.before[:]

                    del self.before[:]
                    return status,1

                del self.before[:]
                return 0,1
        finally:
            self.Sulfur.wait_window.hide()

    def add(self, pkgs, accept = False, always_ask = False):

        self.Sulfur.wait_window.show()

        try:
            if type(pkgs) is not list:
                pkgs = [pkgs]

            action = [pkgs[0].queued]

            if action[0] in ("u","i","rr"): # update/install

                self._keyslotFilter.clear()
                blocked = self.keySlotFiltering(pkgs)
                if blocked:
                    self.showKeySlotErrorMessage(blocked)
                    return 1,0

                action = ["u","i","rr"]
                myq = [x.matched_atom for x in self.packages['u']+self.packages['i']+self.packages['rr']]
                xlist = myq+[x.matched_atom for x in pkgs if x.matched_atom not in myq]
                status = self.elaborateInstall(xlist,action,False,accept,always_ask)
                if status == 0:
                    self.keyslotFilter |= self._keyslotFilter
                return status,0

            else: # remove

                def myfilter(pkg):
                    if not self.checkSystemPackage(pkg):
                        return False
                    return True

                pkgs = filter(myfilter,pkgs)
                if not pkgs: return -2,1
                myq = [x.matched_atom[0] for x in self.packages['r']]
                pkgs = [x.matched_atom[0] for x in pkgs if x.matched_atom[0] not in myq]+myq
                status = self.elaborateRemoval(pkgs,False,accept,always_ask)
                return status,1

        finally:
            self.Sulfur.wait_window.hide()

    def elaborateMaskedPackages(self, matches):

        matchfilter = set()
        masks = {}
        for match in matches:
            mymasks = self.Entropy.get_masked_packages_tree(match, atoms = False, flat = True, matchfilter = matchfilter)
            masks.update(mymasks)
        # run dialog if found some
        if not masks:
            return 0

        # filter already masked
        mymasks = {}
        for match in masks:
            if match not in self.etpbase.unmaskingPackages:
                mymasks[match] = masks[match]
        if not mymasks:
            return 0

        pkgs = []
        self.etpbase.getRawPackages('masked')
        for match in masks:
            pkg, new = self.etpbase.getPackageItem(match)
            pkgs.append(pkg)

        self.Sulfur.wait_window.hide()
        # save old
        oldmask = self.etpbase.unmaskingPackages.copy()
        maskDialog = self.dialogs.MaskedPackagesDialog(self.Entropy, self.etpbase, self.ui.main, pkgs)
        result = maskDialog.run()
        if result == -5: # ok
            result = 0
        else:
            # discard changes
            self.etpbase.unmaskingPackages = oldmask.copy()
        maskDialog.destroy()
        self.Sulfur.wait_window.show()

        return result

    def elaborateInstall(self, xlist, actions, deep_deps, accept, always_ask = False):

        status = self.elaborateMaskedPackages(xlist)
        if status != 0:
            return status

        (runQueue, removalQueue, status) = self.Entropy.get_install_queue(xlist,False,deep_deps, quiet = True)
        if status == -2: # dependencies not found
            confirmDialog = self.dialogs.ConfirmationDialog( self.ui.main,
                        runQueue,
                        top_text = _("Attention"),
                        sub_text = _("Some dependencies couldn't be found. It can either be because they are masked or because they aren't in any active repository."),
                        bottom_text = "",
                        cancel = False,
                        simpleList = True
            )
            confirmDialog.run()
            confirmDialog.destroy()
            return -10
        elif status == 0:
            # runQueue
            remove_todo = []
            install_todo = []
            if runQueue:
                icache = set([x.matched_atom for x in self.packages[actions[0]]+self.packages[actions[1]]+self.packages[actions[2]]])
                my_icache = set()

                # load packages in cache
                self.etpbase.getRawPackages('installed')
                self.etpbase.getRawPackages('available')
                self.etpbase.getRawPackages('reinstallable')
                self.etpbase.getRawPackages('updates')
                self.etpbase.getRawPackages('masked')

                for matched_atom in runQueue:
                    if matched_atom in my_icache:
                        continue
                    my_icache.add(matched_atom)
                    if matched_atom in icache:
                        continue
                    dep_pkg, new = self.etpbase.getPackageItem(matched_atom)
                    if not dep_pkg:
                        continue
                    install_todo.append(dep_pkg)

            if removalQueue:
                my_rcache = set()
                rcache = set([x.matched_atom[0] for x in self.packages['r']])
                for idpackage in removalQueue:
                    if idpackage in my_rcache:
                        continue
                    my_rcache.add(idpackage)
                    if idpackage in rcache:
                        continue
                    mymatch = (idpackage,0)
                    rem_pkg, new = self.etpbase.getPackageItem(mymatch)
                    if not rem_pkg:
                        continue
                    remove_todo.append(rem_pkg)

            if install_todo or remove_todo:
                ok = True

                mybefore = [x.matched_atom for x in self.before]
                items_before = [x for x in install_todo+remove_todo if x.matched_atom not in mybefore]

                if ((len(items_before) > 1) and (not accept)) or (always_ask):

                    ok = False
                    size = 0
                    for x in install_todo:
                        size += x.disksize
                    for x in remove_todo:
                        size -= x.disksize
                    if size > 0:
                        bottom_text = _("Needed disk space")
                    else:
                        size = abs(size)
                        bottom_text = _("Freed disk space")
                    size = self.Entropy.entropyTools.bytes_into_human(size)
                    confirmDialog = self.dialogs.ConfirmationDialog( self.ui.main,
                        install_todo+remove_todo,
                        top_text = _("These are the packages that would be installed/updated"),
                        bottom_text = bottom_text,
                        bottom_data = size
                    )
                    result = confirmDialog.run()
                    if result == -5: # ok
                        ok = True
                    confirmDialog.destroy()

                if ok:

                    mycache = {
                        'r': [x.matched_atom for x in self.packages['r']],
                        'u': [x.matched_atom for x in self.packages['u']],
                        'rr': [x.matched_atom for x in self.packages['rr']],
                        'i': [x.matched_atom for x in self.packages['i']],
                    }

                    for rem_pkg in remove_todo:
                        rem_pkg.queued = rem_pkg.action
                        if rem_pkg.matched_atom not in mycache['r']:
                            self.packages['r'].append(rem_pkg)
                    for dep_pkg in install_todo:
                        dep_pkg.queued = dep_pkg.action
                        if dep_pkg.matched_atom not in mycache[dep_pkg.action]:
                            self.packages[dep_pkg.action].append(dep_pkg)
                else:
                    return -10

        return status

    def elaborateRemoval(self, mylist, nodeps, accept, always_ask = False):
        if nodeps:
            return 0

        def r_cache_map(x):
            return x.matched_atom[0]

        r_cache = set(map(r_cache_map,self.packages['r']))
        removalQueue = self.Entropy.get_removal_queue(mylist)

        if removalQueue:
            todo = []
            my_rcache = set()
            self.etpbase.getRawPackages('installed')
            for idpackage in removalQueue:
                if idpackage in my_rcache:
                    continue
                my_rcache.add(idpackage)
                if idpackage in r_cache:
                    continue
                rem_pkg, new = self.etpbase.getPackageItem((idpackage,0))
                if not rem_pkg:
                    continue
                todo.append(rem_pkg)
            del r_cache, my_rcache

            if todo:
                ok = True
                items_before = [x for x in todo if x not in self.before]
                if ((len(items_before) > 1) and (not accept)) or (always_ask):
                    ok = False
                    size = 0
                    for x in todo:
                        size += x.disksize
                    if size > 0:
                        bottom_text = _("Freed space")
                    else:
                        size = abs(size)
                        bottom_text = _("Needed space")
                    size = self.Entropy.entropyTools.bytes_into_human(size)
                    confirmDialog = self.dialogs.ConfirmationDialog(
                        self.ui.main,
                        todo,
                        top_text = _("These are the packages that would be removed"),
                        bottom_text = bottom_text,
                        bottom_data = size
                    )
                    result = confirmDialog.run()
                    if result == -5: # ok
                        ok = True
                    confirmDialog.destroy()

                if ok:
                    for rem_pkg in todo:
                        if rem_pkg not in self.packages[rem_pkg.action]:
                            rem_pkg.queued = rem_pkg.action
                            self.packages[rem_pkg.action].append(rem_pkg)
                else:
                    return -10

        return 0

class EntropyPackages:

    def __init__(self, EquoInstance):
        self.Entropy = EquoInstance
        self.filterCallback = None
        self._packages = {}
        self.pkgCache = {}
        self.unmaskingPackages = set()
        self.selected_treeview_item = None
        self.selected_advisory_item = None
        self.queue = None

    def connect_queue(self, queue):
        self.queue = queue

    def clearPackages(self):
        self._packages.clear()
        self.selected_treeview_item = None
        self.selected_advisory_item = None
        self.unmaskingPackages.clear()

    def clearPackagesSingle(self, mask):
        if mask in self._packages:
            del self._packages[mask]
        self.selected_treeview_item = None
        self.selected_advisory_item = None
        self.unmaskingPackages.clear()

    def clearCache(self):
        self.pkgCache.clear()
        self._packages.clear()
        self.selected_treeview_item = None
        self.selected_advisory_item = None

    def populatePackages(self,masks):
        for flt in masks: self.populateSingle(flt)

    def populateSingle(self, mask, force = False):
        if self._packages.has_key(mask) and not force:
            return
        self._packages[mask] = self._getPackages(mask)

    def getPackages(self,flt):
        if flt == 'all': return self.getAllPackages()
        else: return self.doFiltering(self.getRawPackages(flt))

    def getAllPackages(self):
        pkgs = []
        pkgs.extend(self.getPackages('installed'))
        pkgs.extend(self.getPackages('available'))
        pkgs.extend(self.getPackages('reinstallable'))
        pkgs.extend(self.getPackages('updates'))
        return pkgs

    def setFilter(self,fn = None):
        self.filterCallback = fn

    def doFiltering(self,pkgs):
        if self.filterCallback:
            return filter(self.filterCallback,pkgs)
        return pkgs

    def getRawPackages(self,flt):
        self.populateSingle(flt)
        return self._packages[flt]

    def getPackageItem(self, pkgdata):
        new = False
        yp = self.pkgCache.get(pkgdata)
        if yp is None:
            new = True
            pkgset = None
            if isinstance(pkgdata, basestring): # package set
                pkgset = True
            yp = EntropyPackage(pkgdata, pkgset = pkgset)
            self.pkgCache[pkgdata] = yp
        return yp, new

    def _pkg_get_installed(self):

        gp_call = self.getPackageItem
        def fm(idpackage):
            try:
                yp, new = gp_call((idpackage,0))
            except RepositoryError:
                return 0
            yp.action = 'r'
            yp.color = SulfurConf.color_install
            return yp
        return [x for x in map(fm,self.Entropy.clientDbconn.listAllIdpackages(order_by = 'atom')) if type(x) != int]

    def _pkg_get_queued(self):
        data = []
        for qkey in self.queue.packages:
            data.extend(self.queue.packages[qkey])
        return data

    def _pkg_get_available(self):
        gp_call = self.getPackageItem
        # Get the rest of the available packages.
        def fm(match):
            try:
                yp, new = gp_call(match)
            except RepositoryError:
                return 0
            yp.action = 'i'
            return yp
        return [x for x in map(fm,self.Entropy.calculate_available_packages()) if type(x) != int]

    def _pkg_get_updates(self):

        gp_call = self.getPackageItem
        cdb_atomMatch = self.Entropy.clientDbconn.atomMatch
        def fm(match):
            try:
                yp, new = gp_call(match)
            except RepositoryError:
                return 0
            key, slot = yp.keyslot
            installed_match = cdb_atomMatch(key, matchSlot = slot)
            if installed_match[0] != -1: yp.installed_match = installed_match
            yp.action = 'u'
            yp.color = SulfurConf.color_update
            return yp
        updates, remove, fine, spm_fine = self.Entropy.calculate_world_updates()

        # we need to cache these too on getPackageItem
        map(fm, spm_fine)

        return [x for x in map(fm, updates) if type(x) != int]

    def _pkg_get_reinstallable(self):
        def fm(match):
            idpackage, matched = match
            try:
                yp, new = self.getPackageItem(matched)
            except RepositoryError:
                return 0
            yp.installed_match = (idpackage,0)
            yp.action = 'rr'
            yp.color = SulfurConf.color_install
            return yp
        return [x for x in map(fm,self.filterReinstallable(self.Entropy.clientDbconn.listAllPackages(get_scope = True,order_by = 'atom'))) if type(x) != int]

    def _pkg_get_masked(self):
        gp_call = self.getPackageItem
        gmp_action = self.getMaskedPackageAction
        gi_match = self.getInstalledMatch
        def fm(match):
            match, idreason = match
            try:
                yp, new = gp_call(match)
            except RepositoryError:
                return 0
            action = gmp_action(match)
            yp.action = action
            if action == 'rr': # setup reinstallables
                idpackage = gi_match(match)
                if idpackage == None: # wtf!?
                    yp.installed_match = None
                else:
                    yp.installed_match = (idpackage,0)
            yp.masked = idreason
            yp.color = SulfurConf.color_install
            return yp
        return [x for x in map(fm,self.getMaskedPackages()) if type(x) != 0]

    def _pkg_get_user_masked(self):
        masked_objs = self.getPackages("masked")
        return [x for x in masked_objs if x.user_masked]

    def _pkg_get_user_unmasked(self):
        objs = self.getPackages("updates") + self.getPackages("available") + self.getPackages('reinstallable')
        return [x for x in objs if x.user_unmasked]

    def _pkg_get_pkgset_matches_installed_matches(self, set_deps):
        set_matches = []
        set_installed_matches = []
        install_incomplete = False
        remove_incomplete = False
        for set_dep in set_deps:
            if set_dep.startswith(etpConst['packagesetprefix']):
                set_matches.append((set_dep,None,))
                set_installed_matches.append((set_dep,None,))
            else:
                set_match = self.Entropy.atom_match(set_dep)
                if set_match[0] != -1: set_matches.append(set_match)
                else: install_incomplete = True
                set_installed_match = self.Entropy.clientDbconn.atomMatch(set_dep)
                if set_match[0] != -1: set_installed_matches.append(set_installed_match)
                else: remove_incomplete = True
        return set_matches, set_installed_matches, install_incomplete, remove_incomplete

    def _pkg_get_pkgset_set_from_desc(self, set_from):
        my_set_from = _('Set from')
        set_from_desc = _('Unknown')
        if set_from in self.Entropy.validRepositories:
            avail_repos = self.Entropy.SystemSettings['repositories']['available']
            set_from_desc = avail_repos[set_from]['description']
        elif set_from == etpConst['userpackagesetsid']:
            set_from_desc = _("User configuration")
        return "%s: %s" % (my_set_from,set_from_desc,)

    def _pkg_get_pkgsets(self):

        gp_call = self.getPackageItem

        # make sure updates will be marked as such
        self.getPackages("updates")
        # make sure unavailable packages are marked as such
        self.getPackages("available")
        # make sure reinstallable packages will be marked as such
        self.getPackages("reinstallable")

        objects = []

        pkgsets = self.getPackageSets()
        for set_from, set_name, set_deps in pkgsets:

            set_matches, set_installed_matches, install_incomplete, remove_incomplete = self._pkg_get_pkgset_matches_installed_matches(set_deps)
            if not (set_matches and set_installed_matches): continue
            cat_namedesc = self._pkg_get_pkgset_set_from_desc(set_from)
            set_objects = []

            def update_yp(yp):
                yp.color = SulfurConf.color_install
                yp.set_cat_namedesc = cat_namedesc
                yp.set_names.add(set_name)
                yp.set_from = set_from
                yp.set_matches = set_matches
                yp.set_installed_matches = set_installed_matches

            myobjs = []
            broken = False
            for match in set_matches:
                # set dependency
                if match[1] == None:
                    yp, new = gp_call(match[0])
                    yp.action = "i"
                else:
                    try:
                        yp, new = gp_call(match)
                    except RepositoryError:
                        broken = True
                        break
                myobjs.append(yp)
            if broken: continue

            for yp in myobjs: yp.set_names.clear()
            for yp in myobjs: update_yp(yp)
            objects += myobjs

        return objects

    def _pkg_get_fake_updates(self):
        # load a pixmap inside the treeview
        msg2 = _("Try clicking the %s button in the %s page") % ( _("Update Repositories"),_("Repository Selection"),)

        msg = "<big><b><span foreground='%s'>%s</span></b></big>\n%s.\n%s" % (
            SulfurConf.color_title,
            _('No updates available'),
            _("It seems that your system is already up-to-date. Good!"),
            msg2,
        )
        myobj = DummyEntropyPackage(namedesc = msg, dummy_type = SulfurConf.dummy_empty)
        return [myobj]

    def _getPackages(self,mask):

        calls_dict = {
            "installed": self._pkg_get_installed,
            "queued": self._pkg_get_queued,
            "available": self._pkg_get_available,
            "updates": self._pkg_get_updates,
            "reinstallable": self._pkg_get_reinstallable,
            "masked": self._pkg_get_masked,
            "user_masked": self._pkg_get_user_masked,
            "user_unmasked": self._pkg_get_user_unmasked,
            "pkgsets": self._pkg_get_pkgsets,
            "fake_updates": self._pkg_get_fake_updates,
        }
        return calls_dict.get(mask)()


    def isReinstallable(self, atom, slot, revision):
        for repoid in self.Entropy.validRepositories:
            dbconn = self.Entropy.open_repository(repoid)
            idpackage, idreason = dbconn.isPackageScopeAvailable(atom, slot, revision)
            if idpackage == -1:
                continue
            return (repoid,idpackage,)
        return None

    def getPackageSets(self):
        return self.Entropy.package_set_list()

    def getMaskedPackages(self):
        maskdata = []

        for repoid in self.Entropy.validRepositories:
            dbconn = self.Entropy.open_repository(repoid)
            repodata = dbconn.listAllIdpackages(order_by = 'atom')
            def fm(idpackage):
                idpackage_filtered, idreason = dbconn.idpackageValidator(idpackage)
                if idpackage_filtered == -1:
                    return ((idpackage,repoid,),idreason)
                return 0
            maskdata += [x for x in map(fm,repodata) if type(x) != int]

        return maskdata

    def getMaskedPackageAction(self, match):
        action = self.Entropy.get_package_action(match)
        if action in [2,-1]:
            return 'u'
        elif action == 1:
            return 'i'
        else:
            return 'rr'

    def getInstalledMatch(self, match):
        dbconn = self.Entropy.open_repository(match[1])
        try:
            atom, slot, revision = dbconn.getStrictScopeData(match[0])
        except TypeError:
            return None
        idpackage, idresult = \
            self.Entropy.clientDbconn.isPackageScopeAvailable(atom, slot,
                revision)
        if idpackage == -1:
            return None
        return idpackage

    def filterReinstallable(self, client_scope_data):
        clientdata = {}
        for idpackage, atom, slot, revision in client_scope_data:
            clientdata[(atom,slot,revision,)] = idpackage
        del client_scope_data

        matched_data = set()
        for repoid in self.Entropy.validRepositories:
            dbconn = self.Entropy.open_repository(repoid)
            repodata = dbconn.listAllPackages(get_scope = True)
            mydata = {}
            for idpackage, atom, slot, revision in repodata:
                mydata[(atom, slot, revision)] = idpackage

            def fm_pre(item):
                if item in mydata:
                    return True
                return False

            def fm(item):
                idpackage = mydata[item]
                idpackage, idreason = dbconn.idpackageValidator(idpackage)
                if idpackage != -1:
                    return (clientdata[item],(mydata[item],repoid,))
                return 0

            matched_data |= set([x for x in map(fm,filter(fm_pre,clientdata)) \
                if type(x) != int])

        return matched_data
