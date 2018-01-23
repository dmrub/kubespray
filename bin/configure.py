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

try:
    from subprocess import DEVNULL # py3k
except ImportError:
    import os
    DEVNULL = open(os.devnull, 'wb')

try:
    from yaml import CLoader as Loader, CDumper as Dumper
except ImportError:
    from yaml import Loader, Dumper

logger = logging.getLogger()

HOME = os.path.expanduser('~')


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


class Config(object):

    def __init__(self):
        self.VARS = {}
        self.THIS_DIR = os.path.dirname(os.path.realpath(__file__))
        self.ROOT_DIR = os.path.join(self.THIS_DIR, '..')
        self.ANSIBLE_DIR = self.ROOT_DIR
        self.ANSIBLE_PLAYBOOKS_DIR = self.ANSIBLE_DIR
        self.ANSIBLE_INVENTORY_DIR = os.path.join(self.ROOT_DIR, 'inventory')
        self.ANSIBLE_INVENTORY = os.path.join(self.ANSIBLE_INVENTORY_DIR, 'inventory.cfg')
        self.CONFIG_DIR = os.path.join(HOME, '.ansible')
        self.VAULT_FILE = os.path.join(self.ROOT_DIR, 'vault-config.yml')
        self.VARS_FILE = os.path.join(self.ROOT_DIR, 'vars-config.yml')
        self.load_vars()
        self.ANSIBLE_VAULT_PASSWORD_FILE = os.getenv('ANSIBLE_VAULT_PASSWORD_FILE',
                                                     os.path.join(self.CONFIG_DIR, 'vault_pass.txt'))
        self.ANSIBLE_CONFIG = os.path.join(self.ANSIBLE_DIR, 'ansible.cfg')
        self.ANSIBLE_FILTER_PLUGINS = os.path.join(self.ANSIBLE_DIR, 'filter_plugins')
        self.ANSIBLE_ROLES_PATH = os.path.join(self.ANSIBLE_DIR, 'roles')

        # update config_vars
        self.get_ansible_inventory()

        # create initial state
        self.INIT_VARS = copy.deepcopy(self.VARS)

    @property
    def changed(self):
        return self.VARS != self.INIT_VARS

    def get_var(self, key, default=None):
        return self.VARS.get(key, default)

    def get_config_var(self, key, default=None):
        config_vars = self.VARS.get('config_vars')
        if not isinstance(config_vars, dict):
            config_vars = self.VARS['config_vars'] = {}
        return config_vars.get(key, default)

    def set_config_var(self, key, value):
        config_vars = self.VARS.get('config_vars')
        if not isinstance(config_vars, dict):
            config_vars = self.VARS['config_vars'] = {}
        config_vars[key] = value

    def get_ansible_user(self, default=None):
        user = self.VARS.get('ansible_user')
        if user is None:
            user = self.VARS.get('ansible_ssh_user', default)
        return user

    def set_ansible_user(self, user):
        self.VARS['ansible_user'] = self.VARS['ansible_ssh_user'] = user

    def get_ansible_private_key_file(self, default=None):
        f = self.VARS.get('ansible_private_key_file')
        if f is None:
            f = self.VARS.get('ansible_ssh_private_key_file', default)
        return f

    def set_ansible_private_key_file(self, value):
        self.VARS['ansible_private_key_file'] = self.VARS['ansible_ssh_private_key_file'] = value

    def get_ansible_inventory(self):
        return self.get_config_var('ANSIBLE_INVENTORY', self.ANSIBLE_INVENTORY)

    def set_ansible_inventory(self, value):
        self.set_config_var('ANSIBLE_INVENTORY', value)

    def load_vars(self):
        self.VARS.clear()
        if os.path.exists(self.VARS_FILE):
            try:
                with open(self.VARS_FILE, 'r') as fd:
                    self.VARS = load(fd, Loader=Loader)
                logger.info('Loaded vars from file: %s', self.VARS_FILE)
            except Exception:
                logger.exception('Could not load vars from file: %s', self.VARS_FILE)

    def save_vars(self, do_backup=True):
        if do_backup:
            try:
                backup_file(self.VARS_FILE)
            except Exception:
                logger.exception('Could not make backup from file: %s', self.VARS_FILE)
                return False

        try:
            with open(self.VARS_FILE, 'w') as fd:
                fd.write(dump(self.VARS, Dumper=Dumper))
            logger.info('Saved vars to file: %s', self.VARS_FILE)
        except Exception:
            logger.exception('Could not save vars to file: %s', self.VARS_FILE)
            return False

        return True

    def print_info(self):
        print("""
Current Configuration:

Ansible inventory file:        {ANSIBLE_INVENTORY}
Config directory:              {CONFIG_DIR}
Ansible vault password file:   {ANSIBLE_VAULT_PASSWORD_FILE}
Ansible remote user:           {ANSIBLE_REMOTE_USER}
Ansible private SSH key file:  {ANSIBLE_PRIVATE_KEY_FILE}""".format(
            ANSIBLE_INVENTORY=os.path.realpath(self.get_ansible_inventory()),
            CONFIG_DIR=realpath_if(self.CONFIG_DIR),
            ANSIBLE_VAULT_PASSWORD_FILE=realpath_if(self.ANSIBLE_VAULT_PASSWORD_FILE),
            ANSIBLE_REMOTE_USER=self.get_ansible_user(default=''),
            ANSIBLE_PRIVATE_KEY_FILE=realpath_if(self.get_ansible_private_key_file(default=''))))

    def print_shell_config(self):
        print("""ANSIBLE_REMOTE_USER={ANSIBLE_REMOTE_USER}
ANSIBLE_PRIVATE_KEY_FILE={ANSIBLE_PRIVATE_KEY_FILE}
ANSIBLE_INVENTORY={ANSIBLE_INVENTORY}""".format(
            ANSIBLE_REMOTE_USER=shlex_quote(self.get_ansible_user(default='')),
            ANSIBLE_PRIVATE_KEY_FILE=shlex_quote(self.get_ansible_private_key_file(default='')),
            ANSIBLE_INVENTORY=shlex_quote(realpath_if(self.get_ansible_inventory()))))


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
                        default=realpath_if(config.ANSIBLE_INVENTORY))
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
        os.environ['ANSIBLE_VAULT_PASSWORD_FILE'] = config.ANSIBLE_VAULT_PASSWORD_FILE
        return subprocess.check_call(['ansible-vault', 'view', config.VAULT_FILE], env=os.environ)

    if args.decrypt_vault:
        os.environ['ANSIBLE_VAULT_PASSWORD_FILE'] = config.ANSIBLE_VAULT_PASSWORD_FILE
        return subprocess.check_call(['ansible-vault', 'decrypt', config.VAULT_FILE], env=os.environ)

    if not os.path.isdir(config.CONFIG_DIR):
        logger.info('Create directory: %r', config.CONFIG_DIR)
        os.makedirs(config.CONFIG_DIR)

    if not os.path.exists(config.ANSIBLE_VAULT_PASSWORD_FILE):
        logger.info('Generate vault password file: %r', config.ANSIBLE_VAULT_PASSWORD_FILE)
        with open(config.ANSIBLE_VAULT_PASSWORD_FILE, 'w') as fd:
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

    if not os.path.exists(config.VAULT_FILE) or args.reconfigure:
        count = 0
        while True:
            if count > 2:
                print("Have exhausted maximum number of retries", file=sys.stderr)
                return 1
            sudo_pass_1 = getpass("Sudo password: ")
            sudo_pass_2 = getpass("Retype sudo password: ")
            if sudo_pass_1 != sudo_pass_2:
                print("Sorry, passwords do not match", file=sys.stderr)
            else:
                break
            count += 1
        vault_data = {
            "ansible_become_pass" : sudo_pass_1
        }
        with open(config.VAULT_FILE, 'w') as fd:
            fd.write(dump(vault_data, Dumper=Dumper))
        logger.info('Wrote sudo password to vault file')

    if os.path.exists(config.VAULT_FILE):
        os.environ['ANSIBLE_VAULT_PASSWORD_FILE'] = config.ANSIBLE_VAULT_PASSWORD_FILE
        subprocess.call(['ansible-vault', 'encrypt', config.VAULT_FILE], env=os.environ, stderr=DEVNULL)
        logger.info('Encrypted vault file')

    if config.changed:
        logger.info('Configuration changed')
        config.save_vars(do_backup=not args.no_backup)
    logger.info('Configuration finished')

    config.print_info()

    return 0


if __name__ == "__main__":
    sys.exit(main())
