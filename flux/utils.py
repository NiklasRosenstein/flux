# Copyright (c) 2016  Niklas Rosenstein
#
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in
# all copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN
# THE SOFTWARE.

import io
import functools
import hashlib
import hmac
import json
import logging
import os
import shlex
import subprocess
import urllib.parse
import uuid
import zipfile

from . import config
from .constants import API_GOGS, API_GITHUB
from urllib.parse import urlparse
from flask import request, session, redirect, url_for, Response


def get_raise(data, key, expect_type=None):
  ''' Helper function to retrieve an element from a JSON data structure.
  The *key* must be a string and may contain periods to indicate nesting.
  Parts of the key may be a string or integer used for indexing on lists.
  If *expect_type* is not None and the retrieved value is not of the
  specified type, TypeError is raised. If the key can not be found,
  KeyError is raised. '''

  parts = key.split('.')
  resolved = ''
  for part in parts:
    resolved += part
    try:
      part = int(part)
    except ValueError:
      pass

    if isinstance(part, str):
      if not isinstance(data, dict):
        raise TypeError('expected dictionary to access {!r}'.format(resolved))
      try:
        data = data[part]
      except KeyError:
        raise KeyError(resolved)
    elif isinstance(part, int):
      if not isinstance(data, list):
        raise TypeError('expected list to access {!r}'.format(resolved))
      try:
        data = data[part]
      except IndexError:
        raise KeyError(resolved)
    else:
      assert False, "unreachable"

    resolved += '.'

  if expect_type is not None and not isinstance(data, expect_type):
    raise TypeError('expected {!r} but got {!r} instead for {!r}'.format(
      expect_type.__name__, type(data).__name__, key))
  return data


def get(data, key, expect_type=None, default=None):
  ''' Same as :func:`get_raise`, but returns *default* if the key could
  not be found or the datatype doesn't match. '''

  try:
    return get_raise(data, key, expect_type)
  except (TypeError, ValueError, KeyError):
    return default


def basic_auth(message='Login required'):
  ''' Sends a 401 response that enables basic auth. '''

  headers = {'WWW-Authenticate': 'Basic realm="{}"'.format(message)}
  return Response('Please log in.', 401, headers, mimetype='text/plain')


def requires_auth(func):
  ''' Decorator for view functions that require basic authentication. '''

  from .models import Session, User

  @functools.wraps(func)
  def wrapper(*args, **kwargs):
    user_name = session.get('user_name')
    user_passhash = session.get('user_passhash')
    with Session() as db_session:
      user = User.get_by(db_session, user_name, user_passhash)
      if not user:
        return redirect(url_for('login'))

    request.user = user
    return func(*args, **kwargs)

  return wrapper


def with_io_response(kwarg='stream', stream_type='text', **response_kwargs):
  ''' Decorator for View functions that create a :class:`io.StringIO` or
  :class:`io.BytesIO` (based on the *stream_type* parameter) and pass it
  as *kwarg* to the wrapped function. The contents of the buffer are
  sent back to the client. '''

  if stream_type == 'text':
    factory = io.StringIO
  elif stream_type == 'bytes':
    factory = io.BytesIO
  else:
    raise ValueError('invalid value for stream_type: {!r}'.format(stream_type))

  def decorator(func):
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
      if kwarg in kwargs:
        raise RuntimeError('keyword argument {!r} already occupied'.format(kwarg))
      kwargs[kwarg] = stream = factory()
      status = func(*args, **kwargs)
      return Response(stream.getvalue(), status=status, **response_kwargs)
    return wrapper

  return decorator


def with_logger(kwarg='logger', stream_dest_kwarg='stream', replace=True):
  ''' Decorator that creates a new :class:`logging.Logger` object
  additionally to or in-place for the *stream* parameter passed to
  the wrapped function. This is usually used in combination with
  the :func:`with_io_response` decorator.

  Note that exceptions with this decorator will be logged and the
  returned status code will be 500 Internal Server Error. '''

  def decorator(func):
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
      if replace:
        stream = kwargs.pop(stream_dest_kwarg)
      else:
        stream = kwargs[stream_dest_kwarg]
      kwargs[kwarg] = logger = create_logger(stream)
      try:
        return func(*args, **kwargs)
      except BaseException as exc:
        logger.exception(exc)
        return 500
    return wrapper

  return decorator


