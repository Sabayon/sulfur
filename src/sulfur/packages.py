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
import gobject

from entropy.i18n import _
from entropy.const import etpConst, const_debug_write, const_get_stringtype
from entropy.exceptions import DependenciesNotFound, RepositoryError, \
    SystemDatabaseError, SystemDatabaseError, DependenciesNotRemovable, \
    DependenciesCollision
from entropy.output import print_generic
from entropy.graph import Graph
from entropy.db.exceptions import OperationalError
from entropy.client.interfaces.db import InstalledPackagesRepository
import entropy.tools

from sulfur.setup import SulfurConf, cleanMarkupString, const
from sulfur.package import EntropyPackage, DummyEntropyPackage
from sulfur.event import SulfurSignals

class Queue:

    def __init__(self, SulfurApplication):
        self.packages = {}
        self.before = []
        self.keyslotFilter = set()
        self._keyslotFilter = set()
        self.Entropy = None
        self.etpbase = None
        self.pkgView = None
        self.ui = None
        self.Sulfur = SulfurApplication
        from . import dialogs
        self.dialogs = dialogs
        self.clear()

    def connect_objects(self, equo_conn, etpbase, pkgView, ui):
        self.Entropy = equo_conn
        self.etpbase = etpbase
        self.pkgView = pkgView
        self.ui = ui

    def clear(self):
        self.packages.clear()
        self.packages['i'] = []
        self.packages['u'] = []
        self.packages['r'] = []
        self.packages['rr'] = []
        self.packages['d'] = []
        del self.before[:]
        self.keyslotFilter.clear()

    def get(self, action = None):
        if action is None:
            return self.packages
        return self.packages[action]

    def total(self):
        size = 0
        for key in self.packages:
            size += len(self.packages[key])
        return size

    def key_slot_filtering(self, queue):

        blocked = []
        for pkg in queue:
            match = pkg.matched_atom
            if isinstance(match[1], int): # installed package
                dbconn = self.Entropy.installed_repository()
            else:
                dbconn = self.Entropy.open_repository(match[1])
            keyslot = dbconn.retrieveKeySlot(match[0])
            if keyslot in self.keyslotFilter:
                blocked.append(pkg)
            else:
                self._keyslotFilter.add(keyslot)

        return blocked

    def show_key_slot_error_message(self, blocked):

        confirmDialog = self.dialogs.ConfirmationDialog( self.ui.main,
            list(blocked),
            top_text = _("Attention"),
            sub_text = _("There are packages that can't be installed at the same time, thus are blocking your request:"),
            bottom_text = "",
            cancel = False
        )
        confirmDialog.run()
        confirmDialog.destroy()

    def check_system_package(self, pkg):
        # check if it's a system package
        valid = self.Entropy.validate_package_removal(pkg.matched_atom[0])
        if not valid:
            pkg.queued = None
        return valid

    def elaborate_reinsert(self, to_be_reinserted, idpackages_queued,
        accept_reinsert):

        new_proposed_idpackages_queue = [x for x in idpackages_queued if x \
            not in to_be_reinserted]
        if not new_proposed_idpackages_queue:
            return idpackages_queued

        # atoms
        atoms = []
        newdepends = set()
        # get depends tree
        if new_proposed_idpackages_queue:
            newdepends = self.Entropy.get_removal_queue(
                new_proposed_idpackages_queue)

        for idpackage in to_be_reinserted:
            if idpackage not in newdepends:
                mystring = "<span foreground='%s'>%s</span>\n<small><span foreground='%s'>%s</span></small>" % (
                    SulfurConf.color_title,
                    self.Entropy.installed_repository().retrieveAtom(idpackage),
                    SulfurConf.color_pkgsubtitle,
                    cleanMarkupString(
                        self.Entropy.installed_repository().retrieveDescription(idpackage)),
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

    def elaborate_undo_remove(self, matches_to_be_removed, proposed_matches):

        def flatten(d):
            mynew = set()
            [mynew.update(d[x]) for x in d]
            return mynew

        try:
            install, remove = self.Entropy.get_install_queue(
                proposed_matches, False, False)
        except (DependenciesNotFound, DependenciesCollision):
            return proposed_matches, False

        crying_items = [x for x in matches_to_be_removed if x in install]
        if not crying_items:
            return proposed_matches, False

        # we need to get a list of packages that must be "undo-removed"
        crying_items = []

        for package_match in proposed_matches:

            try:
                install, remove = self.Entropy.get_install_queue(
                    [package_match], False, False)
            except (DependenciesNotFound, DependenciesCollision):
                return proposed_matches, False # wtf?

            if [x for x in matches_to_be_removed if x in install]:
                crying_items.append(package_match)

        # just to make sure...
        if not crying_items:
            return proposed_matches, False

        atoms = []
        for package_id, repo_id in crying_items:
            pkg_repo = self.Entropy.open_repository(repo_id)
            mystring = "<span foreground='%s'>%s</span>\n<small><span foreground='%s'>%s</span></small>" % (
                SulfurConf.color_title,
                pkg_repo.retrieveAtom(package_id),
                SulfurConf.color_pkgsubtitle,
                cleanMarkupString(pkg_repo.retrieveDescription(package_id)),
            )
            atoms.append(mystring)
        atoms = sorted(atoms)

        ok = False
        confirmDialog = self.dialogs.ConfirmationDialog(
            self.ui.main,
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

        if not ok:
            return proposed_matches, True

        return [x for x in proposed_matches if x not in crying_items], False

    def remove(self, pkgs, accept = False, accept_reinsert = False,
        always_ask = False):

        # make sure to not taint list object passed
        q_pkgs = pkgs[:]

        try:

            action = [q_pkgs[0].action]
            if action[0] in ("u", "i", "rr", "d"): # update/install/downgrade

                action = ["u", "i", "rr", "d"]
                pkgs_matches = [x.matched_atom for x in q_pkgs]
                myq = [x.matched_atom for x in self.packages['u'] + \
                    self.packages['i'] + self.packages['rr'] + self.packages['d']]
                xlist = [x for x in myq if x not in pkgs_matches]

                xlist, abort = self.elaborate_undo_remove(pkgs_matches, xlist)
                if abort:
                    return -10, 0

                self.before = self.packages['u'][:] + self.packages['i'][:] + \
                    self.packages['rr'][:] + self.packages['d'][:]
                for pkg in self.before: pkg.queued = None
                del self.packages['u'][:]
                del self.packages['i'][:]
                del self.packages['rr'][:]
                del self.packages['d'][:]

                mybefore = set([x.keyslot for x in self.before])
                self.keyslotFilter -= mybefore

                if xlist:
                    status = self.elaborate_install(xlist, action, False,
                        accept, always_ask)
                    del self.before[:]
                    return status, 0

                del self.before[:]
                return 0, 0

            else:

                xlist = [x.matched_atom[0] for x in \
                    self.packages[action[0]] if x not in q_pkgs]
                #toberemoved_idpackages = [x.matched_atom[0] for x in q_pkgs]
                try:
                    mydepends = set(self.Entropy.get_removal_queue(
                        [x.matched_atom[0] for x in q_pkgs]))
                except DependenciesNotRemovable as err:
                    self._show_dependencies_not_removable_err(err)
                    return -10, 0
                mydependencies = set()
                myQA = self.Entropy.QA()
                cl_repo_name = etpConst.get(
                    'clientdbid',
                    getattr(InstalledPackagesRepository, "NAME", None))
                for pkg in q_pkgs:
                    pkg_match = (pkg.matched_atom[0], cl_repo_name)
                    mydeps = myQA.get_deep_dependency_list(self.Entropy,
                        pkg_match, match_repo = (cl_repo_name,))
                    mydependencies |= set([x for x, y in mydeps if x in xlist])
                # what are in queue?
                mylist = set(xlist)
                mylist -= mydepends
                mylist |= mydependencies
                if mylist:
                    xlist = self.elaborate_reinsert(mylist, xlist,
                        accept_reinsert)

                self.before = self.packages[action[0]][:]
                # clean, will be refilled
                for pkg in self.before:
                    pkg.queued = None
                del self.packages[action[0]][:]

                if xlist:

                    status = self.elaborate_removal(xlist, False, accept, always_ask)
                    if status == -10:
                        del self.packages[action[0]][:]
                        self.packages[action[0]] = self.before[:]

                    del self.before[:]
                    return status, 1

                del self.before[:]
                return 0, 1
        finally:
            items = [x for x in list(self.packages.values()) if x]
            if items:
                SulfurSignals.emit('install_queue_filled')
            else:
                SulfurSignals.emit('install_queue_empty')
            SulfurSignals.emit('install_queue_changed', len(items))

    def add(self, pkgs, accept = False, always_ask = False):

        # make sure to not taint list object passed
        q_pkgs = pkgs[:]

        try:

            action = [q_pkgs[0].queued]

            if action[0] in ("u", "i", "rr", "d"): # update/install

                self._keyslotFilter.clear()
                blocked = self.key_slot_filtering(q_pkgs)
                if blocked:
                    self.show_key_slot_error_message(blocked)
                    return 1, 0

                action = ["u", "i", "rr", "d"]
                myq = [x.matched_atom for x in self.packages['u'] + \
                    self.packages['i'] + self.packages['rr'] + self.packages['d']]
                xlist = myq+[x.matched_atom for x in q_pkgs if \
                    x.matched_atom not in myq]
                status = self.elaborate_install(xlist, action, False, accept,
                    always_ask)
                if status == 0:
                    self.keyslotFilter |= self._keyslotFilter
                return status, 0

            else: # remove

                def myfilter(pkg):
                    if not self.check_system_package(pkg):
                        return False
                    return True

                q_pkgs = list(filter(myfilter, q_pkgs))
                if not q_pkgs:
                    return -2, 1
                myq = [x.matched_atom[0] for x in self.packages['r']]
                q_pkgs = [x.matched_atom[0] for x in q_pkgs if \
                    x.matched_atom[0] not in myq] + myq
                status = self.elaborate_removal(q_pkgs, False, accept,
                    always_ask)
                return status, 1

        finally:
            items_len = len([x for x in list(self.packages.values()) if x])
            if items_len:
                SulfurSignals.emit('install_queue_filled')
            else:
                SulfurSignals.emit('install_queue_empty')
            SulfurSignals.emit('install_queue_changed', items_len)

    def elaborate_masked_packages(self, matches):

        masks = self.Entropy.get_masked_packages(matches)
        # filter already masked
        mymasks = {}
        for match in masks:
            if match not in self.etpbase.unmaskingPackages:
                mymasks[match] = masks[match]
        if not mymasks:
            return 0

        pkgs = []
        self.etpbase.get_raw_groups('masked')
        for match in masks:
            pkg, new = self.etpbase.get_package_item(match)
            pkgs.append(pkg)

        # save old
        oldmask = self.etpbase.unmaskingPackages.copy()
        maskDialog = self.dialogs.MaskedPackagesDialog(self.Entropy,
            self.etpbase, self.ui.main, pkgs)
        result = maskDialog.run()
        if result == -5: # ok
            result = 0
        else:
            # discard changes
            self.etpbase.unmaskingPackages = oldmask.copy()
        maskDialog.destroy()

        return result

    def __get_disksize(self, pkg, force_debug):
        cl_id = etpConst['system_settings_plugins_ids']['client_plugin']
        misc_data = self.Entropy.Settings()[cl_id]['misc']
        if misc_data['splitdebug'] or force_debug:
            return pkg.disksize_debug
        return pkg.disksize

    def elaborate_install(self, xlist, actions, deep_deps, accept,
        always_ask = False):

        status = self.elaborate_masked_packages(xlist)
        if status != 0:
            return status

        try:
            runQueue, removalQueue = self.Entropy.get_install_queue(
                xlist, False, deep_deps,
                relaxed = (SulfurConf.relaxed_deps == 1), quiet = True)
        except DependenciesNotFound as exc:
            run_deps = sorted(exc.value)
            confirmDialog = self.dialogs.ConfirmationDialog(
                self.ui.main,
                run_deps,
                top_text = _("Attention"),
                sub_text = _("Some dependencies couldn't be found. It can either be because they are masked or because they aren't in any active repository."),
                bottom_text = "",
                cancel = False,
                simpleList = True
            )
            confirmDialog.run()
            confirmDialog.destroy()
            return -10
        except DependenciesCollision as exc:
            col_deps = exc.value
            pkgs_list = []
            for pkg_matches in col_deps:
                for pkg_id, pkg_repo in pkg_matches:
                    repo_db = self.Entropy.open_repository(pkg_repo)
                    pkg_atom = repo_db.retrieveAtom(pkg_id)
                    keyslot = repo_db.retrieveKeySlotAggregated(pkg_id)
                    pkg_string = "%s (%s)" % (pkg_atom, keyslot)
                    pkgs_list.append(pkg_string)
            confirmDialog = self.dialogs.ConfirmationDialog(
                self.ui.main,
                pkgs_list,
                top_text = _("Attention"),
                sub_text = _("Conflicting packages were pulled in, in the same key and slot"),
                bottom_text = _("Please mask packages that are causing the issue"),
                cancel = False,
                simpleList = True
            )
            confirmDialog.run()
            confirmDialog.destroy()
            return -10

        # runQueue
        remove_todo = []
        install_todo = []
        if runQueue:
            icache = set([x.matched_atom for x in \
                self.packages[actions[0]] + self.packages[actions[1]] + \
                self.packages[actions[2]]])
            my_icache = set()

            # load packages in cache
            self.etpbase.get_raw_groups('installed')
            self.etpbase.get_raw_groups('available')
            self.etpbase.get_raw_groups('reinstallable')
            self.etpbase.get_raw_groups('updates')
            self.etpbase.get_raw_groups('unfiltered_updates')
            self.etpbase.get_raw_groups('masked')
            self.etpbase.get_raw_groups('downgrade')

            for matched_atom in runQueue:
                if matched_atom in my_icache:
                    continue
                my_icache.add(matched_atom)
                if matched_atom in icache:
                    continue
                dep_pkg, new = self.etpbase.get_package_item(matched_atom)
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
                mymatch = (idpackage, 0)
                rem_pkg, new = self.etpbase.get_package_item(mymatch)
                if not rem_pkg:
                    continue
                remove_todo.append(rem_pkg)

        if install_todo or remove_todo:
            ok = True

            mybefore = [x.matched_atom for x in self.before]
            items_before = [x for x in install_todo+remove_todo if \
                x.matched_atom not in mybefore]

            if ((len(items_before) > 1) and (not accept)) or (always_ask):

                ok = False
                size = 0
                for x in install_todo:
                    size += self.__get_disksize(x, False)
                for x in remove_todo:
                    size -= self.__get_disksize(x, False)
                if size > 0:
                    bottom_text = _("Needed disk space")
                else:
                    size = abs(size)
                    bottom_text = _("Freed disk space")
                size = entropy.tools.bytes_into_human(size)
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
                    'd': [x.matched_atom for x in self.packages['d']],
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

        return 0

    def _show_dependencies_not_removable_err(self, err):
        c_repo = self.Entropy.installed_repository()
        non_rm_pkg = sorted([c_repo.retrieveAtom(x[0]) for x in err.value],
            key = lambda x: c_repo.retrieveAtom(x))
        confirmDialog = self.dialogs.ConfirmationDialog(self.ui.main,
            non_rm_pkg,
            top_text = _("Cannot remove packages"),
            sub_text = _("Some dependencies couldn't be removed because they are vital."),
            bottom_text = "",
            cancel = False,
            simpleList = True
        )
        confirmDialog.run()
        confirmDialog.destroy()

    def elaborate_removal(self, mylist, nodeps, accept, always_ask = False):
        if nodeps:
            return 0

        def r_cache_map(x):
            return x.matched_atom[0]

        r_cache = set(map(r_cache_map, self.packages['r']))
        try:
            removalQueue = self.Entropy.get_removal_queue(mylist)
        except DependenciesNotRemovable as err:
            self._show_dependencies_not_removable_err(err)
            return -10

        a_cache = []

        if removalQueue:
            todo = []
            my_rcache = set()
            self.etpbase.get_raw_groups('installed')
            for idpackage in removalQueue:
                if idpackage in my_rcache:
                    continue
                my_rcache.add(idpackage)
                if idpackage in r_cache:
                    continue
                rem_pkg, new = self.etpbase.get_package_item((idpackage, 0))
                if not rem_pkg:
                    continue

                # there can be pkgs not marked for removal, mark them
                if rem_pkg.action is None:
                    # set to "r"
                    rem_pkg.action = "r"
                    a_cache.append(rem_pkg)

                todo.append(rem_pkg)

            if todo:
                ok = True
                items_before = [x for x in todo if x not in self.before]
                if ((len(items_before) > 1) and (not accept)) or (always_ask):
                    ok = False
                    size = 0
                    for x in todo:
                        size += self.__get_disksize(x, True)
                    if size > 0:
                        bottom_text = _("Freed space")
                    else:
                        size = abs(size)
                        bottom_text = _("Needed space")
                    size = entropy.tools.bytes_into_human(size)
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
                    # restore previous removal state
                    for rem_pkg in a_cache:
                        rem_pkg.action = None
                    return -10

        return 0

class EntropyPackages:

    def __init__(self, EquoInstance):
        self.Entropy = EquoInstance
        self._filter_callback = None
        self._search_callback = None
        self._packages = {}
        self._pkg_cache = {}
        self.unmaskingPackages = set()
        self.queue = None
        self._non_cached_groups = ("queued", "search",)

    def connect_queue(self, queue):
        self.queue = queue

    def clear_groups(self):
        self._packages.clear()
        self.unmaskingPackages.clear()

    def clear_single_group(self, mask):
        if mask in self._packages:
            del self._packages[mask]
        self.unmaskingPackages.clear()

    def clear_cache(self):
        self._pkg_cache.clear()
        self._packages.clear()

    def is_cached(self, group):
        return group in self._packages

    def populate_single_group(self, mask, force = False):
        if mask in self._packages and not force and mask not in \
            self._non_cached_groups:
            return
        if const.debug:
            t1 = time.time()
        self._packages[mask] = self._get_groups(mask)
        if const.debug:
            const_debug_write(__name__,
                "populate_single_group: generated group content for %s in %s" % (
                    mask, time.time() - t1,))

    def get_groups(self, flt):
        if flt in ['queued', 'glsa_metadata']:
            return self.get_raw_groups(flt)
        return self.do_filtering(self.get_raw_groups(flt))

    def set_filter(self, fn = None):
        self._filter_callback = fn

    def set_search(self, fn, keyword):
        if fn is None:
            self._search_callback = None
        else:
            self._search_callback = (fn, keyword)

    def get_search(self):
        return self._search_callback

    def do_filtering(self, pkgs):
        if self._filter_callback:
            return list(filter(self._filter_callback, pkgs))
        return pkgs

    def get_raw_groups(self, flt):
        if const.debug:
            t1 = time.time()
        self.populate_single_group(flt)
        if const.debug:
            const_debug_write(__name__,
                "get_raw_groups: generated group content for %s in %s" % (
                    flt, time.time() - t1,))
        return self._packages[flt]

    def get_package_item(self, pkgdata):
        new = False
        yp = self._pkg_cache.get(pkgdata)
        if yp is None:
            new = True
            pkgset = None
            if isinstance(pkgdata, const_get_stringtype()): # package set
                pkgset = True
            yp = EntropyPackage(pkgdata, pkgset = pkgset)
            self._pkg_cache[pkgdata] = yp
        return yp, new

    def __inst_pkg_setup(self, idpackage):
        try:
            yp, new = self.get_package_item((idpackage, 0))
        except RepositoryError:
            return None
        yp.action = 'r'
        yp.installed_match = (idpackage, 0,)
        yp.color = SulfurConf.color_install
        return yp

    def _pkg_get_syspkg_orphans(self):
        return self._pkg_get_orphans(get_syspkgs = True)

    def _pkg_get_unavailable_orphans(self):
        return self._pkg_get_orphans(get_unavailable = False)

    def _pkg_get_orphans(self, get_syspkgs = False, get_unavailable = False):

        # make sure we have these configured
        self.get_groups("installed")
        self.get_groups("reinstallable")

        with self.Entropy.Cacher():
            outcome = self.Entropy.calculate_updates(
                critical_updates = False)
            if isinstance(outcome, dict):
                updates, remove, fine, spm_fine = outcome['update'], \
                    outcome['remove'], outcome['fine'], outcome['spm_fine']
            else:
                updates, remove, fine, spm_fine = outcome

        # verify that client database idpackage still exist,
        # validate here before passing removePackage() wrong info
        remove = [x for x in remove if \
            self.Entropy.installed_repository().isPackageIdAvailable(x)]
        # Filter out packages installed from unavailable repositories, this is
        # mainly required to allow 3rd party packages installation without
        # erroneously inform user about unavailability.
        unavail_pkgs = [x for x in remove if \
            self.Entropy.installed_repository().getInstalledPackageRepository(x) \
            not in self.Entropy.repositories()]
        remove = [x for x in remove if x not in unavail_pkgs]
        # drop system packages for automatic removal, user has to do it manually.
        system_unavail_pkgs = [x for x in remove if \
            not self.Entropy.validate_package_removal(x)]
        remove = [x for x in remove if x not in system_unavail_pkgs]

        if get_syspkgs:
            return [x for x in map(self.__inst_pkg_setup, unavail_pkgs) if \
                x is not None]
        elif get_unavailable:
            return [x for x in map(self.__inst_pkg_setup, system_unavail_pkgs) \
                if x is not None]
        else:
            return [x for x in map(self.__inst_pkg_setup, remove) if \
                x is not None]

    def _pkg_get_installed(self):
        return [x for x in map(self.__inst_pkg_setup,
            self.Entropy.installed_repository().listAllPackageIds(order_by = 'atom')) if \
                x is not None]

    def _pkg_get_queued(self):
        data = []
        for mylist in list(self.queue.packages.values()):
            data.extend(mylist)
        return data

    def _pkg_get_all(self):

        keys = ['installed', 'available', 'masked', 'updates']
        allpkgs_dict = {}
        for key in keys:
            allpkgs_dict.update(dict((x.matched_atom, x) for x in \
                self.get_raw_groups(key)))
        allpkgs_set = set(allpkgs_dict)

        # filter duplicates, drop installed pkgs if they are already
        # provided as updates or available
        allpkgs_set -= set(x.matched_atom for x in \
            self.get_raw_groups('installed'))
        allpkgs_set -= set(x.installed_match for x in \
            self.get_raw_groups('updates') + \
            self.get_raw_groups('available') + \
            self.get_raw_groups('masked'))

        return [allpkgs_dict[x] for x in allpkgs_set]

    def _pkg_get_available(self):
        gp_call = self.get_package_item
        # Get the rest of the available packages.
        def fm(match):
            try:
                yp, new = gp_call(match)
            except RepositoryError:
                return None
            yp.action = 'i'
            return yp
        with self.Entropy.Cacher():
            return [x for x in map(fm, self.Entropy.calculate_available_packages()) \
                if x is not None]

    def _pkg_get_updates_raw(self):
        return self._pkg_get_updates(critical_updates = False)

    def _pkg_get_updates(self, critical_updates = True, orphans = False):

        gp_call = self.get_package_item
        cdb_atomMatch = self.Entropy.installed_repository().atomMatch

        def setup_item(match):
            try:
                yp, new = gp_call(match)
            except RepositoryError:
                return None
            try:
                key, slot = yp.keyslot
            except OperationalError:
                return None
            installed_match = cdb_atomMatch(key, matchSlot = slot)
            if installed_match[0] != -1:
                yp.installed_match = installed_match
            yp.action = 'u'
            yp.color = SulfurConf.color_update
            return yp

        try:
            with self.Entropy.Cacher():
                outcome = self.Entropy.calculate_updates(
                    critical_updates = critical_updates)

            if isinstance(outcome, dict):
                updates, remove, fine, spm_fine = outcome['update'], \
                    outcome['remove'], outcome['fine'], outcome['spm_fine']
            else:
                updates, remove, fine, spm_fine = outcome

        except SystemDatabaseError:
            # broken client db
            return []

        for match in spm_fine:
            setup_item(match)

        pkg_updates = []
        for match in updates:
            pkg = setup_item(match)
            if pkg is None:
                continue
            pkg_updates.append(pkg)

        # emit signal about updates available
        SulfurSignals.emit("updates_available", len(pkg_updates))

        return pkg_updates

    def _pkg_get_downgrade(self):

        if const.debug:
            t1 = time.time()

        already_in = set((x.matched_atom for x in self.get_raw_groups("unfiltered_updates")))
        already_in |= set((x.matched_atom for x in self.get_raw_groups("available")))
        already_in |= set((x.matched_atom for x in self.get_raw_groups("reinstallable")))
        already_in |= set((x.matched_atom for x in self.get_raw_groups("masked")))
        already_in |= set((x.matched_atom for x in self.get_raw_groups("user_masked")))
        already_in |= set((x.matched_atom for x in self.get_raw_groups("user_unmasked")))

        if const.debug:
            const_debug_write(__name__,
                "_pkg_get_downgrade: created already_in in %s" % (
                    time.time() - t1,))
            t1 = time.time()

        matches = set()
        for repo in self.Entropy.repositories():
            dbconn = self.Entropy.open_repository(repo)
            try:
                idpackages = dbconn.listAllPackageIds()
            except OperationalError:
                continue
            matches |= set(((x, repo) for x in idpackages if (x, repo) not in
                already_in))

        if const.debug:
            const_debug_write(__name__,
                "_pkg_get_downgrade: first iteration in %s" % (
                    time.time() - t1,))
            t1 = time.time()

        final_matches = []
        for match in matches:
            try:
                yp, new = self.get_package_item(match)
            except RepositoryError:
                continue
            if yp.keyslot is None: # broken entry?
                continue
            key, slot = yp.keyslot
            installed_match = self.Entropy.installed_repository().atomMatch(key,
                matchSlot = slot)
            if installed_match[0] != -1:
                yp.installed_match = installed_match
            yp.action = 'd'
            yp.is_downgrade = True
            yp.color = SulfurConf.color_remove
            final_matches.append(yp)

        if const.debug:
            const_debug_write(__name__,
                "_pkg_get_downgrade: second iteration in %s" % (
                    time.time() - t1,))

        return final_matches

    def _pkg_get_reinstallable(self):
        def fm(match):
            idpackage, matched = match
            try:
                yp, new = self.get_package_item(matched)
            except RepositoryError:
                return None
            # added for reliability
            yp.installed_match = (idpackage, 0)
            yp.action = 'rr'
            yp.color = SulfurConf.color_install
            return yp
        filtered = self.filter_reinstallable(
            self.Entropy.installed_repository().listAllPackages(get_scope = True))
        return [x for x in map(fm, filtered) if x is not None]

    def _pkg_get_masked(self):

        gmp_action = self.get_masked_package_action
        gi_match = self.get_installed_idpackage
        def fm(match):

            match, idreason = match
            try:
                yp, new = self.get_package_item(match)
            except RepositoryError:
                return None

            if yp.action is None:
                pkg_id, pkg_repo = match
                # make sure that package is available before calling
                # get_masked_package_action, otherwise
                # Entropy.get_package_action will raise TypeError at
                # retrieveKeySlot
                pkg_db = self.Entropy.open_repository(pkg_repo)
                yp.action = gmp_action(match)
                if yp.action == 'rr': # setup reinstallables
                    idpackage = gi_match(match)
                    if idpackage is None: # wtf!?
                        yp.installed_match = None
                    else:
                        yp.installed_match = (idpackage, 0)

                yp.masked = idreason
                yp.color = SulfurConf.color_install

            return yp

        return [x for x in map(fm, self.Entropy.calculate_masked_packages()) \
            if x is not None]

    def _pkg_get_user_masked(self):
        masked_objs = self.get_raw_groups("masked")
        return [x for x in masked_objs if x.user_masked]

    def _pkg_get_user_unmasked(self):
        objs = self.get_raw_groups("unfiltered_updates") + self.get_raw_groups("available") + \
            self.get_raw_groups('reinstallable')# + self.get_raw_groups("downgrade")
        return [x for x in objs if x.user_unmasked]

    def _pkg_get_pkgset_matches_installed_matches(self, set_deps):

        set_matches = []
        set_installed_matches = []
        install_incomplete = False
        remove_incomplete = False
        pkgset_pfx = etpConst['packagesetprefix']
        for set_dep in set_deps:
            if set_dep.startswith(pkgset_pfx):
                set_matches.append((set_dep, None,))
                set_installed_matches.append((set_dep, None,))
            else:
                set_match = self.Entropy.atom_match(set_dep)
                if set_match[0] != -1:
                    set_matches.append(set_match)
                else: install_incomplete = True
                set_installed_match = self.Entropy.installed_repository().atomMatch(set_dep)
                if set_match[0] != -1:
                    set_installed_matches.append(set_installed_match)
                else: remove_incomplete = True

        return set_matches, set_installed_matches, install_incomplete, remove_incomplete

    def _pkg_get_pkgset_set_from_desc(self, set_from):
        my_set_from = _('Set from')
        set_from_desc = _('Unknown')
        if set_from in self.Entropy.repositories():
            avail_repos = self.Entropy.Settings()['repositories']['available']
            set_from_desc = avail_repos[set_from]['description']
        elif set_from == etpConst['userpackagesetsid']:
            set_from_desc = _("User configuration")
        return "%s: %s" % (my_set_from, set_from_desc,)

    def _pkg_get_pkgsets(self):

        gp_call = self.get_package_item

        self.get_groups("updates")
        self.get_groups("unfiltered_updates")
        self.get_groups("available")
        self.get_groups("reinstallable")
        self.get_groups("downgrade")
        self.get_groups("masked")
        self.get_groups("user_masked")
        self.get_groups("user_unmasked")

        objects = []

        pkgsets = self.get_package_sets()
        for set_from, set_name, set_deps in pkgsets:

            set_matches, set_installed_matches, install_incomplete, \
                remove_incomplete = \
                self._pkg_get_pkgset_matches_installed_matches(set_deps)

            if not (set_matches and set_installed_matches):
                continue

            cat_namedesc = self._pkg_get_pkgset_set_from_desc(set_from)
            set_objects = []

            def update_yp(yp):
                yp.color = SulfurConf.color_install
                yp.set_cat_namedesc = cat_namedesc
                yp.set_names.add(set_name)
                yp.set_from.add(set_from)
                yp.set_matches = set_matches
                yp.set_installed_matches = set_installed_matches

            myobjs = []
            broken = False
            for match in set_matches:
                # set dependency
                if match[1] is None:
                    yp, new = gp_call(match[0])
                    yp.action = "i"
                else:
                    try:
                        yp, new = gp_call(match)
                    except RepositoryError:
                        broken = True
                        break
                myobjs.append(yp)

            if broken:
                continue

            for yp in myobjs:
                update_yp(yp)
            objects += myobjs

        return objects

    def _pkg_get_fake_updates(self):

        msg2 = _("Try to update your repositories")
        msg = "<big><b><span foreground='%s'>%s</span></b></big>\n%s.\n%s" % (
            SulfurConf.color_title,
            _('No updates available'),
            _("It seems that your system is already up-to-date. Good!"),
            msg2,
        )
        myobj = DummyEntropyPackage(namedesc = msg,
            dummy_type = SulfurConf.dummy_empty)
        return [myobj]

    def _pkg_get_loading(self):

        msg = "<big><b><span foreground='%s'>%s</span></b></big>\n%s.\n%s" % (
            SulfurConf.color_title,
            _('Please wait, loading...'),
            _("The current view is loading."),
            _("Be patient, sit down and relax."),
        )
        myobj = DummyEntropyPackage(namedesc = msg,
            dummy_type = SulfurConf.dummy_empty)
        return [myobj]

    def _pkg_get_empty_search_item(self):

        if self._filter_callback:
            msg2 = _("No packages found means nothing to show!")

            msg = "<big><b><span foreground='%s'>%s</span></b></big>\n%s.\n%s" % (
                SulfurConf.color_title,
                _("Nothing found"),
                _("No packages found using the provided search term"),
                msg2,
            )
        else:
            msg2 = _("No packages to show")
            msg = "<big><b><span foreground='%s'>%s</span></b></big>\n%s.\n%s" % (
                SulfurConf.color_title,
                _("No packages to show"),
                _("There are no packages that can be shown, sorry."),
                msg2,
            )
        myobj = DummyEntropyPackage(namedesc = msg,
            dummy_type = SulfurConf.dummy_empty)
        return myobj

    def _pkg_get_search(self):
        if self._search_callback is None:
            return []

        func, arg = self._search_callback
        if const.debug:
            t1 = time.time()
            const_debug_write(__name__, "_pkg_get_search: begin")
        matches = func(arg)
        if const.debug:
            const_debug_write(__name__, "_pkg_get_search: end in %s" % (
                time.time() - t1,))
        # load pkgs
        for key in self._get_calls_dict().keys():
            if key == "search": # myself
                continue
            self.get_raw_groups(key)
        pkgs = []
        for match in matches:
            yp, new = self.get_package_item(match)
            if new: # wtf!
                sys.stderr.write("WTF! %s is new %s\n" % (match, yp,))
                sys.stderr.flush()
                continue
            pkgs.append(yp)
        return pkgs


    def _get_calls_dict(self):
        calls_dict = {
            "installed": self._pkg_get_installed,
            "queued": self._pkg_get_queued,
            "available": self._pkg_get_available,
            "updates": self._pkg_get_updates,
            "orphans": self._pkg_get_orphans,
            "syspkg_orphans": self._pkg_get_syspkg_orphans,
            "unavail_orphans": self._pkg_get_unavailable_orphans,
            "unfiltered_updates": self._pkg_get_updates_raw,
            "reinstallable": self._pkg_get_reinstallable,
            "masked": self._pkg_get_masked,
            "user_masked": self._pkg_get_user_masked,
            "user_unmasked": self._pkg_get_user_unmasked,
            "pkgsets": self._pkg_get_pkgsets,
            "fake_updates": self._pkg_get_fake_updates,
            "loading": self._pkg_get_loading,
            "downgrade": self._pkg_get_downgrade,
            "search": self._pkg_get_search,
            "all": self._pkg_get_all,
        }
        return calls_dict

    def _get_groups(self, mask):
        return self._get_calls_dict().get(mask)()

    def is_reinstallable(self, atom, slot, revision):
        for repoid in self.Entropy.repositories():
            dbconn = self.Entropy.open_repository(repoid)
            idpackage, idreason = dbconn.isPackageScopeAvailable(atom, slot,
                revision)
            if idpackage == -1:
                continue
            return (repoid, idpackage,)
        return None

    def get_package_sets(self):
        sets = self.Entropy.Sets()
        return sets.available()

    def get_masked_package_action(self, match):
        action = self.Entropy.get_package_action(match)
        if action == 2:
            return 'u'
        elif action == -1:
            return 'd'
        elif action == 1:
            return 'i'
        else:
            return 'rr'

    def get_installed_idpackage(self, match):
        dbconn = self.Entropy.open_repository(match[1])
        try:
            atom, slot, revision = dbconn.getStrictScopeData(match[0])
        except TypeError:
            return None
        idpackage, idresult = \
            self.Entropy.installed_repository().isPackageScopeAvailable(atom, slot,
                revision)
        if idpackage == -1:
            return None
        return idpackage

    def filter_reinstallable(self, client_scope_data):
        clientdata = {}
        for idpackage, atom, slot, revision in client_scope_data:
            clientdata[(atom, slot, revision,)] = idpackage
        del client_scope_data

        matched_data = set()
        for repoid in self.Entropy.repositories():
            dbconn = self.Entropy.open_repository(repoid)
            try:
                repodata = dbconn.listAllPackages(get_scope = True)
            except OperationalError:
                continue # wtf?
            mydata = {}
            for idpackage, atom, slot, revision in repodata:
                mydata[(atom, slot, revision)] = idpackage

            def fm_pre(item):
                if item in mydata:
                    return True
                return False

            def fm(item):
                idpackage = mydata[item]
                idpackage, idreason = dbconn.maskFilter(idpackage)
                if idpackage != -1:
                    return (clientdata[item], (mydata[item], repoid,))
                return None

            matched_data |= set([x for x in map(fm, list(filter(fm_pre, clientdata))) \
                if x is not None])

        return matched_data

