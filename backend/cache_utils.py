"""
===============================================================================
FILE : backend/cache_utils.py                              [Milestone 8]
WHAT : redis response caching. a @cached decorator + the invalidation helpers.
WHY  : job listings and the admin search pages hammer the same queries over and
       over with identical results. caching them turns a multi-table JOIN into
       one redis GET.

USED BY:
  student_routes.py -> @cached on list_jobs()
  company_routes.py -> @cached on list_company_jobs(); bump_jobs() on writes
  admin_routes.py   -> @cached on list_companies/list_students/list_jobs;
                       bump_*() on every approve/reject/blacklist/remove
  routes.py         -> bump_companies()/bump_students() on registration
  export_routes.py  -> the /api/admin/cache/* endpoints

REDIS DB LAYOUT (all on the same server, different logical dbs):
    db 0 -> celery broker      (the job queue)
    db 1 -> celery results     (task return values)
    db 2 -> THIS cache         <- flushing it can never eat a queued job

-------------------------------------------------------------------------------
THE TWO HARD PROBLEMS, AND HOW WE SOLVE THEM
-------------------------------------------------------------------------------

PROBLEM 1: "how do I invalidate 500 cached job lists when an admin approves
            one job?"

  the naive way is `redis.keys("jobs:*")` + delete. two things wrong with that:
  KEYS is O(n) and blocks the whole redis server, and you have to remember every
  key you ever wrote.

  we use a NAMESPACE VERSION COUNTER instead. every cache key embeds a version:

      ppa:cache:jobs:v7:u12:<hash of query args>
                        ^^
  invalidating = INCR ppa:cachever:jobs  ->  v7 becomes v8.

  every subsequent read builds a key with v8, misses, and recomputes. the old v7
  keys are now orphans that nobody will ever look up again, and redis evicts them
  on their own TTL. so invalidation is ONE atomic O(1) INCR, no scanning, no
  bookkeeping, no blocking. this is the standard trick and it's worth knowing.

PROBLEM 2: "GET /api/student/jobs returns a DIFFERENT body per student"
            (each job carries an `already_applied` flag for THAT student)

  cache it under one shared key and student A sees student B's applied state.
  actual data leak, not just a stale-cache annoyance.

  so `vary_on_user=True` folds the caller's user id into the key (the `u12`
  above). endpoints whose body is identical for everyone use `vary_on_user=False`
  and share one entry. getting this wrong is the classic caching bug -- the M8
  test suite has a dedicated check for it.

-------------------------------------------------------------------------------
DEGRADE, NEVER DIE
-------------------------------------------------------------------------------
a cache is an optimisation, not a dependency. every redis call here is wrapped:
if redis is down/slow/misconfigured, we log once and behave exactly like a cache
miss -- the route runs its query and returns real data. the app must never 500
because a cache is unhappy. (there's a test for this too: point it at a dead
port and every endpoint still answers 200.)
===============================================================================
"""

import functools
import hashlib
import json
import logging

import redis
from flask import g, jsonify, request

from config import Config

logger = logging.getLogger(__name__)

# A SHORT FINGERPRINT OF THE DATABASE WE'RE POINTED AT.
#
# why: the cache key is built from (namespace, version, user id, query args) --
# note that NONE of those mention which database produced the data. so two
# processes sharing one redis but talking to DIFFERENT databases would collide:
# admin user 1 + `?q=` in the test DB produces exactly the same key as admin
# user 1 + `?q=` in the real DB, and whoever writes last wins.
#
# that's not hypothetical. the M6/M7 test suites run against a temp sqlite file
# while redis stays on the shared cache db -- without this tag, a test run would
# poison the dev app's cache with test rows for up to the TTL. same trap bites
# staging and prod sharing a redis instance.
#
# folding a hash of the DB URI into the prefix makes the caches disjoint by
# construction. 8 hex chars is plenty to separate a handful of environments.
_DB_TAG = hashlib.sha256(Config.SQLALCHEMY_DATABASE_URI.encode()).hexdigest()[:8]

# key prefixes. namespacing everything under "ppa:" means this cache can share a
# redis server with anything else without collisions.
_KEY_PREFIX = f"ppa:cache:{_DB_TAG}"
_VERSION_PREFIX = f"ppa:cachever:{_DB_TAG}"

# the three namespaces we cache. one version counter each, so approving a job
# doesn't needlessly blow away the cached student search.
NS_JOBS = "jobs"
NS_COMPANIES = "companies"
NS_STUDENTS = "students"

# TTL per namespace, falling back to the default for anything unlisted.
_TTL = {
    NS_JOBS: Config.CACHE_TTL_JOBS,
    NS_COMPANIES: Config.CACHE_TTL_COMPANIES,
    NS_STUDENTS: Config.CACHE_TTL_STUDENTS,
}


# --- the client -------------------------------------------------------------

