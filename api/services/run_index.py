"""Run index — keyset-paged, filterable, health-tagged view over the engine
run root.

This is a **read-only** substrate for the Operate-plane Runs UI (U6) and the
Runs dashboard (U9). It scans ``<project_root>/data/workflows/<run_id>/`` run
checkpoints directly; the frozen ``WorkflowEngine`` (``engine.list_runs``) is
deliberately untouched and unused by this path.

Design pins (Operate-plane spec §3.2):

* **Run root (F11):** there is no ``ENCLAVE_RUNS_DIR`` env var. Run dirs live at
  ``<project_root>/data/workflows`` — the exact location the engine derives in
  ``workflow_engine.py`` (``self._project_root / "data" / "workflows"``, the
  boot-reaper at ~:243) and reads through the ``WORKFLOW_DATA_DIR`` override
  (``workflow_engine.DATA_DIR``, :35). We honour that same env seam live so
  tests and deployments stay in lockstep, and fall back to the two-line
  project-root derivation duplicated below with a pin comment.
* **Cursor (F22):** keyset paging sorted on the *immutable* ``(started_at,
  run_id)`` descending. ``started_at`` is read from ``run.json`` (dir-mtime
  fallback when absent); ``run_id`` (the dir name) is the stable tiebreak. Dir
  mtime mutates on every checkpoint and is therefore **never** the sort key —
  it only pre-orders the scan-cap window. The cursor encodes both halves.
* **Amortized stats cache (F23/C9):** one signature-invalidated
  ``{workflow_id -> {kinds, duration_median, tokens_median}}`` cache. Anomaly
  math reads the cache; a cold cache renders rows with ``stats_pending`` in
  ``degraded_reasons`` rather than triggering per-row sibling scans.
"""

from __future__ import annotations

import base64
import os
import statistics
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

from ..logging_config import logger

# Bounded work per request — never walk the whole corpus to fill one page.
SCAN_CAP = 500
# Anomaly threshold: a run is degraded when its duration/token cost exceeds
# this multiple of the cached same-workflow median.
ANOMALY_FACTOR = 3.0
# Median window: last-N completed runs per workflow feed the median.
MEDIAN_WINDOW = 10

_FAILED_STATES = {"failed", "error"}
_RUNNING_STATES = {"running", "queued"}


# ── Run root ────────────────────────────────────────────────────────────────


def _run_root() -> Path:
    """Resolve the engine run root.

    Honours ``WORKFLOW_DATA_DIR`` live (the same override
    ``workflow_engine.DATA_DIR`` reads — keeps this scanner and the engine's
    own checkpoint writer pointed at one directory under test). Falls back to
    the project-root derivation pinned to ``workflow_engine.py`` (the boot
    reaper: ``self._project_root / "data" / "workflows"``; ``_project_root =
    Path(__file__).resolve().parents[2]``). This file lives at the same depth
    (``api/services/``) so the derivation is identical.
    """
    override = os.getenv("WORKFLOW_DATA_DIR")
    if override:
        return Path(override).resolve()
    # PIN: mirror workflow_engine.py ``_project_root`` derivation (do NOT edit
    # the frozen engine to share this — duplication is intentional, F11).
    project_root = Path(__file__).resolve().parents[2]
    return (project_root / "data" / "workflows").resolve()


def _resolve_run_dir(root: Path, run_id: str) -> Optional[Path]:
    """Resolve ``root/run_id`` and confirm containment BEFORE any file open.

    Rejects ``..`` traversal, absolute-path injection, and symlink escapes.
    Returns ``None`` when the resolved path is not a directory strictly under
    ``root`` — the caller skips it silently (nothing invented, nothing leaked).
    """
    if not run_id or run_id in (".", ".."):
        return None
    candidate = (root / run_id).resolve()
    try:
        candidate.relative_to(root)
    except ValueError:
        return None
    if not candidate.is_dir():
        return None
    return candidate


# ── Cursor ──────────────────────────────────────────────────────────────────


def encode_cursor(started_at: str, run_id: str) -> str:
    """Opaque, URL-safe ``<started_at>|<run_id>`` cursor."""
    raw = f"{started_at or ''}|{run_id}".encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii")


