"""Deployment settings the audit found unsafe or stale (O1, O2, O3, O6, O9).
Plain-text checks on the files themselves — nothing here runs Docker."""

import os
import re

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _read(name):
    with open(os.path.join(ROOT, name), encoding="utf-8") as f:
        return f.read()


def _compose_ports():
    return re.findall(r'^\s*-\s*"([^"]+:\d+)"\s*$', _read("docker-compose.yml"), re.M)


def test_ports_are_published_on_this_computer_only():
    # O1: "8501:8501" listened on every interface, with no login.
    ports = _compose_ports()
    assert ports == ["127.0.0.1:8501:8501"]


def test_env_reaches_the_containers_at_start_and_never_the_image():
    # O2: .env was baked into the image by COPY . .
    ignored = _read(".dockerignore").split()
    assert ".env" in ignored
    compose = _read("docker-compose.yml")
    assert compose.count("- path: .env") == 2              # dashboard and scheduler
    assert "required: false" in compose


def test_no_local_model_container():
    # O3: the Mistral container was pulled and run, and nothing called it.
    compose = _read("docker-compose.yml")
    assert "model-runner" not in compose and "mistral" not in compose
    assert "DMR_ENDPOINT" not in _read("config.py") + _read(".env.example")


def test_backups_land_on_the_host():
    compose = _read("docker-compose.yml")
    assert compose.count("./backups:/app/backups") == 2
    assert "./contracts" not in compose                     # O9: never written


def test_requirements_are_pinned():
    # O6: `streamlit>=1.35.0` let a rebuild pull a release that drops an
    # argument the app relies on.
    reqs = [ln.split("#")[0].strip() for ln in _read("requirements.txt").splitlines()]
    reqs = [r for r in reqs if r]
    assert reqs and all(re.fullmatch(r"[A-Za-z0-9_.\-\[\]]+==[\w.]+", r) for r in reqs), reqs


def test_no_deprecated_use_container_width():
    assert "use_container_width" not in _read("app.py")


def test_restart_only_stops_its_own_streamlit():
    # O9: `pkill -f "streamlit run"` killed every Streamlit app on the machine.
    code = [ln for ln in _read("restart.sh").splitlines() if not ln.lstrip().startswith("#")]
    assert not [ln for ln in code if "pkill" in ln]
    assert any("streamlit.pid" in ln for ln in code)
