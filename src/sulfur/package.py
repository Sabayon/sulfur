#!/usr/bin/python -tt
# -*- coding: iso-8859-1 -*-
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU Library General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 59 Temple Place - Suite 330, Boston, MA 02111-1307, USA.

from entropy.const import *
from entropy.i18n import _
from sulfur.entropyapi import Equo
from sulfur.setup import cleanMarkupString, SulfurConf
EquoIntf = Equo()

class DummyEntropyPackage:

    def __init__(self, namedesc = None, dummy_type = -1, onlyname = ''):
        self.matched_atom = (0,0)
        self.namedesc = namedesc
        self.queued = None
        self.repoid = ''
        self.name = ''
        self.vote = -1
        self.voted = 0.0
        self.color = None
        self.action = None
        self.dbconn = None
        self.masked = None
        self.pkgset = False
        self.broken = False # used by pkgsets
        self.selected_by_user = False
        self.dummy_type = dummy_type
        self.onlyname = onlyname
        self.set_names = set()
        self.set_matches = set()
        self.set_installed_matches = set()
        self.set_from = None
        self.set_cat_namedesc = None
        self.set_category = False
        self.set_install_incomplete = False
        self.set_remove_incomplete = False
        self.is_downgrade = False

class EntropyPackage:

    import entropy.tools as entropyTools
    def __init__(self, matched_atom, remote = None, pkgset = None):

        self.pkgset = pkgset
        self.broken = False # used by pkgsets
        self.queued = None
        self.action = None
        self.dummy_type = None
        self.do_purge = False
        self.masked = None
        self.voted = 0.0
        self.color = SulfurConf.color_normal
        self.remote = remote
        self.selected_by_user = False
        self.set_names = set()
        self.set_matches = set()
        self.set_installed_matches = set()
        self.set_from = None
        self.set_cat_namedesc = None
        self.set_category = False
        self.set_install_incomplete = False
        self.set_remove_incomplete = False
        self.is_downgrade = False

        if self.pkgset:

            # must be available!
            set_match, rc = EquoIntf.package_set_match(
                matched_atom[1:])
            if not rc:
                # package set broken
                self.broken = True
            else:
                (self.set_from, self.set_name, self.set_matches,) = set_match
                self.cat = self.set_name
                self.set_cat_namedesc = self.set_name
                self.description = self.set_name
                self.matched_repo = set_name

            self.from_installed = False
            self.dbconn = None
            self.dummy_type = -2
            self.is_set_dep = True
            self.set_names = set()
            self.onlyname = matched_atom
            self.name = matched_atom
            self.set_category = False
            self.matched_id = "@"

        elif self.remote:

            self.dbconn = EquoIntf.open_memory_database()
            idpackage, revision, mydata_upd = self.dbconn.addPackage(self.remote)
            matched_atom = (idpackage, matched_atom[1])
            self.from_installed = False

        else:

            if matched_atom[1] == 0:
                self.dbconn = EquoIntf.clientDbconn
                self.from_installed = True
            else:
                self.dbconn = EquoIntf.open_repository(matched_atom[1])
                self.from_installed = False

        if isinstance(matched_atom, tuple):
            self.matched_id, self.matched_repo = matched_atom

        self.matched_atom = matched_atom
        self.installed_match = None

    # for debugging purposes, sample method
    """
    def __setattr__(self, name, value):
        if name in ("installed_match", "matched_atom",):
            do_search = True
            try:
                obj_name = str(self)
            except:
                #
                do_search = False
            if do_search:
                if obj_name.find("/flite") != -1:
                    print repr(self), str(self), "=>" , name, ":", value
                    if self.__dict__.get(name) is not None:
                        import pdb; pdb.set_trace()
        self.__dict__[name] = value
    """

    def __del__(self):
        if hasattr(self,'remote'):
            if self.remote:
                self.dbconn.closeDB()

    def __str__(self):
        if self.pkgset: return self.matched_atom
        return str(self.dbconn.retrieveAtom(self.matched_id) + "~" + \
            str(self.dbconn.retrieveRevision(self.matched_id)))

    def __cmp__(self, pkg):
        if pkg.matched_atom == self.matched_atom:
            return 0
        return 1

    def get_pkg(self):
        return self.matched_atom

    def get_tag(self):
        if self.pkgset: return ''

        return self.dbconn.retrieveVersionTag(self.matched_id)

    def get_name(self):
        if self.pkgset: return self.matched_atom
        return self.dbconn.retrieveAtom(self.matched_id)

    def is_masked(self):

        if self.pkgset:
            return False

        idpackage, idmask = self.dbconn.idpackageValidator(self.matched_id)
        if idpackage != -1:
            return False
        return True

    def is_user_masked(self):
        if self.from_installed:
            key, slot = self.dbconn.retrieveKeySlot(self.matched_id)
            m_id, m_r = EquoIntf.atom_match(key, matchSlot = slot)
            if m_id == -1: return False
            return EquoIntf.is_match_masked_by_user((m_id, m_r,))
        return EquoIntf.is_match_masked_by_user(self.matched_atom)

    def is_user_unmasked(self):
        if self.from_installed:
            key, slot = self.dbconn.retrieveKeySlot(self.matched_id)
            m_id, m_r = EquoIntf.atom_match(key, matchSlot = slot)
            if m_id == -1: return False
            return EquoIntf.is_match_unmasked_by_user((m_id, m_r,))
        return EquoIntf.is_match_unmasked_by_user(self.matched_atom)

    def get_nameDesc(self):

        if self.pkgset:
            t = self.matched_atom
            desc = _("Recursive Package Set")
            t += '\n<small><span foreground=\'%s\'>%s</span></small>' % (
                SulfurConf.color_pkgdesc,cleanMarkupString(desc),)
            return t

        ugc_string = ''
        atom = self.get_name()
        if self.from_installed: repo = self.get_repository()
        else: repo = self.matched_repo
        key = self.entropyTools.dep_getkey(atom)
        downloads = EquoIntf.UGC.UGCCache.get_package_downloads(repo,key)
        ugc_string = "<small>[%s]</small> " % (downloads,)

        t = ugc_string+'/'.join(atom.split("/")[1:])
        if self.masked:
            t +=  " <small>[<span foreground='%s'>%s</span>]</small>" % (
                SulfurConf.color_title2,
                EquoIntf.SystemSettings['pkg_masking_reasons'][self.masked],)

        desc = self.get_description(markup = False)
        if len(desc) > 56:
            desc = desc[:56].rstrip()+"..."
        t += '\n<small><span foreground=\'%s\'>%s</span></small>' % (
            SulfurConf.color_pkgdesc, cleanMarkupString(desc),)
        return t

    def get_only_name(self):
        if self.pkgset:
            return self.set_name
        return self.dbconn.retrieveName(self.matched_id)

    def get_repository(self):
        if self.pkgset:
            x = self.set_from
            if x == etpConst['userpackagesetsid']: x = _("User")
            return x
        if self.matched_atom[1] == 0:
            return self.dbconn.retrievePackageFromInstalledTable(self.matched_id)
        else: return self.matched_repo

    def get_idpackage(self):
        return self.matched_id

    def get_revision(self):
        if self.pkgset: return 0

        return self.dbconn.retrieveRevision(self.matched_id)

    def is_sys_pkg(self):
        if self.pkgset: return False

        match = self.matched_atom
        if (not self.from_installed) and (not self.installed_match):
            return False
        elif self.installed_match:
            match = self.installed_match

        # check if it's a system package
        s = EquoIntf.validate_package_removal(match[0])
        return not s

    def get_install_status(self):
        # 0: from installed db, so it's installed for sure
        # 1: not installed
        # 2: updatable
        # 3: already updated to the latest
        if self.pkgset:
            return 0

        if self.from_installed:
            return 0
        key, slot = self.dbconn.retrieveKeySlot(self.matched_id)
        matches = EquoIntf.clientDbconn.searchKeySlot(key,slot)
        if not matches: # not installed, new!
            return 1
        else:
            rc, matched = EquoIntf.check_package_update(key+":"+slot, deep = True)
            if rc:
                return 2
            return 3

    def get_version(self):
        if self.pkgset:
            return "0"

        tag = ""
        vtag = self.dbconn.retrieveVersionTag(self.matched_id)
        if vtag:
            tag = "#"+vtag
        tag += "~"+str(self.dbconn.retrieveRevision(self.matched_id))
        return self.dbconn.retrieveVersion(self.matched_id)+tag

    def get_only_version(self):
        if self.pkgset:
            return "0"
        return self.dbconn.retrieveVersion(self.matched_id)

    def get_download_url(self):
        if self.pkgset:
            return None
        return self.dbconn.retrieveDownloadURL(self.matched_id)

    def get_slot(self):
        if self.pkgset:
            return "0"
        return self.dbconn.retrieveSlot(self.matched_id)

    def get_dependencies(self):
        if self.pkgset: self.set_matches.copy()
        return self.dbconn.retrieveDependencies(self.matched_id)

    def get_inverse_dependencies(self):
        if self.pkgset:
            return []
        return self.dbconn.retrieveDepends(self.matched_id, atoms = True)

    def get_conflicts(self):
        if self.pkgset:
            return []
        return self.dbconn.retrieveConflicts(self.matched_id)

    def get_license(self):
        if self.pkgset:
            return ""
        return self.dbconn.retrieveLicense(self.matched_id)

    def get_changelog(self):
        if self.pkgset:
            return ""
        return self.dbconn.retrieveChangelog(self.matched_id)

    def get_digest(self):
        if self.pkgset:
            return "0"
        return self.dbconn.retrieveDigest(self.matched_id)

    def get_category(self):
        if self.pkgset:
            return self.cat
        return self.dbconn.retrieveCategory(self.matched_id)

    def get_api(self):
        if self.pkgset:
            return "0"
        return self.dbconn.retrieveApi(self.matched_id)

    def get_useflags(self):
        if self.pkgset:
            return []
        return self.dbconn.retrieveUseflags(self.matched_id)

    def get_trigger(self):
        if self.pkgset:
            return ""
        return self.dbconn.retrieveTrigger(self.matched_id)

    def get_config_protect(self):
        if self.pkgset:
            return []
        return self.dbconn.retrieveProtect(self.matched_id)

    def get_config_protect_mask(self):
        if self.pkgset:
            return []
        return self.dbconn.retrieveProtectMask(self.matched_id)

    def get_keywords(self):
        if self.pkgset:
            return []
        return self.dbconn.retrieveKeywords(self.matched_id)

    def get_needed(self):
        if self.pkgset:
            return []
        return self.dbconn.retrieveNeeded(self.matched_id)

    def get_compile_flags(self):
        if self.pkgset:
            return []
        flags = self.dbconn.retrieveCompileFlags(self.matched_id)
        return flags

    def get_sources(self):
        if self.pkgset:
            return []
        return self.dbconn.retrieveSources(self.matched_id)

    def get_eclasses(self):
        if self.pkgset:
            return []
        return self.dbconn.retrieveEclasses(self.matched_id)

    def get_homepage(self):
        if self.pkgset:
            return ""
        return self.dbconn.retrieveHomepage(self.matched_id)

    def get_messages(self):
        if self.pkgset:
            return []
        return self.dbconn.retrieveMessages(self.matched_id)

    def get_key_slot(self):
        if self.pkgset:
            return self.set_name,"0"
        return self.dbconn.retrieveKeySlot(self.matched_id)

    def get_description_no_markup(self):
        if self.pkgset:
            return self.set_cat_namedesc
        return self.get_description(markup = False)

    def get_description(self, markup = True):
        if self.pkgset:
            return self.set_cat_namedesc

        if markup:
            return cleanMarkupString(
                self.dbconn.retrieveDescription(self.matched_id))
        else:
            return self.dbconn.retrieveDescription(self.matched_id)

    def get_download_size(self):
        if self.pkgset:
            return 0
        return self.dbconn.retrieveSize(self.matched_id)

    def get_disk_size(self):
        if self.pkgset:
            return 0
        return self.dbconn.retrieveOnDiskSize(self.matched_id)

    def get_proper_size(self):
        if self.from_installed:
            return self.get_disk_sizeFmt()
        else:
            return self.get_download_sizeFmt()

    def get_download_sizeFmt(self):
        if self.pkgset:
            return 0
        return EquoIntf.entropyTools.bytes_into_human(
            self.dbconn.retrieveSize(self.matched_id))

    def get_disk_sizeFmt(self):
        if self.pkgset:
            return 0
        return EquoIntf.entropyTools.bytes_into_human(
            self.dbconn.retrieveOnDiskSize(self.matched_id))

    def get_arch(self):
        return etpConst['currentarch']

    def get_creation_date(self):
        if self.pkgset:
            return 0
        return self.dbconn.retrieveDateCreation(self.matched_id)

    def get_creation_date_formatted(self):
        if self.pkgset:
            return 0
        return EquoIntf.entropyTools.convert_unix_time_to_human_time(
            float(self.dbconn.retrieveDateCreation(self.matched_id)))

    def get_release(self):
        if self.pkgset:
            return EquoIntf.SystemSettings['repositories']['branch']
        return self.dbconn.retrieveBranch(self.matched_id)

    def get_ugc_package_vote(self):
        if self.pkgset:
            return -1
        atom = self.get_name()
        if not atom:
            return None
        return EquoIntf.UGC.UGCCache.get_package_vote(self.get_repository(),
            self.entropyTools.dep_getkey(atom))

    def get_ugc_package_vote_int(self):
        if self.pkgset:
            return 0
        atom = self.get_name()
        if not atom:
            return 0
        vote = EquoIntf.UGC.UGCCache.get_package_vote(self.get_repository(),
            self.entropyTools.dep_getkey(atom))
        if not isinstance(vote, float):
            return 0
        return int(vote)

    def get_ugc_package_vote_float(self):
        if self.pkgset:
            return 0.0
        atom = self.get_name()
        if not atom:
            return 0.0
        vote = EquoIntf.UGC.UGCCache.get_package_vote(self.get_repository(),
            self.entropyTools.dep_getkey(atom))
        if not isinstance(vote, float):
            return 0.0
        return vote

    def get_ugc_package_voted(self):
        return self.voted

    def get_ugc_package_downloads(self):
        if self.pkgset:
            return 0
        if self.from_installed:
            return 0
        atom = self.get_name()
        if not atom:
            return 0
        key = self.entropyTools.dep_getkey(atom)
        return EquoIntf.UGC.UGCCache.get_package_downloads(self.matched_repo,
            key)

    def get_attribute(self,attr):
        x = None
        if attr == "description":
            x = cleanMarkupString(self.dbconn.retrieveDescription(self.matched_id))
        elif attr == "category":
            x = self.dbconn.retrieveCategory(self.matched_id)
        elif attr == "license":
            x = self.dbconn.retrieveLicense(self.matched_id)
        elif attr == "creationdate":
            x = self.dbconn.retrieveDateCreation(self.matched_id)
        elif attr == "version":
            x = self.dbconn.retrieveVersion(self.matched_id)
        elif attr == "revision":
            x = self.dbconn.retrieveRevision(self.matched_id)
        elif attr == "versiontag":
            x = self.dbconn.retrieveVersionTag(self.matched_id)
            if not x:
                x = "None"
        elif attr == "branch":
            x = self.dbconn.retrieveBranch(self.matched_id)
        elif attr == "name":
            x = self.dbconn.retrieveName(self.matched_id)
        elif attr == "namedesc":
            x = self.get_nameDesc()
        elif attr == "slot":
            x = self.dbconn.retrieveSlot(self.matched_id)
        return x

    def _get_time( self ):
        if self.pkgset:
            return 0
        return self.dbconn.retrieveDateCreation(self.matched_id)

    def get_filelist( self ):
        if self.pkgset:
            return []
        mycont = sorted(list(self.dbconn.retrieveContent(self.matched_id)))
        return mycont

    def get_filelist_ext( self ):
        if self.pkgset:
            return []
        return self.dbconn.retrieveContent(self.matched_id, extended = True,
            order_by = 'file')

    def get_fullname( self ):
        if self.pkgset:
            return self.set_name
        return self.dbconn.retrieveAtom(self.matched_id)

    pkg =  property(fget=get_pkg)
    name =  property(fget=get_name)
    namedesc = property(fget=get_nameDesc)
    onlyname = property(fget=get_only_name)
    cat = property(fget=get_category)
    repoid =  property(fget=get_repository)
    ver =  property(fget=get_version)
    binurl = property(fget=get_download_url)
    onlyver = property(fget=get_only_version)
    tag = property(fget=get_tag)
    revision = property(fget=get_revision)
    digest = property(fget=get_digest)
    version = property(fget=get_version)
    release = property(fget=get_release)
    slot = property(fget=get_slot)
    maskstat = property(fget=is_masked)
    keywords = property(fget=get_keywords)
    useflags = property(fget=get_useflags)
    homepage = property(fget=get_homepage)
    messages = property(fget=get_messages)
    protect = property(fget=get_config_protect)
    protect_mask = property(fget=get_config_protect_mask)
    trigger = property(fget=get_trigger)
    compileflags = property(fget=get_compile_flags)
    dependencies = property(fget=get_dependencies)
    needed = property(fget=get_needed)
    conflicts = property(fget=get_conflicts)
    dependsFmt = property(fget=get_inverse_dependencies)
    api = property(fget=get_api)
    content = property(fget=get_filelist)
    contentExt = property(fget=get_filelist_ext)
    eclasses = property(fget=get_eclasses)
    lic = property(fget=get_license)
    sources = property(fget=get_sources)
    keyslot = property(fget=get_key_slot)
    description =  property(fget=get_description)
    description_nomarkup = property(fget=get_description_no_markup)
    size =  property(fget=get_download_size)
    intelligentsizeFmt = property(fget=get_proper_size)
    sizeFmt =  property(fget=get_download_sizeFmt)
    disksize =  property(fget=get_disk_size)
    disksizeFmt =  property(fget=get_disk_sizeFmt)
    arch = property(fget=get_arch)
    epoch = property(fget=get_creation_date)
    epochFmt = property(fget=get_creation_date_formatted)
    syspkg = property(fget=is_sys_pkg)
    install_status = property(fget=get_install_status)
    vote = property(fget=get_ugc_package_vote)
    voteint = property(fget=get_ugc_package_vote_int)
    votefloat = property(fget=get_ugc_package_vote_float)
    voted = property(fget=get_ugc_package_voted)
    downloads = property(fget=get_ugc_package_downloads)
    user_unmasked = property(fget=is_user_unmasked)
    user_masked = property(fget=is_user_masked)
    changelog = property(fget=get_changelog)
