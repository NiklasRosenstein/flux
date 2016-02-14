# Copyright (C) 2016  Niklas Rosenstein
# All rights reserved.
'''
Flux -- Lightweight private build server
========================================

Flux is a simple, Flask_ based build server that responds to Git
push events as triggered by GitHub, GitLab, BitBucket or Gogs.
While it is cross-platform and can on Windows, Linux and Mac OS,
it does not provide any kind of virtualization or container
management.

.. _Flask: http://flask.pocoo.org/
'''

__author__ = 'Niklas Rosenstein <rosensteinniklas@gmail.com>'
__version__ = '1.0.0-dev'


import flask
app = flask.Flask(__name__)

import flux_config as config
from . import views, queue


def main():
  ''' Runs the Flux Flask application and all required components. '''

  # XXX Test if Git version is at least 2.3 (for GIT_SSH_COMMAND)
  queue.start()
  try:
    app.run(host=config.host, port=config.port, debug=config.debug)
  finally:
    queue.stop()