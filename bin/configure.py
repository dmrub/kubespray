#!/usr/bin/env python

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
from six import iteritems
from six.moves import input
from six.moves import shlex_quote
import yaml

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


def randpw(size=16, chars='_' + string.ascii_uppercase + string.ascii_lowercase + string.digits):
    return ''.join(random.SystemRandom().choice(chars) for _ in range(size))


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
    if os.path.exists(file_name):
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
        for key, value in iteritems(defaults):
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
EXPORT_SHELL_VARS = {
    None: (none_to_empty_str,),
    'ANSIBLE_CONFIG': PATH_MOD,
    'CFG_ANSIBLE_INVENTORIES': ARRAY_PATH_MOD,
    'ANSIBLE_ROLES_PATH': PATH_MOD,
    'CFG_VAULT_FILE': PATH_MOD,
    'CFG_VARS_FILE': PATH_MOD,
    'ANSIBLE_FILTER_PLUGINS': PATH_MOD,
    'ANSIBLE_VAULT_PASSWORD_FILE': PATH_MOD,
    'ANSIBLE_PRIVATE_KEY_FILE': PATH_MOD,
}

CONFIG_PATH_VAR_NAMES = {
    'ANSIBLE_CONFIG', 'ANSIBLE_ROLES_PATH',
    'CFG_VAULT_FILE', 'CFG_VARS_FILE', 'CFG_ANSIBLE_INVENTORIES',
    'CFG_ANSIBLE_VAULT_PASSWORD_FILES',
    'ANSIBLE_FILTER_PLUGINS',
    'ANSIBLE_PRIVATE_KEY_FILE'
}

CONFIG_ARRAY_VAR_NAMES = {
    'CFG_ANSIBLE_INVENTORIES',
    'CFG_ANSIBLE_VAULT_PASSWORD_FILES'
}


def fix_path(path, root_dir):
    if path and not os.path.isabs(path):
        return os.path.realpath(os.path.join(root_dir, path))
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


# https://stackoverflow.com/questions/377017/test-if-executable-exists-in-python
def which(program):
    def is_executable_file(file_path):
        return os.path.isfile(file_path) and os.access(file_path, os.X_OK)

    fpath, _ = os.path.split(program)
    if fpath:
        if is_executable_file(program):
            return program
    else:
        for path in os.environ["PATH"].split(os.pathsep):
            exe_file = os.path.join(path, program)
            if is_executable_file(exe_file):
                return exe_file

    return None


