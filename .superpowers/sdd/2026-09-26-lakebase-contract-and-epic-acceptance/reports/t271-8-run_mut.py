"""#271 Task 8 mutation runner. Runs ONLY in the temp worktree t271-8-mut."""

import os
import subprocess
import sys

TREE = "/Users/robert.whiffin/Documents/slide-gen-branch-eval/t271-8-mut"
SHA = "1e7cf9499"
PY = "/Users/robert.whiffin/.pyenv/shims/python"
assert os.getcwd() == TREE, os.getcwd()
ENV = dict(
    os.environ,
    PYTHONPATH=f"{TREE}:{TREE}/packages/databricks-tellr",
    DATABASE_URL="sqlite:////tmp/t271-8-mut.sqlite",
    TELLR_TEST_POSTGRES_URL="postgresql+psycopg2://localhost:5432/postgres",
)

UNIT_WIRING = "tests/unit/test_engine_mode_wiring.py"
UNIT_C52 = "tests/unit/test_persisted_graph_release.py"
PG = "tests/integration/test_lakebase_contract_failures_postgres.py"
CI = "tests/unit/test_ci_collects_integration_tests.py"


def edit(path, old, new, count=1):
    full = os.path.join(TREE, path)
    text = open(full).read()
    assert text.count(old) == count, (path, text.count(old), old[:80])
    open(full, "w").write(text.replace(old, new))


def run(target, extra=()):
    cmd = [PY, "-m", "pytest", target, "-q", "-p", "no:randomly", "-m", "not live", *extra]
    out = subprocess.run(cmd, cwd=TREE, env=ENV, capture_output=True, text=True, timeout=900)
    tail = out.stdout.strip().splitlines()[-1] if out.stdout.strip() else out.stderr[-300:]
    failed = [line for line in out.stdout.splitlines() if line.startswith(("FAILED", "ERROR"))]
    return tail, failed


def restore(paths):
    subprocess.run(["git", "checkout", SHA, "--", *paths], cwd=TREE, check=True)
    diff = subprocess.run(["git", "diff", "--quiet", SHA, "--", *paths], cwd=TREE)
    assert diff.returncode == 0, paths
    status = subprocess.run(["git", "status", "--porcelain"], cwd=TREE, capture_output=True, text=True)
    assert status.stdout.strip() == "", status.stdout


FAIL_OPEN_ROUTE = """    try:
        engine_mode = await asyncio.to_thread(
            resolve_engine_mode_or_unavailable, request.session_id
        )
    except PersistedConfigurationUnavailableError as e:
        await asyncio.to_thread(
            session_manager.release_session_lock,
            request.session_id,
        )
        raise _engine_mode_unavailable() from e
"""

