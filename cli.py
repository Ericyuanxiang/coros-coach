"""CLI commands for Coros AI Coach."""
import asyncio
import getpass
import sys
import time

from auth.storage import clear_token, get_token, is_keyring_available
from coros_api import TOKEN_TTL_MS, fetch_dashboard, get_env_credentials, get_stored_auth, login, login_mobile, try_auto_login


def _prompt_credentials() -> tuple[str, str, str]:
    """Prompt for email, password, and region. Returns (email, password, region)."""
    email = input("Email: ").strip()
    if not email:
        print("Error: email is required.")
        sys.exit(1)

    password = getpass.getpass("Password: ")
    if not password:
        print("Error: password is required.")
        sys.exit(1)

    print()
    print("Region options: eu, us, cn")
    region = input("Region [eu]: ").strip().lower() or "eu"
    if region not in ("eu", "us", "cn"):
        print(f"Warning: unknown region '{region}', using it anyway.")
    return email, password, region


def cmd_auth() -> int:
    """Authenticate with Coros credentials and store token in keyring."""
    print("Coros AI Coach -- Authentication")
    print()

    if is_keyring_available():
        print("Token will be stored in your system keyring.")
    else:
        print("System keyring not available -- token will be stored in an encrypted local file.")
    print()

    email, password, region = _prompt_credentials()
    print()
    print("Authenticating...")
    try:
        auth = asyncio.run(login(email, password, region, skip_mobile=False))
        print(f"[OK] Authenticated as user {auth.user_id} (region: {auth.region})")
        print("  Token stored securely. You only need to do this once.")
        return 0
    except Exception as e:
        print(f"[FAIL] Authentication failed: {e}")
        return 1


def cmd_auth_web() -> int:
    """Authenticate with Coros web API only (no mobile token)."""
    print("Coros AI Coach -- Web API Authentication")
    print()

    email, password, region = _prompt_credentials()
    print()
    print("Authenticating (web only)...")
    try:
        auth = asyncio.run(login(email, password, region, skip_mobile=True))
        print(f"[OK] Web API authenticated as user {auth.user_id} (region: {auth.region})")
        print("  Mobile token skipped -- sleep data will not be available.")
        return 0
    except Exception as e:
        print(f"[FAIL] Authentication failed: {e}")
        return 1


def cmd_auth_mobile() -> int:
    """Authenticate with Coros mobile API only (sleep + daily health)."""
    print("Coros AI Coach -- Mobile API Authentication")
    print()

    email, password, region = _prompt_credentials()
    print()
    print("Authenticating (mobile only)...")
    try:
        auth = asyncio.run(login_mobile(email, password, region))
        print(f"[OK] Mobile API authenticated (region: {auth.region})")
        print("  Sleep data is now available.")
        return 0
    except Exception as e:
        print(f"[FAIL] Mobile authentication failed: {e}")
        return 1


def cmd_auth_status() -> int:
    """Check whether valid tokens are stored."""
    auth = get_stored_auth()
    if auth:
        age_ms = int(time.time() * 1000) - auth.timestamp
        remaining_hours = round((TOKEN_TTL_MS - age_ms) / 3_600_000, 1)

        # Web token status
        if auth.access_token:
            print(f"[OK] Web API    -- user_id: {auth.user_id}, region: {auth.region}, expires in ~{remaining_hours}h")
        else:
            print("[FAIL] Web API    -- not authenticated")

        # Mobile token status
        if auth.mobile_access_token:
            print("[OK] Mobile API -- token present (sleep data available)")
        elif auth.mobile_login_payload:
            print("[WARN] Mobile API -- token expired (can auto-refresh)")
        else:
            print("[FAIL] Mobile API -- not authenticated (run 'coros-ai-coach auth' or 'coros-ai-coach auth-mobile')")

        return 0
    else:
        result = get_token()
        if result.success:
            print("[WARN] Token found but may be expired. Run 'coros-ai-coach auth' to re-authenticate.")
        else:
            print("[FAIL] Not authenticated. Run 'coros-ai-coach auth' to log in.")
        return 1


def cmd_auth_clear() -> int:
    """Remove stored token from all backends."""
    result = clear_token()
    if result.success:
        print("[OK] Token cleared.")
        return 0
    else:
        print(f"[FAIL] {result.message}")
        return 1