class Config(object):  # pylint: disable=too-many-public-methods
    """Config class represents Ansible configuration"""

    def __init__(self, debug_mode=False): # pylint: disable=too-many-locals,too-many-branches,too-many-statements
        self.debug_mode = debug_mode

        def fix_config_vars(config_vars):
            upgrade_config_vars(config_vars)
            fix_config_path_vars(config_vars)

        # load configuration variables
        self.config_vars = load_config(CONFIG_VARS_FILE, defaults={
            'CFG_ANSIBLE_INVENTORIES': [ANSIBLE_INVENTORY_DIR],
            'CFG_ANSIBLE_VAULT_PASSWORD_FILES': [ANSIBLE_VAULT_PASSWORD_FILE],
            'ANSIBLE_CONFIG': ANSIBLE_CONFIG,
            'ANSIBLE_FILTER_PLUGINS': ANSIBLE_FILTER_PLUGINS,
            'ANSIBLE_ROLES_PATH': ANSIBLE_ROLES_PATH,
            'CFG_VAULT_FILE': CFG_VAULT_FILE,
            'CFG_VARS_FILE': CFG_VARS_FILE
        }, fix_config_vars_func=fix_config_vars)
        # save initial state
        self._init_config_vars = copy.deepcopy(self.config_vars)

        # load ansible variables
        self.ansible_vars = load_config(self.get_vars_file(), defaults={})
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

        ansible_vars_cache_fn = self.get_vars_file() + ".cache"

        self.ansible_vars_interpolated = None

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

                args = ['ansible-playbook']
                for inventory in self.get_ansible_inventories():
                    args.extend(['-i', inventory])

                self.add_ansible_vault_password_file_args(args)

                if os.path.exists(self.get_vault_file()):
                    args.extend(['--extra-vars', '@' + self.get_vault_file()])
                if os.path.exists(self.get_vars_file()):
                    args.extend(['--extra-vars', '@' + self.get_vars_file()])
                args.extend(['--extra-vars', 'CFG_DEST_FILE={}'.format(shlex_quote(vars_fn)),
                             get_vars_playbook_fn])
                LOG.debug("Interpolate loaded variables: %s", " ".join(args))
                save_cache = False
                try:
                    subprocess.check_call(args, stdout=DEVNULL if not self.debug_mode else sys.stderr)
                    self.ansible_vars_interpolated = load_config(vars_fn, defaults=self.ansible_vars)
                    save_cache = True
                except subprocess.CalledProcessError:
                    LOG.exception("Could not interpolate variables")
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
            save_config(self.get_vars_file(), self.ansible_vars, do_backup=do_backup)

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

    def get_vault_file(self):
        return self.get_config_var('CFG_VAULT_FILE')

    def set_vault_file(self, value):
        self.set_config_var('CFG_VAULT_FILE', value)

    def get_vars_file(self):
        return self.get_config_var('CFG_VARS_FILE')

    def set_vars_file(self, value):
        self.set_config_var('CFG_VARS_FILE', value)

    def add_ansible_vault_password_file_args(self, args):
        for ansible_vault_password_file in self.get_ansible_vault_password_files():
            if os.path.exists(ansible_vault_password_file):
                args.extend(['--vault-password-file', ansible_vault_password_file])
        return args

    def has_ansible_vault_password_file(self):
        return any(file_name and os.path.exists(file_name) for file_name in self.get_ansible_vault_password_files())

    def print_info(self):
        print("""
Current Configuration:

Ansible config file:             {ANSIBLE_CONFIG}
Ansible inventory file(s):       {CFG_ANSIBLE_INVENTORIES}
User config directory:           {CONFIG_DIR}
Ansible vault password file(s):  {CFG_ANSIBLE_VAULT_PASSWORD_FILES}
Ansible remote user:             {ANSIBLE_REMOTE_USER}
Ansible private SSH key file:    {ANSIBLE_PRIVATE_KEY_FILE}
User's ansible vars file:        {CFG_VARS_FILE}
User's ansible vault file:       {CFG_VAULT_FILE}
""".format(ANSIBLE_CONFIG=realpath_if(self.get_ansible_config()),
           CFG_ANSIBLE_INVENTORIES=', '.join(array_realpath_if(self.get_ansible_inventories())),
           CONFIG_DIR=realpath_if(CONFIG_DIR),
           CFG_ANSIBLE_VAULT_PASSWORD_FILES=', '.join(array_realpath_if(self.get_ansible_vault_password_files())),
           ANSIBLE_REMOTE_USER=self.get_ansible_user(default=''),
           ANSIBLE_PRIVATE_KEY_FILE=realpath_if(self.get_ansible_private_key_file(default='')),
           CFG_VARS_FILE=realpath_if(self.get_vars_file()),
           CFG_VAULT_FILE=realpath_if(self.get_vault_file())))

    def print_shell_vars(self, vars_dict):
        inventory_dirs = self.get_ansible_inventory_dirs(path_separator_at_end=True)

        default_modifiers = EXPORT_SHELL_VARS.get(None)
        for key, value in iteritems(vars_dict):
            modifiers = EXPORT_SHELL_VARS.get(key, default_modifiers)
            for modifier in modifiers:
                value = modifier(value)
            output_var = True
            for inventory_dir in inventory_dirs:
                group_vars_dir = sep_at_end(os.path.join(inventory_dir, 'group_vars'))
                host_vars_dir = sep_at_end(os.path.join(inventory_dir, 'host_vars'))

                if key in ('CFG_VARS_FILE', 'CFG_VAULT_FILE'):
                    if value.startswith(group_vars_dir):
                        print('# {} variable or vault file is in group_vars inventory directory'.format(value))
                        output_var = False
                        break
                    if value.startswith(host_vars_dir):
                        print('# {} variable or vault file is in host_vars inventory directory'.format(value))
                        output_var = False
                        break
            if output_var:
                if is_sequence(value):
                    print("{}=({})".format(key, ' '.join([shlex_quote(item) for item in value])))
                else:
                    print("{}={}".format(key, shlex_quote(value)))

    def print_shell_config(self):
        self.print_shell_vars(self.config_vars)
        self.print_shell_vars({
            'ANSIBLE_REMOTE_USER': self.get_ansible_user(),
            'ANSIBLE_PRIVATE_KEY_FILE': self.get_ansible_private_key_file()
        })

    def print_yaml_config(self):
        print(yaml.dump(self.config_vars, Dumper=Dumper))

    def has_ansible_vault_files(self):
        vault_fn = self.get_vault_file()
        if vault_fn and os.path.exists(vault_fn):
            return True
        return False

    def run_ansible_vault(self, command, check_call=False, stderr=None):
        cmd_args = ['ansible-vault', command]
        self.add_ansible_vault_password_file_args(cmd_args)
        cmd_args.append(self.get_vault_file())

        call_func = subprocess.check_call if check_call else subprocess.call

        LOG.debug('Executing ansible-vault: %s', ' '.join(cmd_args))

        stderr = sys.stderr if self.debug_mode else stderr

        if stderr is None:
            result = call_func(cmd_args, env=os.environ)
        else:
            result = call_func(cmd_args, env=os.environ, stderr=stderr)

        LOG.debug('ansible-vault result: %s', result)
        return result

