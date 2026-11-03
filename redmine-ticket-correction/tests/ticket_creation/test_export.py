import json
from urllib.parse import parse_qs, urlsplit

import pytest

from ticket_tools.ticket_creation import redmine_to_markdown as exporter
from ticket_tools.ticket_creation import create_children_from_markdown as children


@pytest.mark.parametrize("base_url", ["https://redmine.example", "https://redmine.example/redmine"])
def test_export_preserves_configured_base_path(monkeypatch, base_url):
    requests = []

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self):
            if len(requests) == 1:
                return json.dumps({"issues": [{"id": 1}], "total_count": 1}).encode()
            return json.dumps({"issue": {"id": 1, "subject": "Demo action"}}).encode()

    class Opener:
        def open(self, request, timeout):
            requests.append(request.full_url)
            assert timeout == 30
            assert request.get_header("X-redmine-api-key") == "test-only-key"
            return Response()

    monkeypatch.setattr(exporter.ApiClient, "_build_opener", lambda self: Opener())
    client = exporter.RedmineClient(base_url, "test-only-key")
    assert client.list_issue_ids("demo") == [1]
    issue = client.get_issue_detail(1)
    assert requests[0].startswith(base_url + "/issues.json?")
    assert parse_qs(urlsplit(requests[0]).query)["project_id"] == ["demo"]
    assert requests[1].startswith(base_url + "/issues/1.json?")
    assert exporter.issue_to_row(issue, base_url)["url"] == base_url + "/issues/1"


def test_export_defaults_to_verified_tls():
    client = exporter.RedmineClient("https://redmine.example", "test-only-key")
    assert client.verify_ssl is True


def test_cli_rejects_api_key_argument(monkeypatch):
    monkeypatch.setattr("sys.argv", ["export", "--project", "demo", "--api-key", "test-only-key"])
    with pytest.raises(SystemExit) as exc:
        exporter.parse_args()
    assert exc.value.code == 2


@pytest.mark.parametrize("base_url", ["https://redmine.example", "https://redmine.example/redmine"])
def test_supplementary_child_client_uses_relative_paths(monkeypatch, base_url):
    calls = []

    def request(self, method, path, payload=None):
        calls.append((method, path))
        assert self.base_url == base_url
        assert self.verify_ssl is True
        return {}

    monkeypatch.setattr(children.ApiClient, "request_json", request)
    client = children.RedmineClient(base_url, "test-only-key")
    client.list_trackers()
    client.create_issue("demo", 1, 2, "Demo", "Demo")
    client.update_issue(3, 1, 2, "Demo", "Demo")
    client.list_child_issues("demo", 1)
    assert calls == [("GET", "trackers.json"), ("POST", "issues.json"), ("PUT", "issues/3.json"), ("GET", "issues.json")]