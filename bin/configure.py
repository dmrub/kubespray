#!/usr/bin/env python3

"""Ansible/Kubespray configurator"""

from __future__ import print_function

import sys
import argparse
import copy
import getpass
import logging
import random
import readline
import shutil
import string
import subprocess
import tempfile
import hashlib
import os.path
import difflib
import pprint
import shlex
import yaml
import itertools

try:
    from subprocess import DEVNULL  # pylint: disable=ungrouped-imports
except ImportError:
    import os  # pylint: disable=ungrouped-imports

    DEVNULL = open(os.devnull, 'wb')

try:
    from yaml import CSafeLoader as Loader, CDumper as Dumper
except ImportError:
    from yaml import SafeLoader as Loader, Dumper


def diff_dicts(dict_a, dict_b):
    if dict_a == dict_b:
        return ''
    return '\n'.join(
        difflib.ndiff(pprint.pformat(dict_a, width=70).splitlines(),
                      pprint.pformat(dict_b, width=70).splitlines())
    )


LOG = logging.getLogger(__name__)

# Default configuration
HOME = os.path.expanduser('~')
THIS_DIR = os.path.dirname(os.path.realpath(__file__))
ROOT_DIR = os.path.join(THIS_DIR, '..')
CONFIG_DIR = os.path.join(HOME, '.ansible')

ANSIBLE_DIR = ROOT_DIR
ANSIBLE_PLAYBOOKS_DIR = ANSIBLE_DIR
ANSIBLE_INVENTORY_DIR = os.path.join(ROOT_DIR, 'inventory')
ANSIBLE_VAULT_PASSWORD_FILE = os.getenv('ANSIBLE_VAULT_PASSWORD_FILE',
                                        os.path.join(CONFIG_DIR, 'vault_pass.txt'))
ANSIBLE_CONFIG = os.getenv('ANSIBLE_CONFIG',
                           os.path.join(ANSIBLE_DIR, 'ansible.cfg'))
ANSIBLE_FILTER_PLUGINS = os.getenv('ANSIBLE_FILTER_PLUGINS',
                                   os.path.join(ANSIBLE_DIR, 'filter_plugins'))

ANSIBLE_ROLES_PATH = os.getenv('ANSIBLE_ROLES_PATH', os.path.join(ANSIBLE_DIR, 'roles'))

CFG_VAULT_FILE = os.path.join(ROOT_DIR, 'ansible-vault.yml')
CFG_VARS_FILE = os.path.join(ROOT_DIR, 'ansible-vars.yml')
CONFIG_VARS_FILE = os.path.join(ROOT_DIR, 'config.yml')
CFG_VARS_CACHE_FILE = os.path.join(ROOT_DIR, 'ansible-vars.cache')


def is_sequence(value):
    return isinstance(value, (list, tuple))


def to_list(value):
    if not value:
        return []
    elif isinstance(value, tuple):
        return list(value)
    elif not isinstance(value, list):
        return [value]
    return value


def rlinput(prompt, prefill=''):
    readline.set_startup_hook(lambda: readline.insert_text(prefill))
    try:
        return input(prompt)
    finally:
        readline.set_startup_hook()


def rlselect(prompt, words, print_menu_on_empty_input=True, print_menu_before_prompt=False, prefill=''):
    value = ''
    while True:
        if print_menu_before_prompt or (print_menu_on_empty_input and value == ''):
            for i, word in enumerate(words):
                print("{}) {}".format(i + 1, word), file=sys.stderr)
        value = rlinput(prompt, prefill=prefill)
        if value == '':
            continue
        try:
            j = int(value)
        except ValueError:
            yield -1, value
        else:
            if j < 1 or j > len(words):
                yield -1, value
            else:
                yield j - 1, words[j - 1]


def randpw(size=16, chars='_' + string.ascii_uppercase + string.ascii_lowercase + string.digits):
    return ''.join(random.SystemRandom().choice(chars) for _ in range(size))


def relpaths(base_path, paths, no_parent_dirs=False):
    base_path = os.path.realpath(base_path)
    for path in paths:
        relative_path = os.path.relpath(path, base_path)
        if no_parent_dirs and relative_path.startswith(os.pardir):
            relative_path = os.path.realpath(relative_path)
        yield relative_path


def auto_realpath(path, root_dir):
    if os.path.exists(path):
        path = os.path.realpath(path)
    else:
        abs_path = os.path.join(root_dir, path)
        if os.path.exists(abs_path):
            path = os.path.realpath(abs_path)
    return path


def foreach(value, func):
    if not value:
        return []
    if not is_sequence(value):
        return [func(value)]
    return [func(elem) for elem in value]


def realpath_if(path):
    if path:
        return os.path.realpath(path)
    return path


def array_realpath_if(paths):
    return foreach(paths, realpath_if)


def realpath_auto_if(path):
    return auto_realpath(path, ROOT_DIR) if path else path


def array_realpath_auto_if(paths):
    return foreach(paths, realpath_auto_if)


def vault_id_source(vault_id):
    if '@' in vault_id:
        label, source = vault_id.split('@', 1)
        return source
    return None

def vault_id_label(vault_id):
    if '@' in vault_id:
        label, source = vault_id.split('@', 1)
        return label
    return None


def realpath_vault_id_if(vault_id):
    if vault_id:
        if '@' in vault_id:
            label, source = vault_id.split('@', 1)
            if source != 'prompt':
                source = auto_realpath(source, ROOT_DIR)
                vault_id = label + '@' + source
    return vault_id


def array_realpath_vault_id_if(vault_ids):
    return foreach(vault_ids, realpath_vault_id_if)


def dirname_if(path):
    if path:
        return os.path.dirname(path)
    return path


def array_dirname_if(paths):
    return foreach(paths, dirname_if)


def sep_at_end(path):
    if not path.endswith(os.sep):
        path += os.sep
    return path


def array_sep_at_end(paths):
    return foreach(paths, sep_at_end)


def backup_file(path):
    rpath = os.path.realpath(path)
    if os.path.exists(rpath):
        bak_rpath = rpath + "~"
        while os.path.exists(bak_rpath):
            bak_rpath += "~"
        LOG.info('Backup file %s to file %s', rpath, bak_rpath)
        os.rename(rpath, bak_rpath)


