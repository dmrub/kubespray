#!/usr/bin/env python
from __future__ import print_function
import logging
import sys
import argparse
import subprocess
import tempfile
import os
import copy
import os.path
import string
import random
import readline
import getpass
from six.moves import input
from six.moves import shlex_quote
from yaml import load, dump
from six import iteritems

try:
    from subprocess import DEVNULL  # py3k
except ImportError:
    import os

    DEVNULL = open(os.devnull, 'wb')

try:
    from yaml import CLoader as Loader, CDumper as Dumper
except ImportError:
    from yaml import Loader, Dumper

logger = logging.getLogger()

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


def backup_file(path):
    rpath = os.path.realpath(path)
    if os.path.exists(rpath):
        bak_rpath = rpath + "~"
        while os.path.exists(bak_rpath):
            bak_rpath += "~"
        logger.info('Backup file %s to file %s', rpath, bak_rpath)
        os.rename(rpath, bak_rpath)


def load_config(file_name, defaults=None):
    config_vars = {}
    if os.path.exists(file_name):
        try:
            with open(file_name, 'r') as fd:
                config_vars = load(fd, Loader=Loader)
            logger.info('Loaded configuration variables from file: %s', file_name)
        except Exception:
            logger.exception('Could not load configuration variables from file: %s', file_name)
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
            logger.exception('Could not make backup from file: %s', file_name)
            return False

    try:
        with open(file_name, 'w') as fd:
            fd.write(dump(config_vars, Dumper=Dumper))
        logger.info('Saved vars to file: %s', file_name)
    except Exception:
        logger.exception('Could not save vars to file: %s', file_name)
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


class Config(object):

    def __init__(self):
        self.config_vars = load_config(CONFIG_VARS_FILE, defaults={
            'ANSIBLE_INVENTORY': ANSIBLE_INVENTORY,
            'ANSIBLE_VAULT_PASSWORD_FILE': ANSIBLE_VAULT_PASSWORD_FILE,
            'ANSIBLE_CONFIG': ANSIBLE_CONFIG,
            'ANSIBLE_FILTER_PLUGINS': ANSIBLE_FILTER_PLUGINS,
            'ANSIBLE_ROLES_PATH': ANSIBLE_ROLES_PATH,
            'CFG_VAULT_FILE': CFG_VAULT_FILE,
            'CFG_VARS_FILE': CFG_VARS_FILE
        })
        # save initial state
        self._init_config_vars = copy.deepcopy(self.config_vars)

        self.ansible_vars = load_config(self.get_vars_file(), defaults={})
        # save initial state
        self._init_ansible_vars = copy.deepcopy(self.ansible_vars)

    @property
    def config_vars_changed(self):
        return self.config_vars != self._init_config_vars

    @property
    def ansible_vars_changed(self):
        return self.ansible_vars != self._init_ansible_vars

    def save(self, do_backup=False):
        if self.config_vars_changed:
            logger.info('Configuration changed')
            save_config(CONFIG_VARS_FILE, self.config_vars, do_backup=do_backup)
        if self.ansible_vars_changed:
            logger.info('Ansible configuration changed')
            save_config(self.get_vars_file(), self.ansible_vars, do_backup=do_backup)

    def get_ansible_var(self, key, default=None):
        return self.ansible_vars.get(key, default)

    def get_config_var(self, key, default=None):
        return self.config_vars.get(key, default)

    def set_config_var(self, key, value):
        self.config_vars[key] = value

    def get_ansible_user(self, default=None):
        user = self.ansible_vars.get('ansible_user')
        if user is None:
            user = self.ansible_vars.get('ansible_ssh_user', default)
        return user

    def set_ansible_user(self, user):
        self.ansible_vars['ansible_user'] = self.ansible_vars['ansible_ssh_user'] = user

    def get_ansible_private_key_file(self, default=None):
        f = self.ansible_vars.get('ansible_private_key_file')
        if f is None:
            f = self.ansible_vars.get('ansible_ssh_private_key_file', default)
        return f

    def set_ansible_private_key_file(self, value):
        self.ansible_vars['ansible_private_key_file'] = self.ansible_vars['ansible_ssh_private_key_file'] = value

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
        default_modif = EXPORT_SHELL_VARS.get(None)
        for k, v in iteritems(vars):
            modif = EXPORT_SHELL_VARS.get(k, default_modif)
            for mf in modif:
                v = mf(v)
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
    logger.info('Run command {} in env {}, cwd {}'.format(command, env, cwd))

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

    logger.info('Command {} returned code: {}'.format(command, status))
    return status, out, err


