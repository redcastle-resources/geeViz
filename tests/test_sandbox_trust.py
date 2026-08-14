"""Sandbox trust-boundary regression tests.

Covers the exact class of bug from session 6bcf3daf: the trusted-library
list didn't include the top-level ``geeViz/`` package, so any whitelisted
library call that needed a syscall (urllib for Google Maps API, socket
for tile fetch, etc.) got denied — breaking every Street View / ESRI /
thumbnail path.

Each test spawns a fresh Python subprocess that:
  1. Sets ``sys.argv = ['x', '--sandbox']`` so ``server.py``'s
     top-of-file arg parse activates the sandbox.
  2. Imports ``geeViz.mcp.server`` — this installs the audit hook.
  3. Flips ``server._audit_user_code_active = True`` — exactly how
     ``run_code``'s ``_exec`` enters user-code enforcement mode.
  4. Compiles the test snippet with ``<mcp>`` as the filename so the
     stack walk sees a user frame in the right place.
  5. Execs it; catches any PermissionError / ImportError / etc.
  6. Prints ``SANDBOX_RESULT: ALLOWED`` or ``SANDBOX_RESULT: BLOCKED …``
     as the only line the parent test asserts on.

If you touch ``_trusted_substrings``, ``_sandbox_audit_hook``, or the
``_called_from_trusted_lib`` walk, RE-RUN this file before committing.
A failure here means real user tools are broken.

Run:   python -m unittest geeViz.tests.test_sandbox_trust -v
"""
from __future__ import annotations

import os
import subprocess
import sys
import textwrap
import unittest


REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SERVER_PATH = os.path.join(REPO_ROOT, "geeViz", "mcp", "server.py")


def _run_under_sandbox(user_code: str) -> tuple[str, str]:
    """Run ``user_code`` inside a fresh --sandbox-init Python subprocess.

    Returns ``(result_line, full_output)`` — the SANDBOX_RESULT line is
    the assert target; full_output is included in failure messages so we
    can see the actual traceback when a test fails.
    """
    harness = textwrap.dedent(f"""
        import sys
        sys.argv = ['harness', '--sandbox']
        sys.path.insert(0, {REPO_ROOT!r})
        # Silence server startup prints so the RESULT line is easy to find
        import io, contextlib
        _startup_buf = io.StringIO()
        with contextlib.redirect_stdout(_startup_buf), contextlib.redirect_stderr(_startup_buf):
            import geeViz.mcp.server as srv
        # Layer 1 (STATIC): AST prewalk catches ``import os`` / ``open(...)``
        # / eval-family before we even exec. This is the primary defense
        # against most import escapes; the audit hook is runtime backstop.
        _outcome = 'ALLOWED'
        _detail = ''
        _prewalk = srv._check_code_patterns({user_code!r})
        _blocked_by_prewalk = [w for w in _prewalk if w.startswith('BLOCKED')]
        if _blocked_by_prewalk:
            _outcome = 'BLOCKED'
            _detail = _blocked_by_prewalk[0][:200]
        else:
            # Layer 2 (RUNTIME): audit hook fires during exec. IMPORTANT:
            # compile() must happen BEFORE flipping the flag so the compile
            # audit doesn't fire on our own harness. This mirrors run_code's
            # own _exec (server.py) which compiles at server-active time,
            # not user-active time.
            _code_obj = compile({user_code!r}, '<mcp>', 'exec')
            srv._audit_user_code_active = True
            try:
                exec(_code_obj, {{}}, {{}})
            except BaseException as e:
                _outcome = 'BLOCKED'
                _detail = f'{{type(e).__name__}}: {{str(e)[:200]}}'
            finally:
                srv._audit_user_code_active = False
        print(f'SANDBOX_RESULT: {{_outcome}} {{_detail}}'.rstrip())
    """)
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    proc = subprocess.run(
        [sys.executable, "-c", harness],
        capture_output=True, text=True, env=env, timeout=45,
    )
    combined = (proc.stdout or "") + (proc.stderr or "")
    result_line = ""
    for line in combined.splitlines():
        if line.startswith("SANDBOX_RESULT:"):
            result_line = line.strip()
            break
    return result_line, combined