def load_config(file_name, defaults=None, fix_config_vars_func=None):
    """
    Load configuration from YAML file, optionally fix variables dictionary and set default variables if they are
    missing.
    :param file_name: YAML file name
    :param defaults: default variables dictionary
    :param fix_config_vars_func: function which gets a loaded variables dictionary as an argument and fixes variables in-place
    :return: dictionary of loaded variables
    """
    config_vars = {}
    if file_name and os.path.exists(file_name):
        # noinspection PyBroadException
        try:
            with open(file_name, 'r', encoding='utf-8') as config_vars_file:
                config_vars = yaml.load(config_vars_file, Loader=Loader)
            if config_vars is None:
                config_vars = {}
            LOG.info('Loaded configuration variables from file: %s', file_name)
        except Exception:  # pylint: disable=broad-except
            LOG.exception('Could not load configuration variables from file: %s', file_name)
    if fix_config_vars_func:
        fix_config_vars_func(config_vars)
    if defaults:
        for key, value in defaults.items():
            if key not in config_vars:
                config_vars[key] = value
    return config_vars


def save_config(file_name, config_vars, do_backup=True):
    if do_backup:
        # noinspection PyBroadException
        try:
            backup_file(file_name)
        except Exception:  # pylint: disable=broad-except
            LOG.exception('Could not make backup from file: %s', file_name)
            return False
    # noinspection PyBroadException
    try:
        with open(file_name, 'w') as config_vars_file:
            config_vars_file.write(yaml.dump(config_vars, Dumper=Dumper))
        LOG.info('Saved vars to file: %s', file_name)
    except Exception:  # pylint: disable=broad-except
        LOG.exception('Could not save vars to file: %s', file_name)
        return False

    return True


def none_to_empty_str(val):
    return '' if val is None else val


def array_none_to_empty_str(arr):
    return foreach(arr, none_to_empty_str)


def array_join_comma(arr):
    return ','.join(arr)


# name -> [modifiers]
PATH_MOD = (realpath_if, none_to_empty_str)
ARRAY_PATH_MOD = (array_realpath_if, array_none_to_empty_str)
OPTIONAL_PATH_MOD = (realpath_auto_if, none_to_empty_str)
ARRAY_OPTIONAL_PATH_MOD = (array_realpath_auto_if, array_none_to_empty_str)
EXPORT_SHELL_VARS = {
    None: (none_to_empty_str,),
    'ANSIBLE_CONFIG': PATH_MOD,
    'CFG_ANSIBLE_INVENTORIES': ARRAY_PATH_MOD,
    'ANSIBLE_ROLES_PATH': PATH_MOD,
    'CFG_VAULT_FILES': ARRAY_PATH_MOD,
    'CFG_VARS_FILES': ARRAY_PATH_MOD,
    'ANSIBLE_FILTER_PLUGINS': PATH_MOD,
    'ANSIBLE_VAULT_PASSWORD_FILE': PATH_MOD,
    'ANSIBLE_PRIVATE_KEY_FILE': PATH_MOD,
    'CFG_ANSIBLE_VAULT_IDS': (array_realpath_vault_id_if, array_none_to_empty_str)
}

CONFIG_PATH_VAR_NAMES = {
    'ANSIBLE_CONFIG', 'ANSIBLE_ROLES_PATH',
    'CFG_VAULT_FILES', 'CFG_VARS_FILES',
    'CFG_ANSIBLE_INVENTORIES',
    'CFG_ANSIBLE_VAULT_PASSWORD_FILES',
    'CFG_USER_SCRIPTS',
    'ANSIBLE_FILTER_PLUGINS',
    'ANSIBLE_PRIVATE_KEY_FILE'
}

CONFIG_ARRAY_VAR_NAMES = {
    'CFG_ANSIBLE_INVENTORIES',
    'CFG_ANSIBLE_VAULT_PASSWORD_FILES',
    'CFG_ANSIBLE_VAULT_IDS',
    'CFG_VAULT_FILES',
    'CFG_VARS_FILES',
    'CFG_USER_SCRIPTS'
}


def fix_path(path, root_dir):
    if path and not os.path.isabs(path):
        return auto_realpath(path, root_dir)
    return path


def fix_path_vars(vars_dict, path_var_names, array_var_names, root_dir):
    for var in path_var_names:
        val = vars_dict.get(var)
        if val:
            is_array = False
            if var in array_var_names:
                if not is_sequence(val):
                    val = [val]
                is_array = True

            if is_array:
                vars_dict[var] = [fix_path(elem, root_dir) for elem in val]
            else:
                vars_dict[var] = fix_path(val, root_dir)
    return vars_dict


def fix_config_path_vars(vars_dict):
    return fix_path_vars(vars_dict,
                         CONFIG_PATH_VAR_NAMES, CONFIG_ARRAY_VAR_NAMES,
                         os.path.dirname(CONFIG_VARS_FILE))


ANSIBLE_PATH_VAR_NAMES = {
    'ansible_private_key_file',
    'ansible_ssh_private_key_file',
    'ansible_public_key_file',
    'ansible_ssh_public_key_file',
    'bastion_ssh_private_key_file'
}


def fix_ansible_path_vars(vars_dict):
    return fix_path_vars(vars_dict, ANSIBLE_PATH_VAR_NAMES, {}, ROOT_DIR)


def convert_single_value_to_list(vars_dict, src_var_name, dest_var_name):
    src_value = vars_dict.get(src_var_name, None)
    if src_value is not None:
        src_values = to_list(src_value)
        dest_values = to_list(vars_dict.get(dest_var_name, None))
        dest_values.extend(src_values)
        vars_dict[dest_var_name] = dest_values
        del vars_dict[src_var_name]


def upgrade_config_vars(vars_dict):
    convert_single_value_to_list(vars_dict, 'ANSIBLE_INVENTORY', 'CFG_ANSIBLE_INVENTORIES')
    convert_single_value_to_list(vars_dict, 'ANSIBLE_VAULT_PASSWORD_FILE', 'CFG_ANSIBLE_VAULT_PASSWORD_FILES')
    convert_single_value_to_list(vars_dict, 'CFG_VAULT_FILE', 'CFG_VAULT_FILES')
    convert_single_value_to_list(vars_dict, 'CFG_VARS_FILE', 'CFG_VARS_FILES')