def decode_cursor(cursor: Optional[str]) -> Optional[Tuple[str, str]]:
    """Decode a cursor to ``(started_at, run_id)`` or ``None`` when absent/bad.

    A malformed cursor is treated as "start from the top" rather than an error —
    the page is always renderable.
    """
    if not cursor:
        return None
    try:
        raw = base64.urlsafe_b64decode(cursor.encode("ascii")).decode("utf-8")
        started_at, _, run_id = raw.partition("|")
        if not run_id:
            return None
        return (started_at, run_id)
    except Exception:  # noqa: BLE001 — a bad cursor just resets to page 1
        return None


def _sort_key(started_at: str, run_id: str) -> Tuple[str, str]:
    """Descending keyset order is expressed by reverse-sorting this tuple."""
    return (started_at or "", run_id)


# ── run.json helpers ────────────────────────────────────────────────────────


def _read_json(path: Path) -> Optional[Dict[str, Any]]:
    import json

    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def _started_at_of(run_dir: Path, data: Optional[Dict[str, Any]]) -> str:
    """``started_at`` from run.json, dir-mtime ISO fallback when absent (F22)."""
    if data:
        sa = data.get("started_at")
        if sa:
            return str(sa)
    # Fallback ONLY — mtime is never the primary sort key.
    from datetime import datetime, timezone

    try:
        ts = run_dir.stat().st_mtime
    except OSError:
        ts = 0.0
    return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()


def _duration_seconds(data: Dict[str, Any]) -> Optional[float]:
    """Wall-clock run duration from timestamps; falls back to summed step
    durations when either endpoint is missing."""
    from datetime import datetime

    started = data.get("started_at")
    completed = data.get("completed_at")
    if started and completed:
        try:
            dt0 = datetime.fromisoformat(str(started))
            dt1 = datetime.fromisoformat(str(completed))
            delta = (dt1 - dt0).total_seconds()
            if delta >= 0:
                return delta
        except ValueError:
            pass
    total = 0.0
    seen = False
    for s in data.get("step_results") or []:
        if isinstance(s, dict) and s.get("duration_seconds") is not None:
            try:
                total += float(s["duration_seconds"])
                seen = True
            except (TypeError, ValueError):
                continue
    return total if seen else None


def _tokens_total(data: Dict[str, Any]) -> int:
    """Sum of per-step total_tokens (token_count is a dict or a bare int)."""
    total = 0
    for s in data.get("step_results") or []:
        if not isinstance(s, dict):
            continue
        tc = s.get("token_count")
        if isinstance(tc, dict):
            try:
                total += int(tc.get("total_tokens") or 0)
            except (TypeError, ValueError):
                continue
        elif isinstance(tc, (int, float)):
            total += int(tc)
    return total


def _retries_total(data: Dict[str, Any]) -> int:
    total = 0
    for s in data.get("step_results") or []:
        if isinstance(s, dict) and s.get("retries"):
            try:
                total += int(s["retries"])
            except (TypeError, ValueError):
                continue
    return total


def _error_class(error: Optional[str]) -> Optional[str]:
    """Leading token of an error string — the closest cheap proxy for the
    exception class (``TimeoutError: ...`` -> ``TimeoutError``)."""
    if not error:
        return None
    head = str(error).strip().split(":", 1)[0].strip()
    return head.split()[0] if head else None


# ── Type taxonomy ───────────────────────────────────────────────────────────