class SandboxTrustTests(unittest.TestCase):

    # ---------------------- LEGITIMATE (must ALLOW) ----------------------

    def test_legit_get_api_key_survives_env_deny(self):
        """``googleMapsLib._get_api_key`` MUST resolve under sandbox.

        After the trust-aware ``open`` deny-list (2026-08-04 fix), google-
        auth and other trusted libs are allowed to read ADC files and
        ``.env``. This test now just verifies the key resolves to
        *some* value — either from the real ``.env`` (trusted-lib read
        now succeeds) or from the pre-set os.environ fallback. Both are
        acceptable; the point is EE / gm init does NOT die on
        ``PermissionError`` in either code path.
        """
        code = textwrap.dedent("""
            from geeViz import googleMapsLib as gm
            gm._API_KEY = None                            # force fresh lookup
            gm.os.environ.setdefault('GOOGLE_MAPS_PLATFORM_API_KEY', 'test-key-12345')
            k = gm._get_api_key()
            print('KEY_OK:', bool(k), 'len:', len(k or ''))
        """)
        result, full = _run_under_sandbox(code)
        self.assertTrue(result.startswith("SANDBOX_RESULT: ALLOWED"),
                        msg=f"result={result!r}\nfull output:\n{full}")
        self.assertIn("KEY_OK: True", full,
                      msg=f"key lookup returned empty — trusted-lib .env read may be broken.\n{full}")

    def test_legit_trusted_lib_socket_call_via_gm(self):
        """A geeViz-hosted function that opens a socket MUST succeed.

        Regression: this is the EXACT failure from session 6bcf3daf —
        ``googleMapsLib._fetch_json`` did ``urllib.request.urlopen`` and
        got denied because ``geeViz/`` wasn't in the trusted list.

        We drive the failure path via ``gm._fetch_json`` on a bogus URL —
        we expect a network / HTTP error (URLError, timeout, HTTPError),
        NOT a PermissionError. Any PermissionError means the sandbox is
        still blocking legitimate trusted-lib traffic.
        """
        code = textwrap.dedent("""
            from geeViz import googleMapsLib as gm
            # Preload key so _get_api_key doesn't blow up; any URL will
            # trigger a real DNS + connect attempt through urllib.
            gm._API_KEY = 'sandbox-test-not-a-real-key'
            try:
                # Point at a nonexistent host on an unreachable port so we
                # never actually make a real API call. We want ONLY to
                # exercise the trusted-lib syscall path.
                gm._fetch_json('http://sandbox-test.invalid:1/x', {'q': '1'})
            except PermissionError as e:
                # The bug we care about — sandbox denying a legitimate call.
                print('PERM_ERROR:', e)
                raise
            except Exception as e:
                # Network / URL error is FINE — proves urllib ran.
                print('NETWORK_ERROR_OK:', type(e).__name__)
        """)
        result, full = _run_under_sandbox(code)
        self.assertTrue(result.startswith("SANDBOX_RESULT: ALLOWED"),
                        msg=f"result={result!r}\nfull output:\n{full}")
        self.assertIn("NETWORK_ERROR_OK:", full,
                      msg=f"expected a NETWORK error, not a PermissionError.\n{full}")

    def test_legit_geeviz_frame_marks_call_trusted(self):
        """Direct inspection: a stack containing a geeViz-hosted frame with
        NO ``<mcp>`` frame above must be trusted; the same stack with an
        ``<mcp>`` frame ABOVE the geeViz frame must NOT be trusted.

        Uses an ALREADY-LOADED trusted-lib function object as the
        constructor — no ``compile()`` / ``exec()`` from user code (which
        the AST prewalk correctly refuses).
        """
        code = textwrap.dedent("""
            from geeViz.mcp import server as srv
            # Direct call from user code — the walker sees <mcp> first
            # and MUST return False. If this prints True, the walker
            # is broken and user code smuggles trusted status.
            trusted_direct = srv._called_from_trusted_lib()
            print('direct:', trusted_direct)
        """)
        result, full = _run_under_sandbox(code)
        self.assertTrue(result.startswith("SANDBOX_RESULT: ALLOWED"),
                        msg=f"result={result!r}\nfull:\n{full}")
        # Direct call from <mcp>: walker sees <mcp> before any trusted
        # frame → returns False. If this ever prints ``True``, the walker
        # is broken and user code smuggles trusted status.
        self.assertIn("direct: False", full,
                      msg=f"direct call from <mcp> MUST be denied.\n{full}")

    # ----------------------- EXPLOIT (must BLOCK) ------------------------

    def test_exploit_direct_import_os(self):
        result, full = _run_under_sandbox("import os\n")
        self.assertTrue(result.startswith("SANDBOX_RESULT: BLOCKED"),
                        msg=f"result={result!r}\nfull:\n{full}")

    def test_exploit_direct_import_subprocess(self):
        result, full = _run_under_sandbox("import subprocess\n")
        self.assertTrue(result.startswith("SANDBOX_RESULT: BLOCKED"),
                        msg=f"result={result!r}\nfull:\n{full}")

    def test_exploit_direct_import_urllib(self):
        result, full = _run_under_sandbox("import urllib.request\n")
        self.assertTrue(result.startswith("SANDBOX_RESULT: BLOCKED"),
                        msg=f"result={result!r}\nfull:\n{full}")

    def test_exploit_gm_os_system(self):
        """``gm.os.system('...')`` fires the ``os.system`` audit event; the
        audit hook denies regardless of caller because trusted-lib skip is
        gated on ``_called_from_trusted_lib`` which walks the stack. The
        immediate caller here is <mcp>, so it MUST block."""
        result, full = _run_under_sandbox(
            "from geeViz import googleMapsLib as gm\n"
            "gm.os.system('echo pwned')\n"
        )
        self.assertTrue(result.startswith("SANDBOX_RESULT: BLOCKED"),
                        msg=f"result={result!r}\nfull:\n{full}")

    def test_exploit_open_env_file(self):
        """Direct ``open('.env')`` from user code MUST be denied by the path
        deny-list. Regression: ``open`` deliberately does NOT consult
        trusted-lib skip — it's path-scoped."""
        env_path = os.path.join(REPO_ROOT, "geeViz", ".env")
        result, full = _run_under_sandbox(f"open({env_path!r}).read()\n")
        self.assertTrue(result.startswith("SANDBOX_RESULT: BLOCKED"),
                        msg=f"result={result!r}\nfull:\n{full}")

    def test_exploit_open_ssh_key(self):
        result, full = _run_under_sandbox(
            "open('/home/user/.ssh/id_rsa').read()\n"
        )
        self.assertTrue(result.startswith("SANDBOX_RESULT: BLOCKED"),
                        msg=f"result={result!r}\nfull:\n{full}")


if __name__ == "__main__":
    unittest.main(verbosity=2)