# https://stackoverflow.com/questions/377017/test-if-executable-exists-in-python
def which(program):
    def is_executable_file(file_path):
        return os.path.isfile(file_path) and os.access(file_path, os.X_OK)

    fpath, _ = os.path.split(program)
    if fpath:
        if is_executable_file(program):
            return program
    else:
        for path in os.getenv("PATH", "").split(os.pathsep):
            exe_file = os.path.join(path, program)
            if is_executable_file(exe_file):
                return exe_file

    return None


class Config(object):  # pylint: disable=too-many-public-methods
    """Config class represents Ansible configuration"""

    def __init__(self, debug_mode=False):  # pylint: disable=too-many-locals,too-many-branches,too-many-statements
        self.debug_mode = debug_mode

        def fix_config_vars(config_vars):
            upgrade_config_vars(config_vars)
            fix_config_path_vars(config_vars)

        # load configuration variables
        self.config_vars = load_config(CONFIG_VARS_FILE, defaults={
            'CFG_ANSIBLE_INVENTORIES': [ANSIBLE_INVENTORY_DIR],
            'CFG_ANSIBLE_VAULT_PASSWORD_FILES': [ANSIBLE_VAULT_PASSWORD_FILE],
            'CFG_ANSIBLE_VAULT_IDS': [],
            'CFG_USER_SCRIPTS': [],
            'ANSIBLE_CONFIG': ANSIBLE_CONFIG,
            'ANSIBLE_FILTER_PLUGINS': ANSIBLE_FILTER_PLUGINS,
            'ANSIBLE_ROLES_PATH': ANSIBLE_ROLES_PATH,
            'CFG_VAULT_FILES': [CFG_VAULT_FILE],
            'CFG_VARS_FILES': [CFG_VARS_FILE]
        }, fix_config_vars_func=fix_config_vars)
        # save initial state
        self._init_config_vars = copy.deepcopy(self.config_vars)

        # load ansible variables
        self.ansible_vars = {}
        for fn in self.get_vars_files():
            vars = load_config(fn, defaults={})
            self.ansible_vars.update(vars)
        self.ansible_vars.pop('ansible_become_pass', None)
        fix_ansible_path_vars(self.ansible_vars)
        # save initial state
        self._init_ansible_vars = copy.deepcopy(self.ansible_vars)

        # compute secure hash for caching
        shash = hashlib.sha256()
        shash.update(repr(self.ansible_vars).encode())
        ansible_vars_hash = shash.hexdigest()
        del shash
        # print(shash.hexdigest(), file=sys.stderr) # DEBUG

        self.ansible_vars_interpolated = None

        ansible_vars_cache_fn = None
        vars_files = []
        vars_files.extend((fn for fn in self.get_vars_files() if fn))
        vars_files.extend((fn for fn in self.get_vault_files() if fn))

        if vars_files:
            ansible_vars_cache_fn = CFG_VARS_CACHE_FILE

            if os.path.exists(ansible_vars_cache_fn):
                # noinspection PyBroadException
                try:
                    with open(ansible_vars_cache_fn, 'r') as cache_file:
                        cache = yaml.load(cache_file, Loader=Loader)
                    cache_hash = cache["hash"]
                    cache_vars = cache["vars"]
                    if cache_hash == ansible_vars_hash:
                        self.ansible_vars_interpolated = cache_vars
                        LOG.info('Loaded cached variables from file: %s', ansible_vars_cache_fn)
                    else:
                        LOG.info('Cache from file %s is invalid', ansible_vars_cache_fn)
                    del cache

                except Exception:  # pylint: disable=broad-except
                    LOG.exception('Could not load cached variables from file: %s',
                                  ansible_vars_cache_fn)

        # Compute interpolated variables

        if self.ansible_vars_interpolated is None:
            if any(os.path.exists(fn) for fn in vars_files):
                self._compute_interpolated_ansible_vars(
                    ansible_vars_hash=ansible_vars_hash,
                    ansible_vars_cache_fn=ansible_vars_cache_fn)
            else:
                # By default interpolated variables are equal to non-interpolated
                self.ansible_vars_interpolated = self.ansible_vars

    def _compute_interpolated_ansible_vars(self, ansible_vars_hash, ansible_vars_cache_fn):
        LOG.debug("Ansible interpolated variables missing, we will try to compute them")
        # By default interpolated variables are equal to non-interpolated
        self.ansible_vars_interpolated = self.ansible_vars
        ansible_var_names = set(self.ansible_vars.keys())
        # ansible_var_names.update(['ansible_user', 'ansible_ssh_user',
        #                          'ansible_private_key_file',
        #                          'ansible_ssh_private_key_file',
        #                          ])
        ansible_var_names.difference_update(['ansible_become_pass'])
        indent = "      "
        vars_struct = ""
        for var_name in ansible_var_names:
            vars_struct += indent + var_name + \
                           ': "{{ lookup(\'vars\', \'' + var_name + '\', default=\'\') }}"\n'
        vars_tmpl = """
- hosts: 127.0.0.1
  connection: local
  gather_facts: false
  vars:
    all_vars:
%s
  pre_tasks:
    - name: Verify Ansible version
      assert:
        that: "ansible_version.full is version('2.5', '>=')"
        msg: "You must update Ansible to at least 2.5"
  tasks:
    - name: Store message to file
      copy:
        content: "{{ all_vars | to_yaml }}"
        dest: "{{ CFG_DEST_FILE }}"
                                """ % (vars_struct,)

        temp_dir = tempfile.mkdtemp(prefix='cmconf-')
        get_vars_playbook_fn = os.path.join(temp_dir, 'get_vars_pb.yaml')
        vars_fn = os.path.join(temp_dir, 'vars.json')
        try:
            with open(get_vars_playbook_fn, 'w') as cache_file:
                cache_file.write(vars_tmpl)

            cmd_args = ['ansible-playbook']
            for inventory in self.get_ansible_inventories():
                cmd_args.extend(['-i', inventory])

            self.add_ansible_vault_password_file_args(cmd_args)
            self.add_ansible_vault_id_args(cmd_args)
            for fn in itertools.chain(self.get_vars_files(), self.get_vault_files()):
                if fn and os.path.exists(fn):
                    cmd_args.extend(['--extra-vars', '@' + fn])
            cmd_args.extend(['--extra-vars', 'CFG_DEST_FILE={}'.format(shlex.quote(vars_fn)),
                             get_vars_playbook_fn])
            LOG.debug("Interpolate loaded variables: %s", " ".join(cmd_args))
            save_cache = False
            try:
                new_env = None
                if self.get_ansible_config():
                    new_env = os.environ.copy()
                    new_env['ANSIBLE_CONFIG'] = self.get_ansible_config()
                subprocess.check_call(cmd_args, env=new_env, stdout=DEVNULL if not self.debug_mode else sys.stderr)
                self.ansible_vars_interpolated = load_config(vars_fn, defaults=self.ansible_vars)
                save_cache = True
            except subprocess.CalledProcessError:
                LOG.exception("Could not interpolate variables")
                LOG.debug("Failed playbook file: %s", vars_tmpl)
            if save_cache:
                # noinspection PyBroadException
                try:
                    # Save variables to cache
                    cache = {
                        "hash": ansible_vars_hash,
                        "vars": self.ansible_vars_interpolated
                    }

                    with open(ansible_vars_cache_fn, 'w') as cache_file:
                        cache_file.write(yaml.dump(cache, Dumper=Dumper))
                    LOG.info('Saved interpolated variables to cache file: %s', ansible_vars_cache_fn)
                except Exception:  # pylint: disable=broad-except
                    LOG.exception("Could not save interpolated variables to cache")

        finally:
            shutil.rmtree(temp_dir)

    @property
    def config_vars_changed(self):
        return self.config_vars != self._init_config_vars

    @property
    def ansible_vars_changed(self):
        return self.ansible_vars != self._init_ansible_vars

    def save(self, do_backup=False):
        if self.config_vars_changed:
            LOG.info('Configuration changed')
            save_config(CONFIG_VARS_FILE, self.config_vars, do_backup=do_backup)
        if self.ansible_vars_changed:
            LOG.info('Ansible configuration changed')
            fn = select_item('Select file to write changed ansible variables: ', self.get_vars_files())
            save_config(fn, self.ansible_vars, do_backup=do_backup)

    def get_ansible_var(self, key, default=None):
        return self.ansible_vars_interpolated.get(key, default)

    def get_config_var(self, key, default=None):
        return self.config_vars.get(key, default)

    def set_config_var(self, key, value):
        self.config_vars[key] = value

    def get_ansible_user(self, default=None):
        user = self.ansible_vars_interpolated.get('ansible_user')
        if user is None:
            user = self.ansible_vars_interpolated.get('ansible_ssh_user', default)
        return user

    def set_ansible_user(self, user):
        self.ansible_vars['ansible_user'] = \
            self.ansible_vars['ansible_ssh_user'] = \
            self.ansible_vars_interpolated['ansible_user'] = \
            self.ansible_vars_interpolated['ansible_ssh_user'] = \
            user

    def get_ansible_private_key_file(self, default=None):
        key_file_name = self.ansible_vars_interpolated.get('ansible_private_key_file')
        if key_file_name is None:
            key_file_name = self.ansible_vars_interpolated.get('ansible_ssh_private_key_file', default)
        key_file_name = fix_path(key_file_name, os.path.dirname(CONFIG_VARS_FILE))
        return key_file_name

    def set_ansible_private_key_file(self, value):
        self.ansible_vars['ansible_private_key_file'] = \
            self.ansible_vars['ansible_ssh_private_key_file'] = \
            self.ansible_vars_interpolated['ansible_private_key_file'] = \
            self.ansible_vars_interpolated['ansible_ssh_private_key_file'] = \
            value

    def get_ansible_config(self):
        return self.get_config_var('ANSIBLE_CONFIG', ANSIBLE_CONFIG)

    def set_ansible_config(self, value):
        self.set_config_var('ANSIBLE_CONFIG', value)

    def get_ansible_inventories(self):
        return self.get_config_var('CFG_ANSIBLE_INVENTORIES', [ANSIBLE_INVENTORY_DIR])

    def get_ansible_inventory_dirs(self, path_separator_at_end=True):
        inventories = self.get_ansible_inventories()
        result = []
        for inventory in inventories:
            if not inventory:
                continue
            inventory = os.path.realpath(inventory)
            # Inventory can be a file or a directory, if it is not a directory we get a dirname of it
            inventory_dir = os.path.dirname(inventory) if not os.path.isdir(inventory) else inventory
            if path_separator_at_end:
                inventory_dir = sep_at_end(inventory_dir)
            result.append(inventory_dir)
        return result

    def set_ansible_inventories(self, value):
        self.set_config_var('CFG_ANSIBLE_INVENTORIES', to_list(value))

    def get_ansible_vault_password_files(self):
        return self.get_config_var('CFG_ANSIBLE_VAULT_PASSWORD_FILES', [ANSIBLE_VAULT_PASSWORD_FILE])

    def set_ansible_vault_password_files(self, value):
        self.set_config_var('CFG_ANSIBLE_VAULT_PASSWORD_FILES', to_list(value))

    def get_ansible_vault_ids(self):
        return self.get_config_var('CFG_ANSIBLE_VAULT_IDS', [])

    def set_ansible_vault_ids(self, value):
        self.set_config_var('CFG_ANSIBLE_VAULT_IDS', to_list(value))

    def get_vault_files(self):
        return self.get_config_var('CFG_VAULT_FILES', [CFG_VAULT_FILE])

    def set_vault_files(self, value):
        self.set_config_var('CFG_VAULT_FILES', to_list(value))

    def get_vars_files(self):
        return self.get_config_var('CFG_VARS_FILES', [CFG_VARS_FILE])

    def set_vars_files(self, value):
        self.set_config_var('CFG_VARS_FILES', to_list(value))

    def add_ansible_vault_password_file_args(self, args):
        for ansible_vault_password_file in self.get_ansible_vault_password_files():
            if os.path.exists(ansible_vault_password_file):
                args.extend(['--vault-password-file', ansible_vault_password_file])
        return args

    def add_ansible_vault_id_args(self, args):
        for ansible_vault_id in self.get_ansible_vault_ids():
            ansible_vault_id = realpath_vault_id_if(ansible_vault_id)
            args.extend(['--vault-id', ansible_vault_id])
        return args

    def has_ansible_vault_password_file(self):
        return any(file_name and os.path.exists(file_name) for file_name in self.get_ansible_vault_password_files())

    def get_user_scripts(self):
        return self.get_config_var('CFG_USER_SCRIPTS', [])

    def set_user_scripts(self, value):
        self.set_config_var('CFG_USER_SCRIPTS', to_list(value))

    def print_info(self):
        indent = ' ' * 33
        delim = ',\n' + indent
        print("""
Current Configuration:

Ansible config file:             {ANSIBLE_CONFIG}
Ansible inventory file(s):       {CFG_ANSIBLE_INVENTORIES}
User config directory:           {CONFIG_DIR}
Ansible vault password file(s):  {CFG_ANSIBLE_VAULT_PASSWORD_FILES}
Ansible vault id(s):             {CFG_ANSIBLE_VAULT_IDS}
Ansible remote user:             {ANSIBLE_REMOTE_USER}
Ansible private SSH key file:    {ANSIBLE_PRIVATE_KEY_FILE}
User's ansible vars file(s):     {CFG_VARS_FILES}
User's ansible vault file(s):    {CFG_VAULT_FILES}
User scripts:                    {CFG_USER_SCRIPTS}
""".format(ANSIBLE_CONFIG=realpath_if(self.get_ansible_config()),
           CFG_ANSIBLE_INVENTORIES=delim.join(array_realpath_if(self.get_ansible_inventories())),
           CONFIG_DIR=realpath_if(CONFIG_DIR),
           CFG_ANSIBLE_VAULT_PASSWORD_FILES=delim.join(array_realpath_if(self.get_ansible_vault_password_files())),
           CFG_ANSIBLE_VAULT_IDS=delim.join(array_realpath_vault_id_if(self.get_ansible_vault_ids())),
           ANSIBLE_REMOTE_USER=self.get_ansible_user(default=''),
           ANSIBLE_PRIVATE_KEY_FILE=realpath_if(self.get_ansible_private_key_file(default='')),
           CFG_VARS_FILES=delim.join(array_realpath_if(self.get_vars_files())),
           CFG_VAULT_FILES=delim.join(array_realpath_if(self.get_vault_files())),
           CFG_USER_SCRIPTS=delim.join(array_realpath_auto_if(self.get_user_scripts()))))

    def print_shell_vars(self, vars_dict):
        inventory_dirs = self.get_ansible_inventory_dirs(path_separator_at_end=True)

        default_modifiers = EXPORT_SHELL_VARS.get(None)
        for key, value in vars_dict.items():
            modifiers = EXPORT_SHELL_VARS.get(key, default_modifiers)
            for modifier in modifiers:
                value = modifier(value)
            output_var = True
            for inventory_dir in inventory_dirs:
                group_vars_dir = sep_at_end(os.path.join(inventory_dir, 'group_vars'))
                host_vars_dir = sep_at_end(os.path.join(inventory_dir, 'host_vars'))

                def check_vars_file(filename):
                    if filename.startswith(group_vars_dir):
                        print('# {} variable or vault file is in group_vars inventory directory'.format(value))
                        return False
                    if filename.startswith(host_vars_dir):
                        print('# {} variable or vault file is in host_vars inventory directory'.format(value))
                        return False
                    return True

                if key in ('CFG_VARS_FILES', 'CFG_VAULT_FILES'):
                    valid_filenames = []
                    for filename in value:
                        if check_vars_file(filename):
                            valid_filenames.append(filename)
                    if len(valid_filenames) == 0:
                        output_var = False
                        break
                    value = valid_filenames
            if output_var:
                if is_sequence(value):
                    print("{}=({})".format(key, ' '.join([shlex.quote(item) for item in value])))
                else:
                    print("{}={}".format(key, shlex.quote(value)))

    def print_shell_config(self):
        self.print_shell_vars(self.config_vars)
        self.print_shell_vars({
            'ANSIBLE_REMOTE_USER': self.get_ansible_user(),
            'ANSIBLE_PRIVATE_KEY_FILE': self.get_ansible_private_key_file()
        })

    def print_yaml_config(self):
        print(yaml.dump(self.config_vars, Dumper=Dumper))

    def has_ansible_vault_files(self):
        return any((vault_fn and os.path.exists(vault_fn)) for vault_fn in self.get_vault_files())

    def run_ansible_vault(self, command, vault_file, extra_cmd_args=None, check_call=False, stderr=None):
        cmd_args = ['ansible-vault', command]
        self.add_ansible_vault_password_file_args(cmd_args)
        self.add_ansible_vault_id_args(cmd_args)
        cmd_args.append(vault_file)
        if extra_cmd_args:
            cmd_args.extend(extra_cmd_args)

        call_func = subprocess.check_call if check_call else subprocess.call

        LOG.debug('Executing ansible-vault: %s', ' '.join(cmd_args))

        stderr = sys.stderr if self.debug_mode else stderr

        if stderr is None:
            result = call_func(cmd_args, env=os.environ)
        else:
            result = call_func(cmd_args, env=os.environ, stderr=stderr)

        LOG.debug('ansible-vault result: %s', result)
        return result


