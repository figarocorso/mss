# -*- coding: UTF-8 -*-
#
# (c) 2010 Mandriva, http://www.mandriva.com/
#
# This file is part of Mandriva Server Setup
#
# MSS is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.
#
# MSS is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with MSS; if not, write to the Free Software
# Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston,
# MA 02110-1301, USA.

import os
import re
import glob
import sys
import logging
import platform
import traceback
import json
import ConfigParser
from urllib2 import urlopen, URLError, HTTPError

from mss.agent.lib.utils import grep, Singleton
from mss.agent.lib.db import Session, OptionTable, LogTypeTable, LogTable, ModuleTable
from mss.agent.classes.module import Module
from mss.agent.managers.process import ProcessManager
from mss.agent.managers.translation import TranslationManager

LSB_FILENAME = '/etc/os-release'
_ = TranslationManager().translate
logger = logging.getLogger(__name__)


def expose(f):
    "Decorator to set exposed flag on a function."
    f.exposed = True
    return f


def is_exposed(f):
    "Test whether another function should be publicly exposed."
    return getattr(f, 'exposed', False)


class ModuleManager:
    """
    Class for managing modules

    """
    __metaclass__ = Singleton

    def _dispatch(self, method, params):
        func = getattr(self, method)
        if not is_exposed(func):
            raise Exception('Method "%s" is not supported' % method)

        try:
            return func(*params)
        except:
            logger.error(traceback.format_exc())
            raise

    def __init__(self):
        if platform.machine() == 'x86_64':
            self.arch = 'x86_64'
        else:
            self.arch = 'i586'
        self.mssAgentConfig = ConfigParser.ConfigParser();
        self.mssAgentConfig.readfp(open("/etc/mss/agent.ini"))
        self.modulesDirectory = self.mssAgentConfig.get("addons", "localPath")
        logger.warning("Looking for modules inside %s" % self.modulesDirectory)
        self.modules = {}
        self.packages = []

        # translation manager
        TranslationManager().set_catalog('agent', os.path.join(os.path.dirname(__file__), '..'))
        # BDD access
        self.session = Session()
        # logging
        self.load_packages()
        # Get machine-id
        machine_id = open('/etc/machine-id', 'r').read().strip()
        logger.info("Machine id is %s" % machine_id)
        self.set_option("machine-id", machine_id)

    def load_addons(self):
        """ return addons list """
        addons_json_fp = open(os.path.join(self.mssAgentConfig.get("addons", "localPath"), "addons.json"), "w")
        # Load modules description
        try:
            f_addons = urlopen(os.path.join(self.mssAgentConfig.get("addons", "remotePath"), "addons.json"))
            addons_json_fp.write(f_addons.read())
        #handle errors
        except HTTPError, e:
            print "HTTP Error:", e.code, url
        except URLError, e:
            print "URL Error:", e.reason, url
        addons_json_fp.close()

        addons_json_fp = open(os.path.join(self.mssAgentConfig.get("addons", "localPath"), "addons.json"), "r")
        addons = json.load(addons_json_fp)
        addons_json_fp.close()

        hAddons = {}
        for addon in addons:
            hAddons[addon["slug"]] = addon
        return [addons, hAddons]

    def load_sections(self):
        """ return section list """
        sections_json_fp = open(os.path.join(self.mssAgentConfig.get("sections", "localPath"), "sections.json"), "w")
        # Load modules description
        try:
            f_sections = urlopen(os.path.join(self.mssAgentConfig.get("sections", "remotePath"), "sections.json"))
            sections_json_fp.write(f_sections.read())
        #handle errors
        except HTTPError, e:
            print "HTTP Error:", e.code, url
        except URLError, e:
            print "URL Error:", e.reason, url
        sections_json_fp.close()

        # Load sections
        sections_json_fp = open(os.path.join(self.mssAgentConfig.get("sections", "localPath"), "sections.json"))
        sections = json.load(sections_json_fp)
        sections_json_fp.close()
        return sections

    def load_categories(self, sections, addons):
        """ return categories per section """
        categories = {}
        for section in sections:
            categories[section["slug"]] = []

        categories["hidden"] = []
        for addon in addons:
            if "sections" in addon["module"]:
                section = addon["module"]["sections"]
                for category in addon["categories"]:
                    category["modules"] = []
                    notFound = True
                    for cat in categories[section]:
                        if cat["slug"] == category["slug"]:
                            notFound = False
                    if notFound:
                        categories[section].append(category)
        return categories

    def load_modules2(self, addons):
        """ Dispatch modules in categories """
        # Add modules to categories
        for addon in addons:
            if "sections" in addon["module"]:
                section = addon["module"]["sections"]
                for category in addon["categories"]:
                    for cat in self._categories[section]:
                        if cat["slug"] == category["slug"]:
                            cat["modules"].append(addon["slug"])
            else:
                self._categories["hidden"].append(addon["slug"])

    @expose
    def load_module(self, module):
        """ Load one module """
        sys.path.append(self.modulesDirectory)
        modules = self.get_available_modules()
        logger.info("Get available mss modules : ")
        if module in modules and module not in self.modules:
            logger.debug("Loading %s" % module)
            m = Module(os.path.join(self.modulesDirectory, module), self, self.arch)
            self.modules[m.slug] = m
            logger.info(m)
            for mod in m.dependencies:
                self.load_module(mod)

    @expose
    def load(self):
        """ Load sections/modules after logging successfully """
                # Load section info
        self._sections = self.load_sections()

        # Load addon list
        [self._addons, self._hAddons] = self.load_addons()

        # Load categories
        self._categories = self.load_categories(self._sections, self._addons)
        self.load_modules2(self._addons)

    @expose
    def set_lang(self, lang):
        """ change lang during execution """
        logger.info("Lang changed to %s" % lang)
        TranslationManager().set_lang(lang)

    @expose
    def set_option(self, slug, value):
        """ add an option in the DB """
        option = OptionTable(slug, value)
        self.session.merge(option)
        self.session.commit()

    @expose
    def get_option(self, slug):
        """ get an option from the BDD """
        option = self.session.query(OptionTable).get(slug)
        if option:
            return json.loads(option.value)
        else:
            return False

    @expose
    def load_packages(self):
        logger.info("Load packages...")
        ProcessManager().load_packages(self.set_packages)

    @expose
    def check_net(self):
        ProcessManager().check_net()

    @expose
    def update_medias(self):
        ProcessManager().update_medias()

    @expose
    def reboot(self):
        ProcessManager().reboot()

    def set_packages(self, code, output):
        if code == 0:
            packages = output.split('#')
            if not packages:
                logger.error("No packages found.")
            else:
                self.packages = packages
                logger.info("Loading packages done.")
        else:
            logger.error("Can't load packages.")

    @expose
    def check_media(self, search):
        """ check if media exist """
        return grep(search, '/etc/urpmi/urpmi.cfg')

    @expose
    def check_distribution(self, distribution):
        """
        Allow to check which distribution we are using
        """
        if os.path.exists(LSB_FILENAME):
            for line in open(LSB_FILENAME):
                if line.startswith("PRETTY_NAME"):
                    if distribution in line:
                        return True
        return False

    def get_available_modules(self):
        ret = []
        for item in glob.glob(os.path.join(self.modulesDirectory,
                                           "*", "__init__.py")):
            ret.append(item.split("/")[-2])
        return ret

    def check_installed(self, module):
        """ check if module is installed """
        packages = set(module.packages)
        # check if packages are installed
        if len(packages) == len(packages.intersection(self.packages)):
            module.installed = True
            return True
        else:
            module.installed = False
            return False

    def get_conflicts(self, conflicts, module):
        """ return a module list of current conflicts
            with module """
        if module in self.modules:
            module = self.modules[module]
            _conflicts = module.conflicts
            _dependencies = module.dependencies
            _configured = module.configured
        else:
            module = self._hAddons[module]
            _conflicts = module['module'].get('conflicts', [])
            _dependencies = module['module'].get('dependencies', [])
            _configured = module['module'].get('configured', False)
        for m in _conflicts:
            try:
                if not m in conflicts and _configured:
                    conflicts.append(m)
                    logger.debug("Conflict with : %s" % m)
                    conflicts = self.get_conflicts(conflicts, m)
            except KeyError:
                pass
        for m in _dependencies:
            conflicts = self.get_conflicts(conflicts, m)
        return conflicts

    def get_module(self, m):
        """ return basic info for one module """
        if m in self.modules:
            module = self.modules[m]
            self.check_installed(module)
            
            configured = module.configured
            installed = module.installed
            actions = module.actions
        else:
            details = self.get_module_details(m)
            configured = details['configured']
            installed = details['installed']
            actions = details['actions']

        # get current conflicts for module
        conflicts = self.get_conflicts([], m)
        #conflicts = [conflict.name for conflict in conflicts]

        mod = self._hAddons.get(m, {})
        # return result
        result = {
            'slug': mod['slug'], 'name': mod['name'],
            'actions': actions, 'desc': mod.get('description'),
            'purchased': mod.get("purchased", False), 'price': mod.get("price", 0),
            'installed': installed,
            'configured': configured, 'conflict': conflicts,
            'conflicts': mod['module'].get('conflicts', []),
            'dependencies': mod['module'].get('dependencies', []),
            'reboot': mod['module'].get('reboot', False)}
        logger.debug("Module info: %s" % str(result))
        return result

    @expose
    def get_modules(self, modules):
        """ return basic info for modules """
        logger.info("Get modules info: %s" % str(modules))
        result = []
        for m in modules:
            logger.debug("Get module info: %s" % str(m))
            result.append(self.get_module(m))
        return result

    @expose
    def get_packages(self, module):
        """ returns package list for module """
        return self.modules[module].packages

    @expose
    def preinstall_modules(self, modules):
        """
        get dependencies for modules to install
        return modules infos
        """
        for module in modules:
            if module not in self.modules:
                self.load_module(module)
        # force module re-installation
        # (not-used for now)
        force_modules = []
        for m in modules:
            if m.startswith("force-"):
                force_modules.append(m.replace("force-", ""))
        modules = [m.replace("force-", "") for m in modules]
        # store old modules list
        old = modules
        # get dependencies for modules
        modules = self.check_dependencies(modules, [])
        modules = self.order_dependencies(modules)
        # get difference for dep list
        deps = list(set(modules).difference(old))
        # get modules info (modules + dependencies)
        modules = self.get_modules(modules)
        # remove already configured modules unless force
        modules = [m for m in modules if not m['configured'] or m['slug'] in force_modules]
        # tell if the module is an dependency of selected modules
        # or if we reinstall it
        for m in modules:
            if m['slug'] in deps:
                m['dep'] = True
            else:
                m['dep'] = False
            if m['slug'] in force_modules:
                m['force'] = True
            else:
                m['force'] = False
        logger.info("Pre-install modules : %s" % str(modules))
        return modules

    def order_dependencies(self, modules, cnt=1):
        for module in modules:
            # if the module has dependencies and is not indexed
            if module[1] and module[2] == -1:
                # for each dep of current module
                set_index = True
                for m1 in module[1]:
                    # for each module
                    for m2 in modules:
                        # if the dep is not indexed (not >=0)
                        if m1 == m2[0] and not m2[2] >= 0:
                            set_index = False
                # set the current module index to cnt
                # if all dependencies are indexed
                if set_index:
                    module[2] = cnt

        # make 10 pass to determine indexes
        # FIXME! this limits the nb max of the modules list
        if(cnt < 10):
            cnt += 1
            modules = self.order_dependencies(modules, cnt)
        # calcule module list from indexes
        else:
            result = []
            for i in range(cnt):
                for module in modules:
                    if module[2] == i:
                        if not module[0] in result:
                            result.append(module[0])
            modules = result
        return modules

    def check_dependencies(self, modules, dependencies):
        """ get dependencies for modules
            create a list with the form : [ [ module, [dependencies], index ],... ]
        """
        for module in modules:
            deps = self.get_dependencies(module)
            if deps:
                # set the index a -1 to calculate index
                dependencies.append([module, deps, -1])
                dependencies = self.check_dependencies(deps, dependencies)
            else:
                # set the index at 0 as the module has no dependencies
                dependencies.append([module, None, 0])
        return dependencies

    def get_dependencies(self, module):
        """ get dependencies for module """
        if getattr(self.modules[module], 'dependencies' or None):
            deps = []
            for dep in self.modules[module].dependencies:
                try:
                    if self.modules[dep]:
                        deps.append(dep)
                except KeyError:
                    logger.error("Module %s doesn't exists !" % dep)
            return deps
        return None

    @expose
    def get_medias(self, modules):
        """ get medias for modules """
        logger.info("Get medias for modules : %s" % str(modules))
        medias = [self.modules[module].medias for module in modules if not self.check_media(module) and self.modules[module].medias]
        logger.debug("Media list : %s" % str(medias))
        return medias

    @expose
    def add_media(self, module, login=None, passwd=None):
        """ add all medias for module """
        media = self.modules[module].medias
        logger.info("Add media : %s" % media.name)
        # get add commands for media
        command = media.get_command(login, passwd)
        logger.debug("Execute: %s" % str(command))
        ProcessManager().add_media(command)

    @expose
    def install_modules(self, modules):
        """ install modules packages """
        logger.info("Install modules : %s" % str(modules))
        packages = []
        for module in modules:
            packages += self.modules[module].packages
        if packages:
            logger.debug("Install packages : %s" % str(packages))
            ProcessManager().install_packages(packages)
            return True
        else:
            logger.info("No packages to install")
            return False

    @expose
    def get_config(self, modules):
        """ get modules config """
        logger.info("Get config for modules : %s" % str(modules))
        config = []
        for module in modules:
            config.append(self.modules[module].get_config())
        return config

    @expose
    def valid_config(self, modules, modules_config):
        """ validate user configuration for modules """
        config = []
        errors = False
        for module in modules:
            module_errors, module_config = self.modules[module].valid_config(modules_config)
            config.append(module_config)
            if module_errors:
                errors = True
        return (errors, config)

    @expose
    def run_config(self, module):
        """ run configuration for module """
        logger.debug("Run configuration for %s" % str(module))
        path, script, args = self.modules[module].info_config()
        logger.debug("Run script: %s, args: %s" % (str(script), str(args)))
        return ProcessManager().run_script(script, args, path, module)

    @expose
    def end_config(self, module):
        if not self.modules[module].configured:
            logger.debug("Set %s as configured" % str(module))
            self.modules[module].configured = True
            # store the config log
            logger.debug("Saving %s configuration log in the DB" % str(module))
            log_type = self.session.query(LogTypeTable).filter(LogTypeTable.name == "config").first()
            if not log_type:
                log_type = LogTypeTable("config")
                self.session.add(log_type)
                self.session.commit()
            module_obj = self.session.query(ModuleTable).filter(ModuleTable.name == module).first()
            config_log = LogTable(log_type.id, module_obj.id, self.get_state("config", module))
            self.session.add(config_log)
            self.session.commit()
        return 0

    def clean_output(self, string):
        # remove ANSI codes
        string = re.sub('\x1b[^m]*m', '', string)
        return string

    @expose
    def get_state(self, type, module="agent"):
        """ return execution output """
        code, output = ProcessManager().p_state(type, module)
        # format output
        tmp = output.splitlines()
        output = []
        if tmp:
            for line in tmp:
                try:
                    if int(line[0]) in range(9):
                        text_code = line[0]
                        text = line[1:]
                    else:
                        text_code = 0
                        text = line
                    output.append({'code': text_code, 'text': self.clean_output(text)})
                # no code at line start
                except ValueError:
                    text_code = 0
                    text = line
                    output.append({'code': text_code, 'text': self.clean_output(text)})
                # no char in line
                except IndexError:
                    pass
        else:
            code = 2000
            output = [{'code': 0, 'text': u''}]

        return (code, output)

    @expose
    def get_status(self):
        """ return current agent status """
        status = []
        statuses = ProcessManager().pm_state()
        for sts in statuses:
            status.append(_(sts, "agent"))
        return ', '.join(status)

    @expose
    def get_sections(self):
        """ return list of sections """
        return self._sections

    def get_categories(self, addons, section):
        """ return list of categories """
        if section in self._categories:
            return self._categories[section]
        else:
            return []

    @expose
    def get_section(self, section):
        """ return modules belonging to section """
        # Init a section structure to be sent to mss-www view.py
        _section = {}
        _section["slug"] = section
        for sec in self._sections:
            if sec["slug"] == section:
                _section["name"] = sec["name"]

        # Set bundles list
        _section["bundles"] = self._categories[section]
        return _section

    @expose
    def get_module_details(self, module):
        """ return the detailed description on a module if it exist """
        mod = self.session.query(ModuleTable).filter(ModuleTable.name == module).first()
        if mod and mod.configured:
            desc_json_fp = open(os.path.join(self.modulesDirectory, module, "desc.json"))
            conf = json.load(desc_json_fp)
            desc_json_fp.close()
            actions = conf.get("actions", [])
            installed = True
            configured = True
        else:
            actions = []
            installed = False
            configured = False
        self._hAddons[module]['module']['installed'] = installed
        self._hAddons[module]['module']['configured'] = configured
        details = {"actions": actions, "installed": installed, "configured": configured}
        return details
