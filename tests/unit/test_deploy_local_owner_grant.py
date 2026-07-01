from unittest.mock import MagicMock
import pytest
import scripts.deploy_local as d


def test_trigger_owner_grant_job_runs_and_waits():
    ws = MagicMock()
    run = MagicMock()
    run.state.result_state = "SUCCESS"
    ws.jobs.run_now.return_value.result.return_value = run
    d._trigger_owner_grant_job(ws, 123, "new-sp", "h.example", "ep")
    _, kwargs = ws.jobs.run_now.call_args
    assert kwargs["job_id"] == 123
    params = kwargs["python_params"]
    assert "--new-sp-id" in params and "new-sp" in params
    assert "--host" in params and "h.example" in params
    assert "--endpoint-name" in params and "ep" in params


def test_trigger_owner_grant_job_raises_on_failure():
    ws = MagicMock()
    run = MagicMock()
    run.state.result_state = "FAILED"
    ws.jobs.run_now.return_value.result.return_value = run
    with pytest.raises(d.DeploymentError):
        d._trigger_owner_grant_job(ws, 123, "new-sp", "h.example", "ep")