def classify_type(
    origin: Optional[Dict[str, Any]],
    kinds_present: Optional[Set[str]],
    workflow_id: str,
    plan_items: Optional[List[Dict[str, Any]]] = None,
) -> List[Dict[str, Any]]:
    """Co-occurring type tags (chips) for a run. Never invents provenance for
    the 1,675 legacy sidecar-less runs — those fall through to Manual plus
    whatever their content-derived kinds justify.

    Precedence within a single origin: an explicit ``origin.json`` sidecar wins
    over the ``^(test|smoke|demo)[-_]`` heuristic. Tags are additive — a
    scheduled run whose workflow contains a ``ralph`` step carries both the
    ``Scheduled`` and ``Autonomous Loop`` chips.
    """
    origin = origin or {}
    kinds_present = kinds_present or set()
    tags: List[Dict[str, Any]] = []

    origin_kind = str(origin.get("origin") or "").lower()

    # Scheduled — sidecar authoritative; ⚡ affix on an on-demand "run-now".
    if origin_kind == "scheduled":
        category = origin.get("schedule_category") or "Scheduled"
        run_now = str(origin.get("trigger") or "") == "run-now"
        label = f"Scheduled {category}"
        if run_now:
            label = "⚡ " + label
        tags.append(
            {
                "type": "scheduled",
                "label": label,
                "category": category,
                "run_now": run_now,
            }
        )

    # Autonomous Loop — a ralph step in the workflow, or a plan item minted by
    # the ralph vocabulary. Read-only against the existing plan model.
    autonomous = "ralph" in kinds_present
    if not autonomous and plan_items:
        autonomous = any(
            isinstance(p, dict) and str(p.get("origin") or "").lower() == "ralph"
            for p in plan_items
        )
    if autonomous:
        tags.append({"type": "autonomous", "label": "Autonomous Loop"})

    # Test — sidecar authoritative; else a flagged, derived heuristic.
    if origin_kind == "test":
        tags.append({"type": "test", "label": "Test"})
    elif not origin_kind:
        low = (workflow_id or "").lower()
        if low.startswith(("test-", "test_", "smoke-", "smoke_", "demo-", "demo_")):
            tags.append({"type": "test", "label": "Test", "derived": True})

    # Manual is the floor — present unless a first-class origin already claimed
    # the run (scheduled / test sidecar).
    if origin_kind not in ("scheduled", "test"):
        tags.append({"type": "manual", "label": "Manual"})

    return tags


# ── Health model ────────────────────────────────────────────────────────────