def run_command(command, env=None, cwd=None, stdin=None,   # pylint: disable=too-many-arguments
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


def main():  # pylint: disable=too-many-branches,too-many-statements,too-many-return-statements
    parser = argparse.ArgumentParser(description="Ansible/Kubespray configurator")
    parser.add_argument('--debug', help='debug mode', action="store_true")
    parser.add_argument('--no-backup', help='disable backup', action="store_true")
    parser.add_argument("-i", "--inventory", action='append',
                        help="specify inventory host path or comma separated host list")
    parser.add_argument("--vault", help="set user's vault file")
    parser.add_argument("--vars", help="set user's vars file")
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

    args = parser.parse_args()

    show_config = args.shell_config or args.yaml_config

    if args.debug:
        logging.basicConfig(format='%(asctime)s %(levelname)s %(pathname)s:%(lineno)s: %(message)s',
                            level=logging.DEBUG)
    else:
        logging.basicConfig(format='%(asctime)s %(levelname)s %(message)s',
                            level=logging.INFO if not show_config else logging.WARNING)

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
        LOG.error("PATH: %s", os.environ["PATH"])
        return 1

    config = Config(debug_mode=args.debug)

    if not args.inventory:
        args.inventory = array_realpath_if(config.get_ansible_inventories())
    if not args.vault:
        args.vault = realpath_if(config.get_vault_file())
    if not args.vars:
        args.vars = realpath_if(config.get_vars_file())
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
        vault_fn = config.get_vault_file()
        if not vault_fn:
            LOG.error("No ansible vault file is configured")
            return 1
        if not os.path.exists(vault_fn):
            LOG.error("Ansible vault file %s doesn't exist !", vault_fn)
            LOG.error("Run --edit-vault command.")
            return 1
        return config.run_ansible_vault('view', check_call=True)

    if args.decrypt_vault:
        vault_fn = config.get_vault_file()
        if not vault_fn:
            LOG.error("No ansible vault file is configured")
            return 1
        if not os.path.exists(vault_fn):
            LOG.error("Ansible vault file %s doesn't exist !", vault_fn)
            LOG.error("Run --edit-vault command.")
            return 1
        return config.run_ansible_vault('decrypt', check_call=True)

    if args.encrypt_vault:
        vault_fn = config.get_vault_file()
        if not vault_fn:
            LOG.error("No ansible vault file is configured")
            return 1
        if not os.path.exists(vault_fn):
            LOG.error("Ansible vault file %s doesn't exist !", vault_fn)
            LOG.error("Run --edit-vault command.")
            return 1
        return config.run_ansible_vault('encrypt', check_call=False, stderr=DEVNULL)

    if args.edit_vault:
        vault_fn = config.get_vault_file()
        if not vault_fn:
            LOG.error("No ansible vault file is configured")
            return 1
        if not os.path.exists(vault_fn):
            LOG.warning("Ansible vault file %s doesn't exist !", vault_fn)
            LOG.warning("I will create it !")
            return config.run_ansible_vault('create', check_call=True)
        else:
            return config.run_ansible_vault('edit', check_call=True)

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

    if args.vault:
        if realpath_if(args.vault) != realpath_if(config.get_vault_file()):
            config.set_vault_file(args.vault)
            LOG.info("Set user's ansible vault file to %r", args.vault)

    if args.vars:
        if realpath_if(args.vars) != realpath_if(config.get_vars_file()):
            config.set_vars_file(args.vars)
            LOG.info("Set user's ansible vars file to %r", args.vars)

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
        with open(config.get_vault_file(), 'w') as vault_file:
            vault_file.write(yaml.dump(vault_data, Dumper=Dumper))
        LOG.info('Wrote sudo password to vault file')

    if os.path.exists(config.get_vault_file()):
        config.run_ansible_vault('encrypt', check_call=False, stderr=DEVNULL)

    config.save(do_backup=not args.no_backup)

    LOG.info('Configuration finished')

    config.print_info()

    return 0


if __name__ == "__main__":
    sys.exit(main())