def run_command(command, env=None, cwd=None, stdin=None,  # pylint: disable=too-many-arguments
                get_stdout=True, get_stderr=True):
    """returns triple (returncode, stdout, stderr)
    if get_stdout is False stdout tuple element will be set to None
    if get_stderr is False stderr tuple element will be set to None
    """
    LOG.info('Run command %s in env %s, cwd %s', command, env, cwd)

    myenv = {}
    if env is not None:
        for key, value in env.items():
            myenv[str(key)] = str(value)
    env = myenv

    with tempfile.TemporaryFile(suffix='stdout') as tmp_stdout:
        with tempfile.TemporaryFile(suffix='stderr') as tmp_stderr:
            if isinstance(command, (list, tuple)):
                proc = subprocess.Popen(command,
                                        stdin=stdin,
                                        stdout=tmp_stdout,
                                        stderr=tmp_stderr,
                                        env=env,
                                        cwd=cwd,
                                        universal_newlines=False)
            else:
                proc = subprocess.Popen(command,
                                        stdin=stdin,
                                        stdout=tmp_stdout,
                                        stderr=tmp_stderr,
                                        env=env,
                                        cwd=cwd,
                                        universal_newlines=False,
                                        shell=True)
            status = proc.wait()

            if get_stdout:
                tmp_stdout.flush()
                tmp_stdout.seek(0)
                out = tmp_stdout.read()
            else:
                out = None

            if get_stderr:
                tmp_stderr.flush()
                tmp_stderr.seek(0)
                err = tmp_stderr.read()
            else:
                err = None

    LOG.info('Command %s returned code: %s', command, status)
    return status, out, err