def cmd_serve() -> int:
    """Start the MCP server (stdio mode)."""
    import server
    server.main()
    return 0


def cmd_test() -> int:
    """Verify setup: Python, dependencies, auth, and API connectivity."""
    import importlib
    from pathlib import Path

    print("Coros AI Coach -- Setup Verification")
    print()

    all_ok = True

    # 1. Python version
    py_ver = f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
    if sys.version_info >= (3, 11):
        print(f"  [OK]  Python {py_ver}")
    else:
        print(f"  [FAIL]  Python {py_ver} -- need 3.11+")
        all_ok = False

    # 2. Dependencies
    deps = {
        "httpx": "httpx",
        "fastmcp": "fastmcp",
        "pydantic": "pydantic",
        "keyring": "keyring",
        "dotenv": "dotenv",
        "Crypto": "pycryptodome",
        "cryptography": "cryptography",
    }
    for mod, pkg in deps.items():
        try:
            importlib.import_module(mod)
            print(f"  [OK]  {pkg}")
        except ImportError:
            print(f"  [FAIL]  {pkg} -- not installed (run: pip install -e .)")
            all_ok = False

    # 3. Auth status
    auth = get_stored_auth()
    if auth and auth.access_token:
        print(f"  [OK]  Auth -- user_id: {auth.user_id}, region: {auth.region}")
    else:
        print("  [WARN]  Auth -- not yet authenticated")
        creds = get_env_credentials()
        if creds:
            print(f"     .env found ({creds[2]} region) -- attempting login...")
            try:
                auth = asyncio.run(try_auto_login())
                if auth and auth.access_token:
                    print(f"  [OK]  Auth -- login succeeded, user_id: {auth.user_id}")
                else:
                    print("  [FAIL]  Auth -- login failed, check COROS_EMAIL/PASSWORD in .env")
                    all_ok = False
            except Exception as e:
                print(f"  [FAIL]  Auth -- login error: {e}")
                all_ok = False
        else:
            print("     Create .env with COROS_EMAIL + COROS_PASSWORD, or run 'coros-ai-coach auth'")

    # 4. API connectivity (only if authenticated)
    if auth and auth.access_token:
        print("  ...  Testing API connectivity...")
        try:
            asyncio.run(fetch_dashboard(auth))
            print("  [OK]  API connectivity -- Coros servers reachable")
        except Exception as e:
            print(f"  [FAIL]  API connectivity failed -- {e}")
            all_ok = False

    print()
    if all_ok:
        print("[OK] All checks passed. Ready to use!")
    else:
        print("[WARN] Some checks failed. Fix issues above, then re-run 'coros-ai-coach test'.")
    return 0 if all_ok else 1


def cmd_help() -> int:
    print(
        """Coros AI Coach -- CLI

Usage:
  coros-ai-coach test           Verify setup: Python, deps, auth, API connectivity
  coros-ai-coach serve          Start the MCP server (used by Claude Code)
  coros-ai-coach auth           Authenticate with your Coros account (web + mobile)
  coros-ai-coach auth-web       Authenticate web API only (no sleep data)
  coros-ai-coach auth-mobile    Authenticate mobile API only (sleep + daily health)
  coros-ai-coach auth-status    Check status of both tokens
  coros-ai-coach auth-clear     Remove stored token
  coros-ai-coach help           Show this help message
"""
    )
    return 0


def main() -> None:
    command = sys.argv[1] if len(sys.argv) > 1 else "help"
    commands = {
        "test": cmd_test,
        "serve": cmd_serve,
        "auth": cmd_auth,
        "auth-web": cmd_auth_web,
        "auth-mobile": cmd_auth_mobile,
        "auth-status": cmd_auth_status,
        "auth-clear": cmd_auth_clear,
        "help": cmd_help,
        "--help": cmd_help,
        "-h": cmd_help,
    }
    if command in commands:
        sys.exit(commands[command]())
    else:
        print(f"Unknown command: {command}")
        print("Run 'coros-ai-coach help' for usage.")
        sys.exit(1)


if __name__ == "__main__":
    main()