def main():
    config = Config()

    parser = argparse.ArgumentParser(
        description="Kubespray configurator",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter
    )
    parser.add_argument('--debug', help='debug mode', action="store_true")
    parser.add_argument('--no-backup', help='disable backup', action="store_true")
    parser.add_argument("-i", "--inventory", help="set inventory",
                        default=realpath_if(config.get_ansible_inventory()))
    parser.add_argument("--vault", help="set user's vault file",
                        default=realpath_if(config.get_vault_file()))
    parser.add_argument("--vars", help="set user's vars file",
                        default=realpath_if(config.get_vars_file()))
    parser.add_argument("-u", "--user", help="set remote user",
                        default=config.get_ansible_user())
    parser.add_argument("-r", "--reconfigure", help="reconfigure", action="store_true")
    parser.add_argument("-k", "--private-key", help="set private key filename",
                        default=realpath_if(config.get_ansible_private_key_file()))
    parser.add_argument("--shell-config", help="print shell configuration", action="store_true")
    parser.add_argument("--show", help="print info and exit", action="store_true")
    parser.add_argument("-v", "--view-vault", help="view configuration vault and exit", action="store_true")
    parser.add_argument("--decrypt-vault", help="decrypt vault", action="store_true")
    args = parser.parse_args()

    if not args.shell_config:
        if args.debug:
            logging.basicConfig(format='%(asctime)s %(levelname)s %(pathname)s:%(lineno)s: %(message)s',
                                level=logging.DEBUG)
        else:
            logging.basicConfig(format='%(asctime)s %(levelname)s %(message)s', level=logging.INFO)

    if args.shell_config:
        config.print_shell_config()
        return 0

    readline.parse_and_bind("tab: complete")

    if args.show:
        config.print_info()
        return 0

    if args.view_vault:
        os.environ['ANSIBLE_VAULT_PASSWORD_FILE'] = config.get_ansible_vault_password_file()
        return subprocess.check_call(['ansible-vault', 'view', config.get_vault_file()], env=os.environ)

    if args.decrypt_vault:
        os.environ['ANSIBLE_VAULT_PASSWORD_FILE'] = config.get_ansible_vault_password_file()
        return subprocess.check_call(['ansible-vault', 'decrypt', config.get_vault_file()], env=os.environ)

    if not os.path.isdir(CONFIG_DIR):
        logger.info('Create directory: %r', CONFIG_DIR)
        os.makedirs(CONFIG_DIR)

    if not os.path.exists(config.get_ansible_vault_password_file()):
        logger.info('Generate vault password file: %r', config.get_ansible_vault_password_file())
        with open(config.get_ansible_vault_password_file(), 'w') as fd:
            fd.write(randpw())

    if args.user:
        config.set_ansible_user(args.user)
    else:
        user = rlinput('Remote (SSH) user name: ', config.get_ansible_user())
        config.set_ansible_user(user)

    logger.info('Ansible user set to %r', config.get_ansible_user())

    if args.private_key:
        config.set_ansible_private_key_file(args.private_key)
        logger.info('Set ansible private key file to %r', args.private_key)

    if args.inventory:
        if realpath_if(args.inventory) != realpath_if(config.get_ansible_inventory()):
            config.set_ansible_inventory(args.inventory)
            logger.info('Set ansible inventory file to %r', args.inventory)

    if args.vault:
        if realpath_if(args.vault) != realpath_if(config.get_vault_file()):
            config.set_vault_file(args.vault)
            logger.info("Set user's ansible vault file to %r", args.vault)

    if args.vars:
        if realpath_if(args.vars) != realpath_if(config.get_vars_file()):
            config.set_vars_file(args.vars)
            logger.info("Set user's ansible vars file to %r", args.vars)

    if not os.path.exists(config.get_vault_file()) or args.reconfigure:
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
        logger.info('Wrote sudo password to vault file')

    if os.path.exists(config.get_vault_file()):
        os.environ['ANSIBLE_VAULT_PASSWORD_FILE'] = config.get_ansible_vault_password_file()
        subprocess.call(['ansible-vault', 'encrypt', config.get_vault_file()], env=os.environ, stderr=DEVNULL)
        logger.info('Encrypted vault file')

    config.save(do_backup=not args.no_backup)

    logger.info('Configuration finished')

    config.print_info()

    return 0


if __name__ == "__main__":
    sys.exit(main())