ANSIBLE_VAULT_MAGIC = b'$ANSIBLE_VAULT;'


def is_vault(filename):
    if not os.path.exists(filename):
        return False
    with open(filename, 'rb') as fd:
        s = fd.read(len(ANSIBLE_VAULT_MAGIC))
        return s == ANSIBLE_VAULT_MAGIC


def find_all_vaults(config):
    found_files = set()
    for filename in config.get_vault_files():
        if is_vault(filename):
            found_files.add(filename)
            yield filename

    for inventory in config.get_ansible_inventories():
        if not os.path.isdir(inventory):
            inventory_dir = os.path.dirname(inventory)
        else:
            inventory_dir = inventory
        for root, dirs, files in os.walk(inventory_dir, topdown=False, followlinks=False):
            for name in files:
                filename = os.path.join(root, name)
                if filename not in found_files and is_vault(filename):
                    found_files.add(filename)
                    yield filename


def find_all_vaults_command(config, args):
    for filename in find_all_vaults(config):
        if args.null:
            print(filename, end=chr(0))
        else:
            print(filename)
    return 0


def decrypt_all_vaults_command(config, args):
    for filename in find_all_vaults(config):
        print('Decrypting file', filename)
        config.run_ansible_vault('decrypt', vault_file=filename, check_call=True, stderr=sys.stderr)
    return 0


