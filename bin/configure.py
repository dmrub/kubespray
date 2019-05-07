#!/usr/bin/env python
from __future__ import print_function

import argparse
import copy
import getpass
import logging
import random
import readline
import shutil
import string
import subprocess
import sys
import tempfile
import hashlib
import os.path
from six import iteritems
from six.moves import input
from six.moves import shlex_quote
from yaml import load, dump

try:
    from subprocess import DEVNULL  # py3k
except ImportError:
    import os

    DEVNULL = open(os.devnull, 'wb')

try:
    from yaml import CLoader as Loader, CDumper as Dumper
except ImportError:
    from yaml import Loader, Dumper

import difflib
import pprint


def diff_dicts(a, b):
    if a == b:
        return ''
    return '\n'.join(
        difflib.ndiff(pprint.pformat(a, width=70).splitlines(),
                      pprint.pformat(b, width=70).splitlines())
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
ANSIBLE_INVENTORY = os.path.join(ANSIBLE_INVENTORY_DIR, 'inventory.cfg')
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


def rlinput(prompt, prefill=''):
    readline.set_startup_hook(lambda: readline.insert_text(prefill))
    try:
        return input(prompt)
    finally:
        readline.set_startup_hook()


def randpw(size=16, chars='_' + string.ascii_uppercase + string.ascii_lowercase + string.digits):
    return ''.join(random.SystemRandom().choice(chars) for _ in range(size))


def realpath_if(path):
    if path:
        return os.path.realpath(path)
    return path


def dirname_if(path):
    if path:
        return os.path.dirname(path)
    return path


def sep_at_end(path):
    if not path.endswith(os.sep):
        path += os.sep
    return path


def backup_file(path):
    rpath = os.path.realpath(path)
    if os.path.exists(rpath):
        bak_rpath = rpath + "~"
        while os.path.exists(bak_rpath):
            bak_rpath += "~"
        LOG.info('Backup file %s to file %s', rpath, bak_rpath)
        os.rename(rpath, bak_rpath)


def load_config(file_name, defaults=None):
    config_vars = {}
    if os.path.exists(file_name):
        try:
            with open(file_name, 'r') as fd:
                config_vars = load(fd, Loader=Loader)
            if config_vars is None:
                config_vars = {}
            LOG.info('Loaded configuration variables from file: %s', file_name)
        except Exception:
            LOG.exception('Could not load configuration variables from file: %s', file_name)
    if defaults:
        for k, v in iteritems(defaults):
            if k not in config_vars:
                config_vars[k] = v
    return config_vars


def save_config(file_name, config_vars, do_backup=True):
    if do_backup:
        try:
            backup_file(file_name)
        except Exception:
            LOG.exception('Could not make backup from file: %s', file_name)
            return False

    try:
        with open(file_name, 'w') as fd:
            fd.write(dump(config_vars, Dumper=Dumper))
        LOG.info('Saved vars to file: %s', file_name)
    except Exception:
        LOG.exception('Could not save vars to file: %s', file_name)
        return False

    return True


def none_to_empty_str(val):
    return '' if val is None else val


# name -> [modifiers]
PATH_MOD = (realpath_if, none_to_empty_str)
EXPORT_SHELL_VARS = {
    None: (none_to_empty_str,),
    'ANSIBLE_CONFIG': PATH_MOD,
    'ANSIBLE_INVENTORY': PATH_MOD,
    'ANSIBLE_ROLES_PATH': PATH_MOD,
    'CFG_VAULT_FILE': PATH_MOD,
    'CFG_VARS_FILE': PATH_MOD,
    'ANSIBLE_FILTER_PLUGINS': PATH_MOD,
    'ANSIBLE_VAULT_PASSWORD_FILE': PATH_MOD,
    'ANSIBLE_PRIVATE_KEY_FILE': PATH_MOD,
}

CONFIG_PATH_VAR_NAMES = {
    'ANSIBLE_CONFIG', 'ANSIBLE_INVENTORY', 'ANSIBLE_ROLES_PATH', 'CFG_VAULT_FILE', 'CFG_VARS_FILE',
    'ANSIBLE_FILTER_PLUGINS', 'ANSIBLE_VAULT_PASSWORD_FILE', 'ANSIBLE_PRIVATE_KEY_FILE'
}


def fix_path(path, root_dir):
    if path and not os.path.isabs(path):
        return os.path.realpath(os.path.join(root_dir, path))
    else:
        return path


def fix_path_vars(vars_dict, path_var_names, root_dir):
    for var in path_var_names:
        val = vars_dict.get(var)
        if val and not os.path.isabs(val):
            vars_dict[var] = os.path.realpath(os.path.join(root_dir, val))
    return vars_dict


def fix_config_path_vars(vars_dict):
    return fix_path_vars(vars_dict, CONFIG_PATH_VAR_NAMES, os.path.dirname(CONFIG_VARS_FILE))


ANSIBLE_PATH_VAR_NAMES = {
    'ansible_private_key_file',
    'ansible_ssh_private_key_file',
    'ansible_public_key_file',
    'ansible_ssh_public_key_file',
    'bastion_ssh_private_key_file'
}


def fix_ansible_path_vars(vars_dict):
    return fix_path_vars(vars_dict, ANSIBLE_PATH_VAR_NAMES, ROOT_DIR)


class Config(object):

    def __init__(self, debug_mode=False):
        self.debug_mode = debug_mode

        # load configuration variables
        self.config_vars = load_config(CONFIG_VARS_FILE, defaults={
            'ANSIBLE_INVENTORY': ANSIBLE_INVENTORY,
            'ANSIBLE_VAULT_PASSWORD_FILE': ANSIBLE_VAULT_PASSWORD_FILE,
            'ANSIBLE_CONFIG': ANSIBLE_CONFIG,
            'ANSIBLE_FILTER_PLUGINS': ANSIBLE_FILTER_PLUGINS,
            'ANSIBLE_ROLES_PATH': ANSIBLE_ROLES_PATH,
            'CFG_VAULT_FILE': CFG_VAULT_FILE,
            'CFG_VARS_FILE': CFG_VARS_FILE
        })
        fix_config_path_vars(self.config_vars)
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
        shash.update(repr(self.ansible_vars))
        ansible_vars_hash = shash.hexdigest()
        del shash
        # print(shash.hexdigest(), file=sys.stderr) # DEBUG

        ansible_vars_cache_fn = self.get_vars_file() + ".cache"

        self.ansible_vars_interpolated = None

        if os.path.exists(ansible_vars_cache_fn):
            try:
                with open(ansible_vars_cache_fn, 'r') as fd:
                    cache = load(fd, Loader=Loader)
                cache_hash = cache["hash"]
                cache_vars = cache["vars"]
                if cache_hash == ansible_vars_hash:
                    self.ansible_vars_interpolated = cache_vars
                    LOG.info('Loaded cached variables from file: %s', ansible_vars_cache_fn)
                else:
                    LOG.info('Cache from file %s is invalid', ansible_vars_cache_fn)
                del cache

            except Exception:
                LOG.exception('Could not load cached variables from file: %s', ansible_vars_cache_fn)

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
            for vn in ansible_var_names:
                vars_struct += indent + vn + ': "{{ lookup(\'vars\', \'' + vn + '\', default=\'\') }}"\n'
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
                with open(get_vars_playbook_fn, 'w') as fd:
                    fd.write(vars_tmpl)

                args = ['ansible-playbook', '-i', self.get_ansible_inventory()]
                if os.path.exists(self.get_ansible_vault_password_file()):
                    args.extend(['--vault-password-file', self.get_ansible_vault_password_file()])
                if os.path.exists(self.get_vault_file()):
                    args.extend(['--extra-vars', '@' + self.get_vault_file()])
                if os.path.exists(self.get_vars_file()):
                    args.extend(['--extra-vars', '@' + self.get_vars_file()])
                args.extend(['--extra-vars', 'CFG_DEST_FILE={}'.format(shlex_quote(vars_fn)),
                             get_vars_playbook_fn
                             ])
                LOG.debug("Interpolate loaded variables: %s", " ".join(args))
                save_cache = False
                try:
                    subprocess.check_call(args, stdout=DEVNULL if not self.debug_mode else sys.stderr)
                    self.ansible_vars_interpolated = load_config(vars_fn, defaults=self.ansible_vars)
                    save_cache = True
                except subprocess.CalledProcessError as e:
                    LOG.exception("Could not interpolate variables")
                if save_cache:
                    try:
                        # Save variables to cache
                        cache = {
                            "hash": ansible_vars_hash,
                            "vars": self.ansible_vars_interpolated
                        }

                        with open(ansible_vars_cache_fn, 'w') as fd:
                            fd.write(dump(cache, Dumper=Dumper))
                        LOG.info('Saved interpolated variables to cache file: %s', ansible_vars_cache_fn)
                    except Exception:
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
        f = self.ansible_vars_interpolated.get('ansible_private_key_file')
        if f is None:
            f = self.ansible_vars_interpolated.get('ansible_ssh_private_key_file', default)
        f = fix_path(f, os.path.dirname(CONFIG_VARS_FILE))
        return f

    def set_ansible_private_key_file(self, value):
        self.ansible_vars['ansible_private_key_file'] = \
            self.ansible_vars['ansible_ssh_private_key_file'] = \
            self.ansible_vars_interpolated['ansible_private_key_file'] = \
            self.ansible_vars_interpolated['ansible_ssh_private_key_file'] = \
            value

    def get_ansible_inventory(self):
        return self.get_config_var('ANSIBLE_INVENTORY', ANSIBLE_INVENTORY)

    def set_ansible_inventory(self, value):
        self.set_config_var('ANSIBLE_INVENTORY', value)

    def get_ansible_vault_password_file(self):
        return self.get_config_var('ANSIBLE_VAULT_PASSWORD_FILE')

    def get_vault_file(self):
        return self.get_config_var('CFG_VAULT_FILE')

    def set_vault_file(self, value):
        self.set_config_var('CFG_VAULT_FILE', value)

    def get_vars_file(self):
        return self.get_config_var('CFG_VARS_FILE')

    def set_vars_file(self, value):
        self.set_config_var('CFG_VARS_FILE', value)

    def print_info(self):
        print("""
Current Configuration:

Ansible inventory file:        {ANSIBLE_INVENTORY}
User config directory:         {CONFIG_DIR}
Ansible vault password file:   {ANSIBLE_VAULT_PASSWORD_FILE}
Ansible remote user:           {ANSIBLE_REMOTE_USER}
Ansible private SSH key file:  {ANSIBLE_PRIVATE_KEY_FILE}
User's ansible vars file:      {CFG_VARS_FILE}
User's ansible vault file:     {CFG_VAULT_FILE}
""".format(
            ANSIBLE_INVENTORY=os.path.realpath(self.get_ansible_inventory()),
            CONFIG_DIR=realpath_if(CONFIG_DIR),
            ANSIBLE_VAULT_PASSWORD_FILE=realpath_if(self.get_config_var('ANSIBLE_VAULT_PASSWORD_FILE')),
            ANSIBLE_REMOTE_USER=self.get_ansible_user(default=''),
            ANSIBLE_PRIVATE_KEY_FILE=realpath_if(self.get_ansible_private_key_file(default='')),
            CFG_VARS_FILE=realpath_if(self.get_vars_file()),
            CFG_VAULT_FILE=realpath_if(self.get_vault_file())
        ))

    def print_shell_vars(self, vars):
        inventory_dir = sep_at_end(realpath_if(dirname_if(self.get_ansible_inventory())))
        group_vars_dir = sep_at_end(os.path.join(inventory_dir, 'group_vars'))
        host_vars_dir = sep_at_end(os.path.join(inventory_dir, 'host_vars'))

        default_modif = EXPORT_SHELL_VARS.get(None)
        for k, v in iteritems(vars):
            modif = EXPORT_SHELL_VARS.get(k, default_modif)
            for mf in modif:
                v = mf(v)
            if k in ('CFG_VARS_FILE', 'CFG_VAULT_FILE'):
                if v.startswith(group_vars_dir):
                    print('# {} variable or vault file is in group_vars inventory directory'.format(v))
                    continue
                if v.startswith(host_vars_dir):
                    print('# {} variable or vault file is in host_vars inventory directory'.format(v))
                    continue

            print("{}={}".format(k, shlex_quote(v)))

    def print_shell_config(self):
        self.print_shell_vars(self.config_vars)
        self.print_shell_vars({
            'ANSIBLE_REMOTE_USER': self.get_ansible_user(),
            'ANSIBLE_PRIVATE_KEY_FILE': self.get_ansible_private_key_file()
        })


def run_command(command, env=None, cwd=None, stdin=None,
                get_stdout=True, get_stderr=True):
    """returns triple (returncode, stdout, stderr)
    if get_stdout is False stdout tuple element will be set to None
    if get_stderr is False stderr tuple element will be set to None
    """
    LOG.info('Run command {} in env {}, cwd {}'.format(command, env, cwd))

    myenv = {}
    if env is not None:
        for k, v in env.items():
            myenv[str(k)] = str(v)
    env = myenv

    with tempfile.TemporaryFile(suffix='stdout') as tmp_stdout:
        with tempfile.TemporaryFile(suffix='stderr') as tmp_stderr:
            if isinstance(command, list) or isinstance(command, tuple):
                p = subprocess.Popen(command,
                                     stdin=stdin,
                                     stdout=tmp_stdout,
                                     stderr=tmp_stderr,
                                     env=env,
                                     cwd=cwd,
                                     universal_newlines=False)
            else:
                p = subprocess.Popen(command,
                                     stdin=stdin,
                                     stdout=tmp_stdout,
                                     stderr=tmp_stderr,
                                     env=env,
                                     cwd=cwd,
                                     universal_newlines=False,
                                     shell=True)
            status = p.wait()

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

    LOG.info('Command {} returned code: {}'.format(command, status))
    return status, out, err


def main():
    global LOG

    parser = argparse.ArgumentParser(description="Kubespray configurator")
    parser.add_argument('--debug', help='debug mode', action="store_true")
    parser.add_argument('--no-backup', help='disable backup', action="store_true")
    parser.add_argument("-i", "--inventory", help="set inventory")
    parser.add_argument("--vault", help="set user's vault file")
    parser.add_argument("--vars", help="set user's vars file")
    parser.add_argument("-u", "--user", help="set remote user")
    parser.add_argument("-r", "--reconfigure", help="reconfigure", action="store_true")
    parser.add_argument("-k", "--private-key", help="set private key filename")
    parser.add_argument("--shell-config", help="print shell configuration", action="store_true")
    parser.add_argument("--show", help="print info and exit", action="store_true")
    parser.add_argument("-v", "--view-vault", help="view configuration vault and exit", action="store_true")
    parser.add_argument("--decrypt-vault", help="decrypt vault and exit", action="store_true")
    parser.add_argument("--edit-vault", help="edit vault and exit", action="store_true")
    parser.add_argument("--encrypt-vault", help="encrypt vault and exit", action="store_true")
    args = parser.parse_args()

    if args.debug:
        logging.basicConfig(format='%(asctime)s %(levelname)s %(pathname)s:%(lineno)s: %(message)s',
                            level=logging.DEBUG)
    else:
        logging.basicConfig(format='%(asctime)s %(levelname)s %(message)s',
                            level=logging.INFO if not args.shell_config else logging.WARNING)

    config = Config(debug_mode=args.debug)

    if not args.inventory:
        args.inventory = realpath_if(config.get_ansible_inventory())
    if not args.vault:
        args.vault = realpath_if(config.get_vault_file())
    if not args.vars:
        args.vars = realpath_if(config.get_vars_file())
    if not args.user:
        args.user = config.get_ansible_user()
    if not args.private_key:
        args.private_key = realpath_if(config.get_ansible_private_key_file())

    if args.shell_config:
        config.print_shell_config()
        return 0

    if args.show:
        config.print_info()
        return 0

    readline.parse_and_bind("tab: complete")

    if args.view_vault:
        os.environ['ANSIBLE_VAULT_PASSWORD_FILE'] = config.get_ansible_vault_password_file()
        return subprocess.check_call(['ansible-vault', 'view', config.get_vault_file()], env=os.environ)

    if args.decrypt_vault:
        os.environ['ANSIBLE_VAULT_PASSWORD_FILE'] = config.get_ansible_vault_password_file()
        return subprocess.check_call(['ansible-vault', 'decrypt', config.get_vault_file()], env=os.environ)

    if args.encrypt_vault:
        os.environ['ANSIBLE_VAULT_PASSWORD_FILE'] = config.get_ansible_vault_password_file()
        return subprocess.call(['ansible-vault', 'encrypt', config.get_vault_file()], env=os.environ, stderr=DEVNULL)

    if args.edit_vault:
        os.environ['ANSIBLE_VAULT_PASSWORD_FILE'] = config.get_ansible_vault_password_file()
        return subprocess.call(['ansible-vault', 'edit', config.get_vault_file()], env=os.environ, stderr=DEVNULL)

    if not os.path.isdir(CONFIG_DIR):
        LOG.info('Create directory: %r', CONFIG_DIR)
        os.makedirs(CONFIG_DIR)

    if not os.path.exists(config.get_ansible_vault_password_file()):
        LOG.info('Generate vault password file: %r', config.get_ansible_vault_password_file())
        with open(config.get_ansible_vault_password_file(), 'w') as fd:
            fd.write(randpw())

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
        if realpath_if(args.inventory) != realpath_if(config.get_ansible_inventory()):
            config.set_ansible_inventory(args.inventory)
            LOG.info('Set ansible inventory file to %r', args.inventory)

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
        with open(config.get_vault_file(), 'w') as fd:
            fd.write(dump(vault_data, Dumper=Dumper))
        LOG.info('Wrote sudo password to vault file')

    if os.path.exists(config.get_vault_file()):
        os.environ['ANSIBLE_VAULT_PASSWORD_FILE'] = config.get_ansible_vault_password_file()
        subprocess.call(['ansible-vault', 'encrypt', config.get_vault_file()], env=os.environ, stderr=DEVNULL)
        LOG.info('Encrypted vault file')

    config.save(do_backup=not args.no_backup)

    LOG.info('Configuration finished')

    config.print_info()

    return 0


if __name__ == "__main__":
    sys.exit(main())