# module-level singleton. redis-py's client is thread-safe and pools connections
# internally, so one instance for the whole process is correct -- do NOT build a
# new client per request.
#
# decode_responses=True -> redis hands back `str`, not `bytes`. saves a .decode()
# on every single read.
#
# the short timeouts matter: without them a hung redis would make every request
# hang too, and the "cache is only an optimisation" promise quietly breaks. 0.5s
# is far longer than a healthy local GET (~0.2ms) and short enough that a dead
# redis costs us half a second, once, per request rather than 30.
try:
    _client = redis.Redis.from_url(
        Config.CACHE_REDIS_URL,
        decode_responses=True,
        socket_connect_timeout=0.5,
        socket_timeout=0.5,
    )
except Exception as exc:  # bad URL in .env, basically
    logger.error("Cache disabled, bad CACHE_REDIS_URL: %s", exc)
    _client = None


def cache_available():
    """Is the cache switched on AND is redis actually answering?

    used by the /api/admin/cache/stats endpoint and by the guards below.
    PING is cheap (sub-millisecond) but it IS a round trip, so don't call this
    on the hot path -- the get/set helpers just try the real command and catch.
    """
    if not Config.CACHE_ENABLED or _client is None:
        return False
    try:
        return _client.ping()
    except redis.RedisError:
        return False


# --- namespace versioning (the invalidation engine) -------------------------


def _version(namespace):
    """Current version number of a namespace. Missing key == version 1.

    a MISS here (redis down) returns 1, which is fine: we'd build keys against
    v1, and since we also can't READ or WRITE, nothing is served stale.
    """
    if _client is None:
        return 1
    try:
        raw = _client.get(f"{_VERSION_PREFIX}:{namespace}")
        return int(raw) if raw else 1
    except (redis.RedisError, ValueError):
        return 1


def bump(namespace):
    """Invalidate an ENTIRE namespace in one atomic O(1) operation.

    INCR is atomic, so two workers invalidating at once can't race. and INCR on a
    missing key treats it as 0 and sets it to 1 -- no need to initialise it.

    the old keys are NOT deleted. they're orphaned (nothing will ever compute
    their key again) and redis reclaims them when their TTL lapses. that's the
    whole point: invalidation costs one command regardless of how many entries
    are being invalidated.

    call this from EVERY write path that could change what a cached read returns.
    the wrapper fns below (bump_jobs etc.) exist so route files read nicely.
    """
    if _client is None or not Config.CACHE_ENABLED:
        return
    try:
        _client.incr(f"{_VERSION_PREFIX}:{namespace}")
    except redis.RedisError as exc:
        # can't invalidate -> entries live out their TTL. stale for <=60s, not
        # forever. we log and carry on rather than failing the user's write.
        logger.warning("Cache bump failed for %s: %s", namespace, exc)


def bump_jobs():
    """Job listings changed. Hit this on: job create/update/approve/reject/delete,
    a student applying (changes already_applied + applications_count), and any
    company approval change (a company's approval status gates its jobs'
    visibility via _approved_jobs_query)."""
    bump(NS_JOBS)


def bump_companies():
    """Company list/search changed: register, approve, reject, blacklist, remove."""
    bump(NS_COMPANIES)


def bump_students():
    """Student list/search changed: register, profile update, blacklist,
    deactivate, activate, remove."""
    bump(NS_STUDENTS)


def bump_all():
    """Nuke everything. Backs the admin "Flush cache" button.

    note it bumps versions rather than FLUSHDB'ing -- same visible effect, but it
    physically cannot touch the celery broker/results even if someone
    misconfigures CACHE_REDIS_URL onto db 0 or 1. defensive.
    """
    for namespace in (NS_JOBS, NS_COMPANIES, NS_STUDENTS):
        bump(namespace)


# --- key building -----------------------------------------------------------


def _build_key(namespace, vary_on_user):
    """Compose the full cache key for THIS request.

        ppa:cache:a1b2c3d4:jobs:v7:u12:3f9a1c...
                  ^db tag  ^ns  ^ver ^user ^hash of the query string

    the hash: query args sorted (so ?q=a&c=b and ?c=b&q=a are ONE entry), joined,
    then sha256'd and truncated to 16 hex chars. we hash rather than inline the
    raw args because arbitrary user input in a key means unbounded key length and
    redis chokes on very long keys.

    16 hex chars = 64 bits. collision odds are negligible at our scale, and a
    collision would serve one user a wrong-but-valid job list, not corrupt data.

    vary_on_user -> `u<id>` segment. omit it and every user shares one entry.
    ANY endpoint whose response body depends on who's asking MUST set this.
    """
    args = sorted(request.args.items())
    raw = "&".join(f"{k}={v}" for k, v in args)
    digest = hashlib.sha256(raw.encode()).hexdigest()[:16]

    user_part = "all"
    if vary_on_user:
        # g.current_user is set by @token_required, which always runs first
        # because @cached sits INSIDE @role_required.
        user_part = f"u{getattr(g, 'current_user', None).id}"

    return f"{_KEY_PREFIX}:{namespace}:v{_version(namespace)}:{user_part}:{digest}"