def select_item(prompt, items, no_query_for_single_item=True):
    if len(items) == 1 and no_query_for_single_item:
        return items[0]
    else:
        for index, item in rlselect(prompt, list(items) + ['Cancel']):
            if item == 'Cancel':
                LOG.error('User canceled the operation')
                return None
            if index >= 0:
                break
    return item


def view_vault_command(config, args):
    vault_files = list(find_all_vaults(config))
    if not vault_files:
        LOG.error("No encrypted ansible vault files found")
        return 1

    vault_fn = select_item('Select ansible vault file to view: ', vault_files)
    if not vault_fn:
        return 1
    return config.run_ansible_vault('view', vault_file=vault_fn, check_call=True)


def decrypt_vault_command(config, args):
    vault_files = list(find_all_vaults(config))
    if not vault_files:
        LOG.error("No ansible vault files found")
        return 1

    vault_fn = select_item('Select ansible vault file to decrypt: ', vault_files)
    if not vault_fn:
        return 1
    return config.run_ansible_vault('decrypt', vault_file=vault_fn, check_call=True)


def encrypt_vault_command(config, args):
    vault_files = [filename for filename in config.get_vault_files()
                   if (os.path.exists(filename) and not is_vault(filename))]
    if not vault_files:
        LOG.error("No unencrypted ansible vault files found")
        return 1

    vault_fn = select_item('Select ansible vault file to encrypt: ', vault_files)
    if not vault_fn:
        return 1
    LOG.info('Encrypt vault file %s', vault_fn)
    extra_cmd_args = []
    encrypt_vault_id = args and getattr(args, 'encrypt_vault_id', None)
    if not encrypt_vault_id and len(config.get_ansible_vault_ids()) > 1:
        encrypt_vault_id = select_item('Select vault id for encryption: ', config.get_ansible_vault_ids())
        if not encrypt_vault_id:
            return 1
        encrypt_vault_id = vault_id_label(encrypt_vault_id)
    if encrypt_vault_id:
        extra_cmd_args.append('--encrypt-vault-id')
        extra_cmd_args.append(encrypt_vault_id)
    return config.run_ansible_vault('encrypt', vault_file=vault_fn, extra_cmd_args=extra_cmd_args, check_call=True)


def edit_vault_command(config, args):
    vault_files = list(find_all_vaults(config))
    if not vault_files:
        if len(config.get_vault_files()) > 0:
            LOG.warning("No configured ansible vault files exist !: %s", config.get_vault_files())
            LOG.warning("I will create it !")
            return create_vault_command(config, args)
        LOG.error("No ansible vault files found")
        return 1

    vault_fn = select_item('Select ansible vault file to edit: ', vault_files)
    if not vault_fn:
        return 1
    return config.run_ansible_vault('edit', vault_file=vault_fn, check_call=True)


def create_vault_command(config, args):
    vault_files = [filename for filename in config.get_vault_files() if not os.path.exists(filename)]
    if not vault_files:
        LOG.error("No ansible vault files configured")
        return 1

    if len(vault_files) == 1:
        vault_fn = vault_files[0]
    else:
        for index, vault_fn in rlselect('Select ansible vault file to create: ', vault_files + ['Cancel']):
            if vault_fn == 'Cancel':
                LOG.error('User canceled the operation')
                return 1
            if index >= 0:
                break
    return config.run_ansible_vault('create', vault_file=vault_fn, check_call=True, stderr=sys.stderr)


def rekey_all_vaults_command(config, args):
    extra_cmd_args = []
    if args.encrypt_vault_id:
        extra_cmd_args.extend(['--encrypt-vault-id', args.encrypt_vault_id])
    if args.new_vault_id:
        extra_cmd_args.extend(['--new-vault-id', args.new_vault_id])
    if args.new_vault_password_file:
        extra_cmd_args.extend(['--new-vault-password-file', args.new_vault_password_file])

    for filename in find_all_vaults(config):
        print('Rekeying file', filename)
        config.run_ansible_vault('rekey', vault_file=filename, extra_cmd_args=extra_cmd_args, check_call=True,
                                 stderr=sys.stderr)

    return 0