MUTATIONS = {
    "M1 fail-open at /chat/stream (C7 reviewer sabotage: fallback=monolith restored at chat.py:~490)": (
        [("src/api/routes/chat.py", FAIL_OPEN_ROUTE, """    # T271M1
    def _fail_open(session_id):
        try:
            return resolve_engine_mode_or_unavailable(session_id)
        except PersistedConfigurationUnavailableError:
            return "monolith"

    engine_mode = await asyncio.to_thread(_fail_open, request.session_id)
""")],
        [(UNIT_WIRING, ()), (PG, ("-k", "stream_route"))],
    ),
    "M2 fail-open at /chat/async (chat.py:~697)": (
        [("src/api/routes/chat.py", """        engine_mode = await asyncio.to_thread(
            resolve_engine_mode_or_unavailable, request.session_id
        )

        # Queue for processing""", """        # T271M2
        try:
            engine_mode = await asyncio.to_thread(
                resolve_engine_mode_or_unavailable, request.session_id
            )
        except PersistedConfigurationUnavailableError:
            engine_mode = "monolith"

        # Queue for processing""")],
        [(UNIT_WIRING, ()), (PG, ("-k", "async_route"))],
    ),
    "M3 fail-open at the SSE re-resolve (chat_service.py:~1141, keeps the route's mode)": (
        [("src/api/services/chat_service.py", """            except PersistedConfigurationUnavailableError:
                yield _pinned_graph_configuration_error_event()
                raise
""", """            except PersistedConfigurationUnavailableError:  # T271M3
                pass
""")],
        [(UNIT_WIRING, ()), (PG, ("-k", "sse_re_resolve"))],
    ),
    "M4 lock not released before the /chat/stream 503": (
        [("src/api/routes/chat.py", """    except PersistedConfigurationUnavailableError as e:
        await asyncio.to_thread(
            session_manager.release_session_lock,
            request.session_id,
        )
        raise _engine_mode_unavailable() from e
""", """    except PersistedConfigurationUnavailableError as e:  # T271M4
        raise _engine_mode_unavailable() from e
""")],
        [(UNIT_WIRING, ()), (PG, ("-k", "stream_route"))],
    ),
    "M5 lock not released before the /chat/async 503": (
        [("src/api/routes/chat.py", """    except PersistedConfigurationUnavailableError as e:
        await asyncio.to_thread(
            session_manager.release_session_lock, request.session_id
        )
        raise _engine_mode_unavailable() from e
""", """    except PersistedConfigurationUnavailableError as e:  # T271M5
        raise _engine_mode_unavailable() from e
""")],
        [(UNIT_WIRING, ()), (PG, ("-k", "async_route"))],
    ),
    "M6 slots=True restored on both C52 exceptions": (
        [("src/services/persisted_graph_release.py", "@_context_manager_safe\n@dataclass(frozen=True)\n",
          "@_context_manager_safe\n@dataclass(frozen=True, slots=True)  # T271M6\n", 2)],
        [(UNIT_C52, ()), (PG, ())],
    ),
    "M6b C52 fix removed entirely (frozen+slots, no wrapper: the shipped defect)": (
        [("src/services/persisted_graph_release.py", "@_context_manager_safe\n@dataclass(frozen=True)\n",
          "@dataclass(frozen=True, slots=True)  # T271M6b\n", 2)],
        [(UNIT_C52, ()), (PG, ())],
    ),
    "M6c C52 wrapper removed but slots dropped (plain frozen dataclass: dropping slots alone is not the fix)": (
        [("src/services/persisted_graph_release.py", "@_context_manager_safe\n@dataclass(frozen=True)\n",
          "@dataclass(frozen=True)  # T271M6c\n", 2)],
        [(UNIT_C52, ()), (PG, ("-k", "bundle or endpoint or lakebase or schema"))],
    ),
    "M7 plan REVIEWER sabotage: AgentRuntime.run's SQLAlchemyError branch queries the active release to retry": (
        [("src/services/agent_runtime.py", """        except SQLAlchemyError as exc:
            raise PersistedConfigurationUnavailableError(code="lakebase_unavailable") from exc
        except (GraphConfigurationIntegrityError, ValidationError, TypeError) as exc:
            raise PersistedConfigurationUnavailableError(
                code="invalid_persisted_definition"
            ) from exc
        return self._run_resolved(definition, payload, assembly_context)
""", """        except SQLAlchemyError as exc:  # T271M7 (run only)
            from sqlalchemy import select as _select

            from src.database.models.graph_configuration import GraphRelease as _GR
            from src.services.graph.builder import get_session_local as _gsl

            with _gsl()() as _db:
                _db.scalars(_select(_GR).where(_GR.effective_to.is_(None))).one()
            raise PersistedConfigurationUnavailableError(code="lakebase_unavailable") from exc
        except (GraphConfigurationIntegrityError, ValidationError, TypeError) as exc:
            raise PersistedConfigurationUnavailableError(
                code="invalid_persisted_definition"
            ) from exc
        return self._run_resolved(definition, payload, assembly_context)
""")],
        [(PG, ("-k", "lakebase_unavailable"))],
    ),
    "M8 the SSE re-resolve raises without yielding the safe event": (
        [("src/api/services/chat_service.py", """            except PersistedConfigurationUnavailableError:
                yield _pinned_graph_configuration_error_event()
                raise
""", """            except PersistedConfigurationUnavailableError:  # T271M8
                raise
""")],
        [(UNIT_WIRING, ()), (PG, ("-k", "sse_re_resolve"))],
    ),
    "M9 the 503 body carries the internal exception text": (
        [("src/api/routes/chat.py", """        raise _engine_mode_unavailable() from e
    except Exception as e:""", """        raise HTTPException(status_code=503, detail={**ENGINE_MODE_UNAVAILABLE_DETAIL, "cause": repr(e.__cause__)}) from e  # T271M9
    except Exception as e:""")],
        [(UNIT_WIRING, ()), (PG, ("-k", "async_route"))],
    ),
    "M10 the CI line for the new file removed": (
        [(".github/workflows/test.yml", "            tests/integration/test_lakebase_contract_failures_postgres.py \\\n", "")],
        [(CI, ())],
    ),
}

only = sys.argv[1:] or list(MUTATIONS)
for name in MUTATIONS:
    if not any(name.startswith(key) for key in only):
        continue
    edits, targets = MUTATIONS[name]
    paths = sorted({e[0] for e in edits})
    for e in edits:
        edit(*e)
    print(f"### {name}", flush=True)
    try:
        for target, extra in targets:
            tail, failed = run(target, extra)
            print(f"  {target} {' '.join(extra)} -> {tail}", flush=True)
            for line in failed[:12]:
                print(f"    {line}", flush=True)
    finally:
        restore(paths)
print("### restored; tree clean", flush=True)