def with_dbsession(func):
  ''' Decorator that adds a :class:`Session` object as ``db_session``
  to the Flask request. '''

  from .models import Session

  @functools.wraps(func)
  def wrapper(*args, **kwargs):
    with Session() as session:
      request.db_session = session
      return func(*args, **kwargs)

  return wrapper


def create_logger(stream, name=__name__, fmt=None):
  ''' Creates a new :class:`logging.Logger` object with the
  specified *name* and *fmt* (defaults to a standard logging
  formating including the current time, levelname and message).

  The logger will also output to stderr. '''

  fmt = fmt or '[%(asctime)-15s - %(levelname)s]: %(message)s'
  formatter = logging.Formatter(fmt)

  logger = logging.Logger(name)
  handler = logging.StreamHandler(stream)
  handler.setFormatter(formatter)
  logger.addHandler(handler)

  return logger


def stream_file(filename, name=None, mime=None):
  def generate():
    with open(filename, 'rb') as fp:
      yield from fp
  if name is None:
    name = os.path.basename(filename)
  headers = {}
  headers['Content-Type'] = mime or 'application/x-octet-stream'
  headers['Content-Length'] = os.stat(filename).st_size
  headers['Content-Disposition'] = 'attachment; filename="' + name + '"'
  return Response(generate(), 200, headers)


def flash(message=None):
  if message is None:
    return session.pop('flux_flash', None)
  else:
    session['flux_flash'] = message


def make_secret():
  return str(uuid.uuid4())


def hash_pw(pw):
  return hashlib.md5(pw.encode('utf8')).hexdigest()


def makedirs(path):
  ''' Shorthand that creates a directory and stays silent when it
  already exists. '''

  if not os.path.exists(path):
    os.makedirs(path)


def zipdir(dirname, filename):
  dirname = os.path.abspath(dirname)
  zipf = zipfile.ZipFile(filename, 'w')
  for root, dirs, files in os.walk(dirname):
    for fname in files:
      arcname = os.path.join(os.path.relpath(root, dirname), fname)
      zipf.write(os.path.join(root, fname), arcname)
  zipf.close()


def run(command, logger, cwd=None, env=None, shell=False):
  ''' Run a subprocess with the specified *command*. The command
  and output of the command is logged to *logger*. *command* will
  automatically be converted to a string or list of command arguments
  based on the *shell* parameter.

  Returns the exit code of the command. '''

  if shell:
    if not isinstance(command, str):
      command = ' '.join(shlex.quote(x) for x in command)
    logger.info('$ ' + command)
  else:
    if isinstance(command, str):
      command = shlex.split(command)
    logger.info('$ ' + ' '.join(map(shlex.quote, command)))

  popen = subprocess.Popen(
    command, cwd=cwd, env=env, shell=shell, stdout=subprocess.PIPE,
    stderr=subprocess.STDOUT, stdin=None)
  stdout = popen.communicate()[0].decode()
  if stdout:
    if popen.returncode != 0:
      logger.error('\n' + stdout)
    else:
      logger.info('\n' + stdout)
  return popen.returncode


def ssh_command(url, *args, no_ptty=False, identity_file=None,
    verbose=None, options=None):
  ''' Helper function to generate an SSH command. If not options are
  specified, the default option ``BatchMode=yes`` will be set. '''

  if options is None:
    options = {'BatchMode': 'yes'}
  if verbose is None:
    verbose = config.ssh_verbose

  command = ['ssh']
  if url is not None:
    command.append(url)
  command += ['-o{}={}'.format(k, v) for (k, v) in options.items()]
  if no_ptty:
    command.append('-T')
  if identity_file:
    command += ['-i', identity_file]
  if verbose:
    command.append('-v')
  if args:
    command.append('--')
    command += args
  return command


def strip_url_path(url):
  ''' Strips that path part of the specified *url*. '''

  result = list(urllib.parse.urlparse(url))
  result[2] = ''
  return urllib.parse.urlunparse(result)


def verify_secret(request, repo, api):
  data = json.loads(request.data.decode('utf8'))
  if api == API_GOGS:
    print("repo.secret={} data.secret={}".format(repo.secret, get(data, 'secret')))
    return repo.secret == get(data, 'secret')
  elif api == API_GITHUB:
    expected = hmac.new(bytes(repo.secret, 'utf-8'), request.data, hashlib.sha1).hexdigest()
    secret = request.headers.get('X-Hub-Signature').replace('sha1=', '')
    print("expected={}, got={}".format(expected, secret))
    return expected == secret
  return False  #  unsupported API, should raise something?