def pwgen(pwd_file, pwd_length=20):
    if os.path.exists(pwd_file):
        LOG.error('File %s already exists', pwd_file)
        return False
    LOG.info('Generate password of length %s in the file %s', pwd_length, pwd_file)
    with open(pwd_file, 'w') as f:
        f.write(randpw(pwd_length))
    return True


def pwgen_command(args):
    if pwgen(args.output, args.length):
        return 0
    else:
        return 1


def relpath_command(args):
    base_path = os.path.realpath(args.base_path if args.base_path else ROOT_DIR)
    for path in relpaths(base_path=base_path, paths=args.paths, no_parent_dirs=args.no_parent_dirs):
        if args.null:
            print(path, end=chr(0))
        else:
            print(path)
    return 0


def main():  # pylint: disable=too-many-branches,too-many-statements,too-many-return-statements
    parser = argparse.ArgumentParser(description="Ansible/Kubespray configurator")
    parser.add_argument('--debug', help='debug mode', action="store_true")
    parser.add_argument('--no-backup', help='disable backup', action="store_true")
    parser.add_argument("-i", "--inventory", action='append',
                        help="specify inventory host path or comma separated host list")

    parser.add_argument('--vault', default=[], dest='vault_files', help="vault file", action='append')
    parser.add_argument('--add-vault', default=[], dest='add_vault_files', help="add vault files", action='append')
    parser.add_argument('--remove-vault', default=[], dest='remove_vault_files', help="remove vault files",
                        action='append')

    parser.add_argument('--vars', default=[], dest='vars_files', help="vars file", action='append')
    parser.add_argument('--add-vars', default=[], dest='add_vars_files', help="add vars files", action='append')
    parser.add_argument('--remove-vars', default=[], dest='remove_vars_files', help="remove vars files",
                        action='append')

    parser.add_argument("--pwgen",
                        metavar="FILE",
                        dest="pwd_file",
                        help="generate random password, store to file and exit")
    parser.add_argument("-u", "--user", help="set remote user")
    parser.add_argument("-r", "--reconfigure", help="reconfigure", action="store_true")
    parser.add_argument("-k", "--private-key", help="set private key filename")
    parser.add_argument("--shell-config",
                        help="print configuration variables in Bash-compatible script format and exit",
                        action="store_true")
    parser.add_argument("--yaml-config",
                        help="print configuration variables in YAML format and exit",
                        action="store_true")
    parser.add_argument("--show", help="print info and exit", action="store_true")
    parser.add_argument("-v", "--view-vault", help="view configuration vault and exit", action="store_true")
    parser.add_argument("--decrypt-vault", help="decrypt vault and exit", action="store_true")
    parser.add_argument("--edit-vault", help="edit vault and exit", action="store_true")
    parser.add_argument("--encrypt-vault", help="encrypt vault and exit", action="store_true")
    parser.add_argument('--vault-password-file', default=[], dest='vault_password_files',
                        help="vault password file", action='append')
    parser.add_argument("--add-vault-password-file", default=[], dest='add_vault_password_files',
                        help="add vault password files", action='append')
    parser.add_argument("--remove-vault-password-file", default=[], dest='remove_vault_password_files',
                        help="remove vault password files", action='append')
    parser.set_defaults(func=None)
    parser.set_defaults(func_require_config=True)

    subparsers = parser.add_subparsers(title="subcommands", dest="subcommand", metavar="")

    command_p = subparsers.add_parser("pwgen", help="Generate password and save to file")
    command_p.add_argument("-o", "--output", metavar="FILE",
                           help="password file name")
    command_p.add_argument("-n", "--length", metavar="PASSWORD_LENGTH",
                           type=int, default=20,
                           help="password length")
    command_p.set_defaults(func_require_config=False)
    command_p.set_defaults(func=pwgen_command)

    command_p = subparsers.add_parser("relpath", help="Relativize paths")
    command_p.add_argument("-b", "--base-path",
                           help="base path, by default path to the directory where config.yml is located")
    command_p.add_argument("-p", "--no-parent-dirs", action="store_true",
                           help="Use absolute paths instead of using parent directories (..)")
    command_p.add_argument("-0", "--null", action="store_true",
                           help='''print the full path name on the standard output, followed by a null
    character. This allows path names that  contain newlines or other types of white space to be correctly
    interpreted by programs that process the output. This option corresponds to the -0 option of xargs.''')
    command_p.add_argument("paths", metavar="PATH", nargs='+', help="path to relativize")
    command_p.set_defaults(func_require_config=False)
    command_p.set_defaults(func=relpath_command)

    command_p = subparsers.add_parser("find-all-vaults", help="find all vault files")
    command_p.add_argument("-0", "--null", action="store_true",
                           help='''print the full file name on the standard output, followed by a null
    character. This allows file names that  contain newlines or other types of white space to be correctly
    interpreted by programs that process the output. This option corresponds to the -0 option of xargs.''')
    command_p.set_defaults(func=find_all_vaults_command)

    command_p = subparsers.add_parser("decrypt-all-vaults", help="decrypt all vault files")
    command_p.set_defaults(func=decrypt_all_vaults_command)

    command_p = subparsers.add_parser("encrypt-vault", help="encrypt vault file")
    command_p.add_argument("--encrypt-vault-id", help="the vault id used to encrypt (required if more than vault-id "
                                                      "is provided)")
    command_p.set_defaults(func=encrypt_vault_command)

    command_p = subparsers.add_parser("rekey-vaults", help="rekey all vault files")
    command_p.add_argument("--encrypt-vault-id",
                           help="the vault id used to encrypt (required if more than vault-id is provided)")
    command_p.add_argument("--new-vault-id", help="the new vault identity to use for rekey")
    command_p.add_argument("--new-vault-password-file", help="new vault password file for rekey")
    command_p.set_defaults(func=rekey_all_vaults_command)

    args = parser.parse_args()

    show_config = args.shell_config or args.yaml_config

    if args.debug:
        logging.basicConfig(format='%(asctime)s %(levelname)s %(pathname)s:%(lineno)s: %(message)s',
                            level=logging.DEBUG)
    else:
        logging.basicConfig(format='%(asctime)s %(levelname)s %(message)s',
                            level=logging.INFO if not show_config else logging.WARNING)

    if args.func is not None and not args.func_require_config:
        return args.func(args=args)

    if args.pwd_file:
        if pwgen(args.pwd_file):
            return 0
        else:
            return 1

    # Check for ansible tools
    tool_not_found = False
    for tool in ('ansible', 'ansible-vault', 'ansible-playbook', 'ansible-inventory'):
        tool_path = which(tool)
        if not tool_path:
            LOG.error("Ansible tool '%s' was not found in PATH", tool)
            tool_not_found = True
    if tool_not_found:
        LOG.error("Some Ansible tools were not found in PATH environment variable, either Ansible was not installed "
                  "or it was not added to PATH.")
        LOG.error("PATH: %s", os.getenv("PATH", None))
        return 1

    # Load configuration
    config = Config(debug_mode=args.debug)

    if args.func is not None:
        return args.func(config=config, args=args)

    if not args.inventory:
        args.inventory = array_realpath_if(config.get_ansible_inventories())

    if not args.vars_files:
        args.vars_files = config.get_vars_files()
    if args.remove_vars_files:
        for item in args.remove_vars_files:
            if item in args.vars_files:
                args.vars_files.remove(item)
    if args.add_vars_files:
        for item in args.add_vars_files:
            if item not in args.vars_files:
                args.vars_files.append(item)

    if not args.vault_files:
        args.vault_files = config.get_vault_files()
    if args.remove_vault_files:
        for item in args.remove_vault_files:
            if item in args.vault_files:
                args.vault_files.remove(item)
    if args.add_vault_files:
        for item in args.add_vault_files:
            if item not in args.vault_files:
                args.vault_files.append(item)

    if not args.user:
        args.user = config.get_ansible_user()
    if not args.private_key:
        args.private_key = realpath_if(config.get_ansible_private_key_file())
    if not args.vault_password_files:
        args.vault_password_files = config.get_ansible_vault_password_files()
    if args.remove_vault_password_files:
        for item in args.remove_vault_password_files:
            if item in args.vault_password_files:
                args.vault_password_files.remove(item)
    if args.add_vault_password_files:
        for item in args.add_vault_password_files:
            if item not in args.vault_password_files:
                args.vault_password_files.append(item)

    if args.shell_config:
        config.print_shell_config()
        return 0

    if args.yaml_config:
        config.print_yaml_config()
        return 0

    if args.show:
        config.print_info()
        return 0

    readline.parse_and_bind("tab: complete")

    if args.view_vault:
        return view_vault_command(config, args)

    if args.decrypt_vault:
        return decrypt_vault_command(config, args)

    if args.encrypt_vault:
        return encrypt_vault_command(config, args)

    if args.edit_vault:
        return edit_vault_command(config, args)

    if not os.path.isdir(CONFIG_DIR):
        LOG.info('Create directory: %r', CONFIG_DIR)
        os.makedirs(CONFIG_DIR)

    if not config.has_ansible_vault_password_file():
        found_file_name = None
        for file_name in config.get_ansible_vault_password_files():
            if file_name:
                found_file_name = file_name
                break
        if found_file_name:
            LOG.info('Generate vault password file: %r', found_file_name)
            with open(found_file_name, 'w') as pwd_file:
                pwd_file.write(randpw())

    if args.user:
        config.set_ansible_user(args.user)
    elif args.reconfigure:
        user = rlinput('Remote (SSH) user name: ', config.get_ansible_user())
        config.set_ansible_user(user)

    LOG.info('Ansible user set to %r', config.get_ansible_user())

    if args.private_key:
        config.set_ansible_private_key_file(args.private_key)
        LOG.info('Set ansible private key file to %r', args.private_key)

    if args.inventory:
        if array_realpath_if(args.inventory) != array_realpath_if(config.get_ansible_inventories()):
            config.set_ansible_inventories(args.inventory)
            LOG.info('Set ansible inventory file to %r', args.inventory)

    if args.vault_password_files:
        if array_realpath_if(args.vault_password_files) != array_realpath_if(config.get_ansible_vault_password_files()):
            config.set_ansible_vault_password_files(args.vault_password_files)
            LOG.info('Set ansible vault password files to %r', args.vault_password_files)

    if args.vault_files:
        if array_realpath_if(args.vault_files) != array_realpath_if(config.get_vault_files()):
            config.set_vault_files(args.vault_files)
            LOG.info("Set user's ansible vault files to %r", args.vault_files)

    if args.vars_files:
        if array_realpath_if(args.vars_files) != array_realpath_if(config.get_vars_files()):
            config.set_vars_files(args.vars_files)
            LOG.info("Set user's ansible vars files to %r", args.vars_files)

    if args.reconfigure:
        count = 0
        while True:
            if count > 2:
                print("Have exhausted maximum number of retries", file=sys.stderr)
                return 1
            sudo_pass_1 = getpass.getpass("Sudo password: ")
            sudo_pass_2 = getpass.getpass("Retype sudo password: ")
            if sudo_pass_1 != sudo_pass_2:
                print("Sorry, passwords do not match", file=sys.stderr)
            else:
                break
            count += 1
        vault_data = {
            "ansible_become_pass": sudo_pass_1
        }
        vault_filename = select_item('Select vault file to write password to: ', config.get_vault_files())
        if vault_filename is None:
            return 1
        with open(vault_filename, 'w') as vault_file:
            vault_file.write(yaml.dump(vault_data, Dumper=Dumper))
        LOG.info('Wrote sudo password to vault file: %s', vault_filename)

    for vault_filename in config.get_vault_files():
        if not is_vault(vault_filename):
            LOG.warning('Vault file {} is configured, but not encrypted ! Execute the command "ansible-vault encrypt" '
                        'to encrypt it !'.format(vault_filename))
            # config.run_ansible_vault('encrypt', check_call=False, stderr=DEVNULL)

    config.save(do_backup=not args.no_backup)

    LOG.info('Configuration finished')

    config.print_info()

    return 0


if __name__ == "__main__":
    sys.exit(main())