# --- the decorator ----------------------------------------------------------


def cached(namespace, vary_on_user=False):
    """Cache a JSON GET endpoint's response body in redis.

    USAGE -- decorator order matters:

        @student_bp.route("/jobs", methods=["GET"])
        @role_required("student")        <- runs FIRST (auth)
        @cached(NS_JOBS, vary_on_user=True)   <- runs SECOND
        def list_jobs():
            ...

    @cached must sit BELOW @role_required so that (a) an unauthenticated request
    is rejected before it can ever read the cache, and (b) g.current_user exists
    by the time _build_key() needs it. flip them and you have both a security
    hole and an AttributeError.

    WHAT GETS CACHED: only a plain 200 JSON response. if the view returns a
    tuple (i.e. an error like `return jsonify({"error":...}), 400`) we pass it
    straight through uncached -- caching a 400 for 60s would be miserable to
    debug, and caching a 403 could later be served to someone else.

    HIT/MISS is surfaced as an `X-Cache` response header. that's not decoration:
    it's how the test suite proves caching works, and how you demo it in the viva
    (`curl -sI ... | grep X-Cache`).
    """

    def decorator(view):
        @functools.wraps(view)  # keeps __name__, else flask route registration breaks
        def wrapper(*args, **kwargs):
            # kill switch / redis missing -> behave as if @cached weren't here
            if not Config.CACHE_ENABLED or _client is None:
                return view(*args, **kwargs)

            key = _build_key(namespace, vary_on_user)

            # ---- read path ----
            try:
                hit = _client.get(key)
            except redis.RedisError as exc:
                logger.warning("Cache read failed (%s): %s", key, exc)
                hit = None  # degrade to a miss, run the real query

            if hit is not None:
                try:
                    response = jsonify(json.loads(hit))
                    response.headers["X-Cache"] = "HIT"
                    return response
                except json.JSONDecodeError:
                    # corrupt entry (shouldn't happen). drop it and recompute.
                    logger.warning("Corrupt cache entry at %s, dropping", key)

            # ---- miss path: run the real view ----
            result = view(*args, **kwargs)

            # only cache a bare 200 JSON Response. a tuple means (body, status)
            # -> an error path -> don't cache. `is_json` guards send_file etc.
            if not isinstance(result, tuple) and getattr(result, "is_json", False):
                if result.status_code == 200:
                    try:
                        _client.setex(  # SET + EXPIRE atomically, in one command
                            key,
                            _TTL.get(namespace, Config.CACHE_TTL_DEFAULT),
                            json.dumps(result.get_json()),
                        )
                    except (redis.RedisError, TypeError) as exc:
                        # TypeError = payload isn't JSON-serialisable. either way
                        # the user still gets their correct response.
                        logger.warning("Cache write failed (%s): %s", key, exc)
                result.headers["X-Cache"] = "MISS"

            return result

        return wrapper

    return decorator


# --- introspection (for the admin cache panel) ------------------------------


def cache_stats():
    """Snapshot of the cache, for GET /api/admin/cache/stats.

    `keys` counts live entries per namespace at the CURRENT version -- orphaned
    old-version keys aren't counted, since they're logically already gone.

    uses SCAN, not KEYS. SCAN is cursor-based and non-blocking; KEYS locks up
    redis for the duration and is a genuine production footgun. at our key counts
    it makes no measurable difference, but the habit is the point.
    """
    if not cache_available():
        return {"enabled": False, "connected": False, "namespaces": {}}

    namespaces = {}
    for namespace in (NS_JOBS, NS_COMPANIES, NS_STUDENTS):
        version = _version(namespace)
        pattern = f"{_KEY_PREFIX}:{namespace}:v{version}:*"
        try:
            count = sum(1 for _ in _client.scan_iter(match=pattern, count=100))
        except redis.RedisError:
            count = 0
        namespaces[namespace] = {
            "version": version,
            "keys": count,
            "ttl_seconds": _TTL.get(namespace, Config.CACHE_TTL_DEFAULT),
        }

    info = {}
    try:
        raw = _client.info("stats")
        hits = raw.get("keyspace_hits", 0)
        misses = raw.get("keyspace_misses", 0)
        total = hits + misses
        info = {
            "keyspace_hits": hits,
            "keyspace_misses": misses,
            # server-wide (celery's dbs count too), so treat it as indicative
            # rather than a precise hit rate for OUR cache.
            "hit_rate_pct": round(hits / total * 100, 1) if total else 0.0,
        }
    except redis.RedisError:
        pass

    return {"enabled": True, "connected": True, "namespaces": namespaces, "redis": info}
