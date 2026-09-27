"""#271 Task 8 fix round 1 mutations. Runs ONLY in the temp worktree t271-8-mut."""
import os, subprocess, sys

TREE = "/Users/robert.whiffin/Documents/slide-gen-branch-eval/t271-8-mut"
SHA = "ad0f5753e"
PY = "/Users/robert.whiffin/.pyenv/shims/python"
assert os.getcwd() == TREE, os.getcwd()
ENV = dict(os.environ, PYTHONPATH=f"{TREE}:{TREE}/packages/databricks-tellr",
           DATABASE_URL="sqlite:////tmp/t271-8-mut.sqlite",
           TELLR_TEST_POSTGRES_URL="postgresql+psycopg2://localhost:5432/postgres")
W = "tests/unit/test_engine_mode_wiring.py"
PC = "tests/unit/test_conversation_pin_creation.py"
PG = "tests/integration/test_lakebase_contract_failures_postgres.py"

def edit(path, old, new, count=1):
    full = os.path.join(TREE, path); text = open(full).read()
    assert text.count(old) == count, (path, text.count(old), old[:80])
    open(full, "w").write(text.replace(old, new))

def run(target, extra=()):
    out = subprocess.run([PY, "-m", "pytest", target, "-q", "-p", "no:randomly", "-m", "not live", *extra],
                         cwd=TREE, env=ENV, capture_output=True, text=True, timeout=900)
    lines = out.stdout.strip().splitlines()
    return (lines[-1] if lines else out.stderr[-300:]), [l for l in lines if l.startswith(("FAILED", "ERROR "))]

def restore(paths):
    subprocess.run(["git", "checkout", SHA, "--", *paths], cwd=TREE, check=True)
    assert subprocess.run(["git", "diff", "--quiet", SHA, "--", *paths], cwd=TREE).returncode == 0
    st = subprocess.run(["git", "status", "--porcelain"], cwd=TREE, capture_output=True, text=True).stdout
    assert st.strip() == "", st

MUT = {
 "F1a contribute: the parent-read mapping removed (back to 500)": (
   [("src/api/routes/sessions.py", """        except ConversationGraphReleaseIntegrityError as e:
            if not _active_graph_release_exists(db):
                raise ActiveGraphReleaseUnavailableError("no active Graph Release") from e
            raise
""", """        except ConversationGraphReleaseIntegrityError:  # T271F1a
            raise
""")], [(PC, ("-k", "contribute")), (PG, ("-k", "route_creator"))]),
 "F1b contribute: ANY parent integrity error mapped to 503 (mislabel)": (
   [("src/api/routes/sessions.py", """            if not _active_graph_release_exists(db):
                raise ActiveGraphReleaseUnavailableError""", """            if True:  # T271F1b
                raise ActiveGraphReleaseUnavailableError""")], [(PC, ("-k", "contribute"))]),
 "F2 async: typed except widened back over the whole try": (
   [("src/api/routes/chat.py", """    except _EngineModeUnresolvedError as e:
        await asyncio.to_thread(
            session_manager.release_session_lock, request.session_id
        )
        raise _engine_mode_unavailable() from e.__cause__
""", """    except (_EngineModeUnresolvedError, PersistedConfigurationUnavailableError) as e:  # T271F2
        await asyncio.to_thread(
            session_manager.release_session_lock, request.session_id
        )
        raise _engine_mode_unavailable() from e
""")], [(W, ()), (PG, ("-k", "async_route"))]),
 "F3a DEBUG cause log removed": (
   [("src/api/services/chat_service.py", """        logger.debug(
            "Engine-mode resolution failure cause",
            extra={"session_id": session_id},
            exc_info=True,
        )
""", """        pass  # T271F3a
""")], [(W, ("-k", "redacted"),)]),
 "F3b ERROR record gets exc_info (redaction lost)": (
   [("src/api/services/chat_service.py", """            "Engine-mode resolution failed; failing the turn closed",
            extra={"session_id": session_id, "error_class": type(exc).__name__},
        )""", """            "Engine-mode resolution failed; failing the turn closed",
            extra={"session_id": session_id, "error_class": type(exc).__name__},
            exc_info=True,  # T271F3b
        )""")], [(W, ("-k", "redacted"),)]),
 "F4 healthy stream turn: SSE generator's finally release removed": (
   [("src/api/routes/chat.py", """        finally:
            await asyncio.to_thread(
                session_manager.release_session_lock,
                request.session_id,
            )

    return StreamingResponse(""", """        finally:
            pass  # T271F4

    return StreamingResponse(""")], [(W, ("-k", "TestStreamingRoute and reaches_the_service_as_graph"))]),
}
only = sys.argv[1:] or list(MUT)
for name, (edits, targets) in MUT.items():
    if not any(name.startswith(k) for k in only):
        continue
    for e in edits: edit(*e)
    print(f"### {name}", flush=True)
    try:
        for t, extra in targets:
            tail, failed = run(t, extra)
            print(f"  {t} {' '.join(extra)} -> {tail}", flush=True)
            for l in failed[:8]: print(f"    {l}", flush=True)
    finally:
        restore(sorted({e[0] for e in edits}))
print("### restored; tree clean")
