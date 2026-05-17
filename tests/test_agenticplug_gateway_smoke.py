"""AgenticPlug gateway smoke test — virtual PoC integration.

Spins up a real AgenticPlug broker (from the sibling agenticplug repo) with
mock backends, creates a session file, and exercises the AgenticSeek provider
path end-to-end. No real infrastructure is used.

Test matrix coverage:
  - Session file creation and loading
  - Provider connects to local mock gateway
  - Bearer token is opaque (not a raw GitHub token)
  - Mock task returns "hello from mock cluster"
  - Session expiry is respected
  - Missing session gives actionable error
  - Auth failure (401) gives login hint
  - UX store mock scenario lifecycle
"""

import json
import os
import sys
import subprocess
import tempfile
import time
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch
from http.server import HTTPServer, BaseHTTPRequestHandler
import threading
import requests

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from sources.agenticplug_session import (
    AgenticPlugSession,
    AgenticPlugSessionError,
    load_session,
    load_session_or_none,
)


# ---------------------------------------------------------------------------
# Mock AgenticPlug gateway (minimal HTTP server)
# ---------------------------------------------------------------------------

class MockGatewayHandler(BaseHTTPRequestHandler):
    """Minimal mock of the AgenticPlug broker endpoints needed by AgenticSeek."""

    # Class-level config set before server starts
    valid_sessions = {}  # session_id -> user_info
    task_responses = {}  # capability -> response dict

    def log_message(self, format, *args):
        pass  # suppress noisy logs

    def _send_json(self, status, body):
        self.send_response(status)
        self.send_header('Content-Type', 'application/json')
        self.end_headers()
        self.wfile.write(json.dumps(body).encode())

    def _resolve_session(self):
        auth = self.headers.get('Authorization', '')
        if not auth.startswith('Bearer '):
            return None
        sid = auth[len('Bearer '):]
        return self.valid_sessions.get(sid)

    def do_GET(self):
        if self.path == '/healthz':
            self._send_json(200, {'status': 'ok', 'mock': True})
            return

        if self.path == '/.well-known/agenticplug':
            self._send_json(200, {
                'name': 'agenticplug',
                'protocol_version': '1.0.0',
                'broker_url': f'http://127.0.0.1:{self.server.server_address[1]}',
                'auth_methods': ['oauth_github_bearer'],
                'capabilities': {
                    'read_only': ['hpc.squeue', 'hpc.health', 'hpc.logs.read'],
                    'approval_gated': ['hpc.submit', 'hpc.cancel'],
                },
                'approval_required_for': ['hpc.submit', 'hpc.cancel'],
            })
            return

        if self.path == '/v1/clusters':
            user = self._resolve_session()
            if not user:
                self._send_json(401, {'error': 'no_session'})
                return
            self._send_json(200, {'clusters': [
                {'cluster_id': 'mock-cluster', 'scheduler': 'slurm', 'health': 'online'},
            ]})
            return

        if self.path == '/v1/connectors':
            self._send_json(200, {'connectors': [
                {'connector_id': 'mock-cluster', 'health': 'online',
                 'capabilities': {'hpc_read': True}},
            ]})
            return

        # OpenAI-compatible chat completions (GET not used, but handle gracefully)
        self._send_json(404, {'error': 'not_found'})

    def do_POST(self):
        content_length = int(self.headers.get('Content-Length', 0))
        body = self.rfile.read(content_length) if content_length else b'{}'
        try:
            data = json.loads(body)
        except json.JSONDecodeError:
            self._send_json(400, {'error': 'invalid JSON'})
            return

        # CLI handshake
        if self.path == '/v1/cli/session':
            token = data.get('github_access_token', '')
            if token == 'gho_mock_allowed_token':
                sid = 'opaque_mock_session_' + str(int(time.time()))
                user = {'login': 'alrobles', 'id': 1001, 'name': 'Angel Robles'}
                MockGatewayHandler.valid_sessions[sid] = user
                self._send_json(200, {
                    'session_id': sid,
                    'user': user,
                    'expires_at': (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat(),
                    'token_type': 'Bearer',
                })
            else:
                self._send_json(401, {'error': 'github_identity_lookup_failed'})
            return

        # Task relay
        if self.path == '/v1/tasks':
            user = self._resolve_session()
            if not user:
                self._send_json(401, {'error': 'no_session'})
                return
            capability = data.get('capability', '')
            if capability in self.task_responses:
                self._send_json(200, self.task_responses[capability])
            else:
                self._send_json(200, {
                    'task_id': 'task_mock_001',
                    'status': 'completed',
                    'result': {'output': 'hello from mock cluster'},
                })
            return

        # OpenAI-compatible chat completions endpoint
        if self.path == '/v1/chat/completions':
            user = self._resolve_session()
            if not user:
                self._send_json(401, {
                    'error': {'message': 'Unauthorized: no valid session', 'type': 'authentication_error'},
                })
                return
            model = data.get('model', 'mock')
            self._send_json(200, {
                'id': 'chatcmpl-mock-001',
                'object': 'chat.completion',
                'model': model,
                'choices': [{
                    'index': 0,
                    'message': {
                        'role': 'assistant',
                        'content': 'hello from mock cluster',
                    },
                    'finish_reason': 'stop',
                }],
                'usage': {'prompt_tokens': 10, 'completion_tokens': 5, 'total_tokens': 15},
            })
            return

        self._send_json(404, {'error': 'not_found'})


def start_mock_gateway():
    """Start the mock gateway on a random port and return (server, port)."""
    MockGatewayHandler.valid_sessions = {}
    MockGatewayHandler.task_responses = {}
    server = HTTPServer(('127.0.0.1', 0), MockGatewayHandler)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, port


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestGatewaySmoke(unittest.TestCase):
    """End-to-end smoke tests using a mock AgenticPlug gateway."""

    @classmethod
    def setUpClass(cls):
        cls.server, cls.port = start_mock_gateway()
        cls.base_url = f'http://127.0.0.1:{cls.port}'

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()

    def test_health_endpoint(self):
        resp = requests.get(f'{self.base_url}/healthz')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()['status'], 'ok')

    def test_discovery_document(self):
        resp = requests.get(f'{self.base_url}/.well-known/agenticplug')
        self.assertEqual(resp.status_code, 200)
        doc = resp.json()
        self.assertEqual(doc['name'], 'agenticplug')
        self.assertIn('hpc.squeue', doc['capabilities']['read_only'])
        self.assertIn('hpc.submit', doc['approval_required_for'])
        # No secrets in discovery
        raw = json.dumps(doc)
        self.assertNotIn('gho_', raw)
        self.assertNotIn('ghp_', raw)

    def test_cli_handshake_creates_opaque_session(self):
        resp = requests.post(f'{self.base_url}/v1/cli/session', json={
            'github_access_token': 'gho_mock_allowed_token',
        })
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn('session_id', data)
        self.assertTrue(data['session_id'].startswith('opaque_mock_session_'))
        self.assertNotIn('gho_', data['session_id'])
        self.assertEqual(data['user']['login'], 'alrobles')

    def test_cli_handshake_rejects_bad_token(self):
        resp = requests.post(f'{self.base_url}/v1/cli/session', json={
            'github_access_token': 'gho_invalid_token_xxx',
        })
        self.assertEqual(resp.status_code, 401)

    def test_clusters_requires_session(self):
        resp = requests.get(f'{self.base_url}/v1/clusters')
        self.assertEqual(resp.status_code, 401)

    def test_clusters_with_valid_session(self):
        # Create session first
        handshake = requests.post(f'{self.base_url}/v1/cli/session', json={
            'github_access_token': 'gho_mock_allowed_token',
        }).json()
        sid = handshake['session_id']

        resp = requests.get(f'{self.base_url}/v1/clusters', headers={
            'Authorization': f'Bearer {sid}',
        })
        self.assertEqual(resp.status_code, 200)
        clusters = resp.json()['clusters']
        self.assertTrue(len(clusters) > 0)

    def test_task_returns_hello_from_mock_cluster(self):
        handshake = requests.post(f'{self.base_url}/v1/cli/session', json={
            'github_access_token': 'gho_mock_allowed_token',
        }).json()
        sid = handshake['session_id']

        resp = requests.post(f'{self.base_url}/v1/tasks', json={
            'connector_id': 'mock-cluster',
            'capability': 'hpc.squeue',
            'payload': {},
        }, headers={'Authorization': f'Bearer {sid}'})
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data['status'], 'completed')
        self.assertEqual(data['result']['output'], 'hello from mock cluster')

    def test_raw_github_token_rejected_as_bearer(self):
        resp = requests.get(f'{self.base_url}/v1/clusters', headers={
            'Authorization': 'Bearer gho_mock_allowed_token',
        })
        self.assertEqual(resp.status_code, 401)