def assess_health(
    data: Dict[str, Any],
    stats: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
    """Health is an axis orthogonal to type (O6d).

    ``failed``     — run status in failed/error; carries ``failing_step`` (first
                     failing step, BFS/document order) and ``error_class``.
    ``degraded``   — completed but suspicious: retries, an internal failed or
                     skipped step, or a duration/token cost beyond
                     ``ANOMALY_FACTOR``x the cached same-workflow median. Reasons
                     are enumerated in ``degraded_reasons``. A cold stats cache
                     contributes ``stats_pending`` and suppresses the
                     cost-anomaly checks (never a per-row sibling scan).
    ``running``    — status running/queued (the client overlays ``stalled``).
    ``completed``  — the healthy terminal state.

    Returns a dict merged into the row: ``health``, ``failing_step``,
    ``error_class``, ``retries_total``, ``tokens_total``, ``degraded_reasons``.
    """
    status = str(data.get("status") or "").lower()
    step_results = [s for s in (data.get("step_results") or []) if isinstance(s, dict)]

    retries_total = _retries_total(data)
    tokens_total = _tokens_total(data)
    duration = _duration_seconds(data)

    failing_step: Optional[str] = None
    error_class: Optional[str] = None

    if status in _FAILED_STATES:
        # First failing step in document order = the BFS root of the failure.
        for s in step_results:
            if str(s.get("status") or "").lower() in _FAILED_STATES:
                failing_step = s.get("step_id")
                error_class = _error_class(s.get("error"))
                break
        if error_class is None:
            error_class = _error_class(data.get("error"))
        return {
            "health": "failed",
            "failing_step": failing_step,
            "error_class": error_class,
            "retries_total": retries_total,
            "tokens_total": tokens_total,
            "degraded_reasons": [],
        }

    if status in _RUNNING_STATES:
        return {
            "health": "running",
            "failing_step": None,
            "error_class": None,
            "retries_total": retries_total,
            "tokens_total": tokens_total,
            "degraded_reasons": [],
        }

    # Terminal-completed: look for degradation signals.
    reasons: List[str] = []
    if retries_total > 0:
        reasons.append("retries")
    for s in step_results:
        st = str(s.get("status") or "").lower()
        if st in _FAILED_STATES:
            reasons.append("failed_step")
            break
    for s in step_results:
        if str(s.get("status") or "").lower() == "skipped":
            reasons.append("skipped_step")
            break

    if stats is None:
        reasons.append("stats_pending")
    else:
        dur_median = stats.get("duration_median")
        tok_median = stats.get("tokens_median")
        if (
            duration is not None
            and dur_median
            and dur_median > 0
            and duration > ANOMALY_FACTOR * dur_median
        ):
            reasons.append("duration_anomaly")
        if (
            tok_median
            and tok_median > 0
            and tokens_total > ANOMALY_FACTOR * tok_median
        ):
            reasons.append("token_anomaly")

    # De-dup while preserving order.
    seen: Set[str] = set()
    reasons = [r for r in reasons if not (r in seen or seen.add(r))]

    # ``stats_pending`` alone (cold cache, otherwise-clean run) is not itself a
    # degradation — it is a caveat carried on an otherwise ``completed`` row.
    real_reasons = [r for r in reasons if r != "stats_pending"]
    health = "degraded" if real_reasons else "completed"

    return {
        "health": health,
        "failing_step": None,
        "error_class": None,
        "retries_total": retries_total,
        "tokens_total": tokens_total,
        "degraded_reasons": reasons,
    }


# ── Amortized stats cache ───────────────────────────────────────────────────

_STATS_LOCK = threading.Lock()
_STATS_CACHE: Dict[str, Any] = {"sig": None, "data": None, "building": False}
_KINDS_LOCK = threading.Lock()
_KINDS_CACHE: Dict[str, Any] = {"sig": None, "data": {}}


def _root_signature(root: Path) -> Tuple[int, int]:
    """(entry-count, root-mtime-ns). Adding a run dir bumps both; per-checkpoint
    child writes bump neither → the index/median cache stays stable under the
    checkpoint-mtime churn the determinism test exercises."""
    try:
        entries = list(os.scandir(root))
        count = sum(1 for e in entries if e.is_dir())
        mtime = root.stat().st_mtime_ns
        return (count, mtime)
    except OSError:
        return (0, 0)


def _kinds_for_workflow(workflow_id: str) -> Set[str]:
    """Distinct step kinds for a workflow, via the engine's own
    ``_collect_step_kinds`` walker (workflows.py:62). Cached per workflow_id;
    best-effort — an unresolvable workflow yields an empty set."""
    if not workflow_id:
        return set()
    cached = _KINDS_CACHE["data"].get(workflow_id)
    if cached is not None:
        return cached
    kinds: Set[str] = set()
    try:
        from ..routers.workflows import _collect_step_kinds, get_engine, WORKFLOWS_DIR

        engine = get_engine()
        yaml_path = engine.resolve_workflow_path(workflow_id, WORKFLOWS_DIR)
        if yaml_path:
            defn = engine.load(yaml_path)
            kinds = set(_collect_step_kinds(defn).values())
    except Exception as exc:  # noqa: BLE001 — kinds are advisory
        logger.debug("kinds lookup skipped for %s: %s", workflow_id, exc)
    with _KINDS_LOCK:
        _KINDS_CACHE["data"][workflow_id] = kinds
    return kinds


def _build_stats(root: Path) -> Dict[str, Dict[str, Any]]:
    """One amortized full pass: per-workflow duration/token medians over the
    last ``MEDIAN_WINDOW`` completed runs. This is the pass F23/C9 folds the
    kinds walk beside — cheap because it is memoized by root signature."""
    buckets: Dict[str, List[Tuple[str, Optional[float], int]]] = {}
    try:
        entries = list(os.scandir(root))
    except OSError:
        return {}
    for scanned, entry in enumerate(entries):
        # Cooperative GIL yield: this pass json-parses the whole corpus and, on
        # a background thread, would otherwise starve uvicorn's event loop
        # (CPU-bound parsing holds the GIL) — a slow-request storm the fast-loop
        # UI suite trips on. A sub-ms sleep every 50 dirs releases the GIL in
        # bounded chunks; the total added latency over ~2k dirs is negligible.
        if scanned and scanned % 50 == 0:
            time.sleep(0.001)
        if not entry.is_dir():
            continue
        run_dir = _resolve_run_dir(root, entry.name)
        if run_dir is None:
            continue
        data = _read_json(run_dir / "run.json")
        if not data:
            continue
        if str(data.get("status") or "").lower() != "completed":
            continue
        wf = data.get("workflow_id") or ""
        started = _started_at_of(run_dir, data)
        buckets.setdefault(wf, []).append(
            (started, _duration_seconds(data), _tokens_total(data))
        )

    stats: Dict[str, Dict[str, Any]] = {}
    for wf, rows in buckets.items():
        rows.sort(key=lambda r: r[0], reverse=True)
        window = rows[:MEDIAN_WINDOW]
        durations = [d for _, d, _ in window if d is not None]
        tokens = [t for _, _, t in window if t]
        stats[wf] = {
            "duration_median": statistics.median(durations) if durations else None,
            "tokens_median": statistics.median(tokens) if tokens else None,
            "count": len(rows),
        }
    return stats


def warm_stats(root: Optional[Path] = None) -> Dict[str, Dict[str, Any]]:
    """Synchronously (re)build and cache the stats. Used by the dashboard warm
    path and by tests that need deterministic anomaly math."""
    root = root or _run_root()
    sig = _root_signature(root)
    data = _build_stats(root)
    with _STATS_LOCK:
        _STATS_CACHE.update({"sig": sig, "data": data, "building": False})
    return data


def _get_stats(root: Path, block: bool) -> Optional[Dict[str, Dict[str, Any]]]:
    """Fresh cached stats, or ``None`` when cold. When cold and not blocking, a
    single background rebuild is kicked off and ``None`` is returned so the page
    renders immediately with ``stats_pending`` (spec: never block the page)."""
    sig = _root_signature(root)
    with _STATS_LOCK:
        if _STATS_CACHE["sig"] == sig and _STATS_CACHE["data"] is not None:
            return _STATS_CACHE["data"]
        already_building = _STATS_CACHE["building"]

    if block:
        return warm_stats(root)

    if not already_building:
        with _STATS_LOCK:
            _STATS_CACHE["building"] = True

        def _bg() -> None:
            try:
                warm_stats(root)
            except Exception as exc:  # noqa: BLE001
                logger.debug("stats warm failed: %s", exc)
                with _STATS_LOCK:
                    _STATS_CACHE["building"] = False

        threading.Thread(target=_bg, name="run-index-stats", daemon=True).start()
    return None


def reset_caches() -> None:
    """Test hook — drop all memoized state so a fresh corpus is re-scanned."""
    with _STATS_LOCK:
        _STATS_CACHE.update({"sig": None, "data": None, "building": False})
    with _KINDS_LOCK:
        _KINDS_CACHE.update({"sig": None, "data": {}})


# ── Row assembly ────────────────────────────────────────────────────────────


def build_row(
    run_id: str,
    data: Dict[str, Any],
    origin: Optional[Dict[str, Any]],
    stats_for_wf: Optional[Dict[str, Any]],
    kinds_present: Optional[Set[str]],
) -> Dict[str, Any]:
    """Assemble one enriched Runs row from an already-read run.json (+ optional
    origin.json). Pure — no I/O, so it is unit-testable in isolation."""
    workflow_id = data.get("workflow_id") or ""
    health = assess_health(data, stats_for_wf)
    origin_kind = str((origin or {}).get("origin") or "") or "manual"
    return {
        "run_id": run_id,
        "workflow_id": workflow_id,
        "status": data.get("status"),
        "started_at": data.get("started_at"),
        "completed_at": data.get("completed_at"),
        "duration_seconds": _duration_seconds(data),
        "origin": origin_kind,
        "schedule_id": (origin or {}).get("schedule_id"),
        "schedule_category": (origin or {}).get("schedule_category"),
        "type_tags": classify_type(origin, kinds_present, workflow_id),
        "health": health["health"],
        "failing_step": health["failing_step"],
        "error_class": health["error_class"],
        "retries_total": health["retries_total"],
        "tokens_total": health["tokens_total"],
        "degraded_reasons": health["degraded_reasons"],
    }


def _matches_filters(
    row: Dict[str, Any],
    status: Optional[str],
    type_: Optional[str],
    health: Optional[str],
    q: Optional[str],
) -> bool:
    if status and str(row.get("status") or "").lower() != status.lower():
        return False
    if health and str(row.get("health") or "").lower() != health.lower():
        return False
    if type_:
        want = type_.lower()
        if not any(t.get("type") == want for t in row.get("type_tags") or []):
            return False
    if q:
        needle = q.lower()
        hay = f"{row.get('run_id','')} {row.get('workflow_id','')}".lower()
        if needle not in hay:
            return False
    return True


# ── Index ───────────────────────────────────────────────────────────────────


def _load_index(root: Path) -> List[Tuple[str, str]]:
    """Build the ``(started_at, run_id)`` keyset index, sorted descending.

    Reads each run.json only for its ``started_at`` (dir-mtime fallback). Uncached
    on purpose at this layer — the expensive per-workflow medians ARE cached; the
    index itself is a light single scan bounded by the corpus size. Containment is
    enforced before any open.
    """
    index: List[Tuple[str, str]] = []
    try:
        entries = list(os.scandir(root))
    except OSError:
        return index
    for entry in entries:
        if not entry.is_dir():
            continue
        run_dir = _resolve_run_dir(root, entry.name)
        if run_dir is None:
            continue
        data = _read_json(run_dir / "run.json")
        started = _started_at_of(run_dir, data)
        index.append((started, entry.name))
    # Descending keyset order: newest started_at first, run_id as stable tiebreak.
    index.sort(key=lambda pair: _sort_key(pair[0], pair[1]), reverse=True)
    return index


def scan_runs(
    limit: int = 30,
    cursor: Optional[str] = None,
    status: Optional[str] = None,
    type_: Optional[str] = None,
    health: Optional[str] = None,
    q: Optional[str] = None,
    *,
    block_stats: bool = False,
) -> Dict[str, Any]:
    """Keyset-paged, server-side-filtered page of enriched Runs rows.

    Returns ``{runs, next_cursor, scanned, exhausted, stats_ready}``. Filters are
    applied server-side so "page N of failed" is a real page. At most
    ``SCAN_CAP`` run dirs are opened per request; when the cap is hit before the
    page fills, ``next_cursor`` points at the last-examined run so the client
    resumes without gaps or dupes.
    """
    limit = max(1, min(int(limit or 30), 200))
    root = _run_root()
    index = _load_index(root)
    # Total run count (unfiltered) — the keyset index is already materialized, so
    # this is free. Lets the client show "Page N of M" for the default view; the
    # exact filtered total isn't cheaply knowable, so the UI drops "of M" when a
    # server-side filter/search narrows the set.
    total = len(index)

    after = decode_cursor(cursor)
    if after is not None:
        after_key = _sort_key(after[0], after[1])
        # Strictly-less-than the cursor in descending order.
        index = [p for p in index if _sort_key(p[0], p[1]) < after_key]

    stats = _get_stats(root, block=block_stats)
    stats_ready = stats is not None

    rows: List[Dict[str, Any]] = []
    scanned = 0
    last_examined: Optional[Tuple[str, str]] = None
    exhausted = True

    for pos, (started, run_id) in enumerate(index):
        if scanned >= SCAN_CAP:
            exhausted = False
            break
        run_dir = _resolve_run_dir(root, run_id)
        if run_dir is None:
            continue
        data = _read_json(run_dir / "run.json")
        if not data:
            continue
        scanned += 1
        last_examined = (started, run_id)
        origin = _read_json(run_dir / "origin.json")
        workflow_id = data.get("workflow_id") or ""
        kinds_present = _kinds_for_workflow(workflow_id)
        stats_for_wf = stats.get(workflow_id) if stats else None
        row = build_row(run_id, data, origin, stats_for_wf, kinds_present)
        if not _matches_filters(row, status, type_, health, q):
            continue
        rows.append(row)
        if len(rows) >= limit:
            # Page is full. Only advertise more if index entries actually remain
            # past this position — a page that lands exactly on the last run is
            # genuinely exhausted (no spurious empty follow-up page).
            exhausted = pos == len(index) - 1
            break

    next_cursor: Optional[str] = None
    if not exhausted and last_examined is not None:
        next_cursor = encode_cursor(last_examined[0], last_examined[1])

    return {
        "runs": rows,
        "next_cursor": next_cursor,
        "scanned": scanned,
        "exhausted": exhausted,
        "stats_ready": stats_ready,
        "total": total,
    }
