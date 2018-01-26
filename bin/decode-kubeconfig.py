#!/usr/bin/env python
from __future__ import print_function
import logging

import sys
import os
import yaml
import base64
import subprocess
import tempfile

logger = logging.getLogger()


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


class ExecutionException(Exception):
    def __init__(self, message, stdout=None, stderr=None, oserror=None):
        self.message = message
        self.stdout = stdout
        self.stderr = stderr
        self.oserror = oserror
        super(ExecutionException, self).__init__(message)


def process_with_cmd(args, input):
    cwd = '.'
    with tempfile.NamedTemporaryFile() as input_file:
        input_file.write(input)
        input_file.flush()
        input_file.seek(0)

        try:
            status, out, err = run_command(args, env=os.environ, cwd=cwd,
                                           stdin=input_file)
        except OSError as e:
            message = 'Could not execute command line "{}" in directory "{}": {}'.format(
                ' '.join(args), cwd, e)
            logger.exception(message)
            raise ExecutionException(message=message, oserror=e)
        if status != 0:
            print(err, file=sys.stderr)
            print(input, file=sys.stderr)
            raise ExecutionException(message='computation failed',
                                     stdout=out, stderr=err)
        print(err)
        return out


def decode_certificate(cert):
    cwd = '.'
    args = ["openssl", "rsa", "-text", "-noout"]
    with tempfile.NamedTemporaryFile() as cert_file:
        cert_file.write(cert)
        cert_file.flush()
        cert_file.seek(0)

        try:
            status, out, err = run_command(args, env=os.environ, cwd=cwd,
                                           stdin=cert_file)
        except OSError as e:
            message = 'Could not execute command line "{}" in directory "{}": {}'.format(
                ' '.join(args), cwd, e)
            logger.exception(message)
            raise ExecutionException(message=message, oserror=e)
        if status != 0:
            print(err, file=sys.stderr)
            print(cert, file=sys.stderr)
            raise ExecutionException(message='computation failed',
                                     stdout=out, stderr=err)
        print(err)
        return out


def get_obj_from_dict(d, key):
    obj_data = d.get(key)
    if obj_data:
        decoded_obj_data = base64.b64decode(obj_data)
        if 'BEGIN CERTIFICATE' in decoded_obj_data:
            cmd = ["openssl", "x509", "-text", "-noout"]
        elif 'BEGIN RSA PRIVATE KEY' in decoded_obj_data:
            cmd = ["openssl", "rsa", "-text", "-noout"]
        return process_with_cmd(cmd, decoded_obj_data)
    return None


if __name__ == "__main__":
    logging.basicConfig()

    if len(sys.argv) <= 1:
        print('Usage: {} kubeconfig-file'.format(sys.argv[0]), file=sys.stderr)
        sys.exit(0)

    stream = open(sys.argv[1], "r")
    docs = yaml.load_all(stream)
    for doc in docs:
        kind = doc.get('kind')
        clusters = doc.get('clusters')
        for cluster in clusters:
            cluster_data = cluster.get('cluster')
            cluster_name = cluster.get('name')
            if cluster_data:
                cert = get_obj_from_dict(cluster_data,
                                         'certificate-authority-data')
                server = cluster_data.get('server')
                print('Server: {}'.format(server))
                print('certificate-authority-data:')
                print(cert)

        users = doc.get('users')
        for user in users:
            user_name = user.get('name')
            print('User: {}'.format(user_name))
            user_data = user.get('user')
            if user_data:
                cert = get_obj_from_dict(user_data,
                                         'client-certificate-data')
                print('client-certificate-data:')
                print(cert)

                cert = get_obj_from_dict(user_data,
                                         'client-key-data')
                print('client-key-data:')
                print(cert)