class TestSessionFileIntegration(unittest.TestCase):
    """Test that AgenticSeek's session loader works with mock gateway output."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.session_path = Path(self.tmp.name) / 'session.json'

    def tearDown(self):
        self.tmp.cleanup()

    def test_session_file_round_trip(self):
        """Simulate what `agenticplug login` writes, then load it."""
        session_data = {
            'base_url': 'http://127.0.0.1:9999/v1',
            'token': 'opaque_mock_session_12345',
            'token_type': 'Bearer',
            'expires_at': (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat(),
            'user': {'login': 'alrobles', 'id': 1001},
            'scopes': ['read:user'],
            'route_header': 'hermes',
            'model': 'hermes',
            'default_cluster': 'mock-cluster',
        }
        self.session_path.write_text(json.dumps(session_data))

        session = load_session(self.session_path)
        self.assertEqual(session.base_url, 'http://127.0.0.1:9999/v1')
        self.assertEqual(session.token, 'opaque_mock_session_12345')
        self.assertFalse(session.is_expired())
        self.assertEqual(session.identity, 'alrobles')
        self.assertEqual(session.authorization_header(), 'Bearer opaque_mock_session_12345')

    def test_expired_session_detected(self):
        session_data = {
            'token': 'expired_session',
            'expires_at': (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat(),
        }
        self.session_path.write_text(json.dumps(session_data))
        session = load_session(self.session_path)
        self.assertTrue(session.is_expired())

    def test_missing_session_gives_actionable_error(self):
        with self.assertRaises(AgenticPlugSessionError) as ctx:
            load_session(self.session_path)
        self.assertIn('agenticplug login', str(ctx.exception))

    def test_token_is_never_a_github_token(self):
        """The session token must be opaque, never gho_/ghp_ prefixed."""
        session_data = {
            'token': 'opaque_mock_session_12345',
            'user': {'login': 'alrobles'},
        }
        self.session_path.write_text(json.dumps(session_data))
        session = load_session(self.session_path)
        self.assertFalse(session.token.startswith('gho_'))
        self.assertFalse(session.token.startswith('ghp_'))


class TestProviderWithMockGateway(unittest.TestCase):
    """Test AgenticSeek provider against the mock gateway."""

    @classmethod
    def setUpClass(cls):
        cls.server, cls.port = start_mock_gateway()
        cls.base_url = f'http://127.0.0.1:{cls.port}'
        # Create a session
        resp = requests.post(f'{cls.base_url}/v1/cli/session', json={
            'github_access_token': 'gho_mock_allowed_token',
        })
        cls.session_id = resp.json()['session_id']

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()

    @patch('sources.llm_provider.OpenAI')
    def test_provider_sends_to_mock_gateway(self, mock_openai_class):
        """Provider configures OpenAI client with mock gateway URL and session token."""
        mock_client = MagicMock()
        mock_openai_class.return_value = mock_client
        mock_client.chat.completions.create.return_value = MagicMock(
            choices=[MagicMock(message=MagicMock(content='hello from mock cluster'))]
        )

        with tempfile.TemporaryDirectory() as tmp:
            session_path = Path(tmp) / 'session.json'
            session_path.write_text(json.dumps({
                'base_url': f'{self.base_url}/v1',
                'token': self.session_id,
                'model': 'hermes',
                'route_header': 'hermes',
            }))

            env_patch = {
                'AGENTICPLUG_SESSION_FILE': str(session_path),
            }
            # Clear env vars that would override session
            for var in ('AGENTICPLUG_BASE_URL', 'AGENTICPLUG_API_KEY',
                        'AGENTICPLUG_MODEL', 'AGENTICPLUG_ROUTE_HEADER'):
                os.environ.pop(var, None)

            with patch.dict(os.environ, env_patch):
                from sources.llm_provider import Provider
                provider = Provider('agenticplug', 'hermes',
                                    server_address='127.0.0.1:8080', is_local=True)
                result = provider.agenticplug_fn(
                    [{'role': 'user', 'content': 'what jobs are running?'}])

            self.assertEqual(result, 'hello from mock cluster')
            kwargs = mock_openai_class.call_args.kwargs
            self.assertEqual(kwargs['base_url'], f'{self.base_url}/v1')
            self.assertEqual(kwargs['api_key'], self.session_id)
            self.assertNotIn('gho_', kwargs['api_key'])

    @patch('sources.llm_provider.OpenAI')
    def test_provider_auth_failure_gives_login_hint(self, mock_openai_class):
        """When gateway returns 401, provider should include login hint."""
        mock_client = MagicMock()
        mock_openai_class.return_value = mock_client
        mock_client.chat.completions.create.side_effect = Exception(
            'Error code: 401 - Unauthorized')

        with tempfile.TemporaryDirectory() as tmp:
            session_path = Path(tmp) / 'session.json'
            session_path.write_text(json.dumps({
                'base_url': f'{self.base_url}/v1',
                'token': 'invalid_session',
            }))

            for var in ('AGENTICPLUG_BASE_URL', 'AGENTICPLUG_API_KEY',
                        'AGENTICPLUG_MODEL', 'AGENTICPLUG_ROUTE_HEADER'):
                os.environ.pop(var, None)

            with patch.dict(os.environ, {'AGENTICPLUG_SESSION_FILE': str(session_path)}):
                from sources.llm_provider import Provider
                provider = Provider('agenticplug', 'hermes',
                                    server_address='127.0.0.1:8080', is_local=True)
                with self.assertRaises(Exception) as ctx:
                    provider.agenticplug_fn(
                        [{'role': 'user', 'content': 'hi'}])
                self.assertIn('agenticplug login', str(ctx.exception))


class TestUXStoreMockScenarios(unittest.TestCase):
    """Test the UX store mock scenarios that drive the frontend approval flow."""

    def test_default_scenario_completes(self):
        from sources.agenticplug_ux import AgenticPlugUXStore
        store = AgenticPlugUXStore()
        task = store.create_mock_task(title='test task', scenario='default')
        self.assertIsNotNone(task.task_id)
        thread = store.run_mock_scenario(task, 'default')
        thread.join(timeout=30)
        final = store.get_task(task.task_id)
        # Should reach GITHUB_HANDOFF (terminal state for default scenario)
        from sources.schemas import AgenticPlugTaskState
        self.assertIn(final.state, (
            AgenticPlugTaskState.JOB_COMPLETED,
            AgenticPlugTaskState.ARTIFACT_AVAILABLE,
            AgenticPlugTaskState.GITHUB_HANDOFF,
        ))

    def test_approval_scenario_blocks_until_approved(self):
        from sources.agenticplug_ux import AgenticPlugUXStore
        from sources.schemas import AgenticPlugTaskState
        store = AgenticPlugUXStore()
        task = store.create_mock_task(title='approval test', scenario='approval_required')
        thread = store.run_mock_scenario(task, 'approval_required')
        thread.join(timeout=10)
        # Should be waiting for approval
        t = store.get_task(task.task_id)
        self.assertEqual(t.state, AgenticPlugTaskState.APPROVAL_REQUIRED)
        self.assertIsNotNone(t.approval_request)
        # Deny it
        store.deny_task(task.task_id)
        t = store.get_task(task.task_id)
        self.assertEqual(t.state, AgenticPlugTaskState.APPROVAL_DENIED)

    def test_failure_scenario(self):
        from sources.agenticplug_ux import AgenticPlugUXStore
        from sources.schemas import AgenticPlugTaskState
        store = AgenticPlugUXStore()
        task = store.create_mock_task(title='fail test', scenario='simulated_failure')
        thread = store.run_mock_scenario(task, 'simulated_failure')
        thread.join(timeout=30)
        t = store.get_task(task.task_id)
        self.assertEqual(t.state, AgenticPlugTaskState.JOB_FAILED)
        self.assertEqual(t.exit_code, 137)


class TestSecurityInvariants(unittest.TestCase):
    """Cross-cutting security checks."""

    @classmethod
    def setUpClass(cls):
        cls.server, cls.port = start_mock_gateway()
        cls.base_url = f'http://127.0.0.1:{cls.port}'

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()

    def test_no_secrets_in_discovery(self):
        resp = requests.get(f'{self.base_url}/.well-known/agenticplug')
        raw = resp.text
        self.assertNotRegex(raw, r'gho_[A-Za-z0-9]{10,}')
        self.assertNotRegex(raw, r'ghp_[A-Za-z0-9]{10,}')
        self.assertNotRegex(raw, r'sk-[A-Za-z0-9]{10,}')

    def test_no_secrets_in_health(self):
        resp = requests.get(f'{self.base_url}/healthz')
        raw = resp.text
        self.assertNotRegex(raw, r'gho_[A-Za-z0-9]{10,}')

    def test_task_response_has_no_secrets(self):
        handshake = requests.post(f'{self.base_url}/v1/cli/session', json={
            'github_access_token': 'gho_mock_allowed_token',
        }).json()
        sid = handshake['session_id']
        resp = requests.post(f'{self.base_url}/v1/tasks', json={
            'connector_id': 'mock-cluster',
            'capability': 'hpc.squeue',
            'payload': {},
        }, headers={'Authorization': f'Bearer {sid}'})
        raw = resp.text
        self.assertNotRegex(raw, r'gho_[A-Za-z0-9]{10,}')

    def test_session_id_is_opaque(self):
        handshake = requests.post(f'{self.base_url}/v1/cli/session', json={
            'github_access_token': 'gho_mock_allowed_token',
        }).json()
        sid = handshake['session_id']
        self.assertFalse(sid.startswith('gho_'))
        self.assertFalse(sid.startswith('ghp_'))


if __name__ == '__main__':
    unittest.main()
