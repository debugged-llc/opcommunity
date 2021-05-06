"""Install exception handler for process crash."""
import sys
import capnp

from selfdrive.swaglog import cloudlog
from selfdrive.version import version

import sentry_sdk
from sentry_sdk.integrations.threading import ThreadingIntegration

def capture_exception(*args, **kwargs):
  exc_info = sys.exc_info()
  if not exc_info[0] is capnp.lib.capnp.KjException:
    sentry_sdk.capture_exception(*args, **kwargs)
    sentry_sdk.flush()  # https://github.com/getsentry/sentry-python/issues/291
  cloudlog.error("crash", exc_info=kwargs.get('exc_info', 1))

def bind_user(**kwargs):
  sentry_sdk.set_user(kwargs)

def bind_extra(**kwargs):
  for k, v in kwargs.items():
    sentry_sdk.set_tag(k, v)

def init():
  sentry_sdk.init("https://2dd3d1d918134797b3517056cd69f23a@o400203.ingest.sentry.io/5753007",
                  default_integrations=False, integrations=[ThreadingIntegration(propagate_hub=True)],
                  release=version)
