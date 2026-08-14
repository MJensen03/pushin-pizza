"""Flask extensions, created unbound.

They live here rather than in app.py so the view modules can import them (for
decorators like @limiter.limit) without importing app.py, which would be a
circular import. app.py calls init_app() on each one during setup.
"""

from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from flask_wtf import CSRFProtect

csrf = CSRFProtect()

# Rate limiting. Per-IP, in-memory (per-process, resets on restart) — matches the
# login throttle in views_admin; a shared store (e.g. Redis) is needed for
# multi-worker deployments. Volumetric floods should also be handled at the host /
# reverse-proxy layer; this is the application-level backstop against request spam.
limiter = Limiter(
    key_func=get_remote_address,
    default_limits=["300 per hour"],
    storage_uri="memory://",
    strategy="fixed-window",
)
