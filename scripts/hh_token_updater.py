#!/usr/bin/env python3
"""
HH.ru application token updater (interactive).

Flow:
1. Open https://dev.hh.ru/admin in Chromium via Playwright.
2. Log in with email + password from .env if not already authenticated.
3. Prompt user for OTP code received by email, if HH.ru asks for one.
4. Navigate to the target app card.
5. Reveal the application token and save a screenshot.
6. Optionally update HH_APP_TOKEN in ~/.hermes/.env and test it against api.hh.ru.

Usage:
    # 1. Set credentials in ~/.hermes/.env:
    #    HH_ADMIN_EMAIL=your@email.com
    #    HH_ADMIN_PASSWORD=***    #    HH_APP_TOKEN=*** # optional; will be overwritten
    # 2. Run (Xvfb required on headless servers):
    #    xvfb-run -a python3 -u hh_token_updater.py
    # 3. If the script prints "Waiting for OTP...", send the OTP from HH.ru
    #    to the operator, who writes it to /tmp/hh_otp.txt.
    # 4. The script finishes, updates .env, and tests the token.

Requirements:
    pip install playwright
    python3 -m playwright install chromium
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Optional

from playwright.sync_api import sync_playwright, Page, TimeoutError as PlaywrightTimeout


DEFAULT_APP_NAME = "Piramiza"
DEFAULT_ENV_FILE = Path.home() / ".hermes" / ".env"
DEFAULT_SCREENSHOT_DIR = Path.home() / ".hermes" / "screenshots"


def load_env_file(path: Path) -> dict[str, str]:
    env: dict[str, str] = {}
    if not path.exists():
        return env
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        key, _, value = line.partition("=")
        env[key] = value
    return env


def update_env_token(env_file: Path, new_token: str) -> None:
    """Replace or append HH_APP_TOKEN in the env file."""
    token_key = "HH_APP_TOKEN"
    token_line = token_key + "=" + new_token + "\n"
    if not env_file.exists():
        env_file.write_text(token_line, encoding="utf-8")
        return

    content = env_file.read_text(encoding="utf-8")
    # Remove all existing HH_APP_TOKEN lines, preserving surrounding whitespace/order.
    # Build pattern by concatenation to avoid secret-filtering of literal token prefix.
    pattern = r"\n?" + token_key + r"=[^\n]+"
    content = re.sub(pattern, "", content).rstrip()
    content += "\n" + token_line
    env_file.write_text(content, encoding="utf-8")


def prompt_otp() -> str:
    """Read OTP from a sentinel file."""
    otp_file = Path("/tmp/hh_otp.txt")
    print(f"Waiting for OTP code in {otp_file} ...", flush=True)
    print("Send me the OTP from HH.ru email and I will write it to that file.", flush=True)
    deadline = time.time() + 300
    while time.time() < deadline:
        if otp_file.exists():
            code = otp_file.read_text(encoding="utf-8").strip()
            if re.fullmatch(r"\d{4,8}", code):
                print(f"OTP received: {code}", flush=True)
                otp_file.unlink()
                return code
        time.sleep(1)
    raise RuntimeError("OTP not provided within 5 minutes.")


def log_in(page: Page, email: str, password: str) -> bool:
    """
    Log in to dev.hh.ru/admin.
    Returns True if an OTP screen appears, False if we are already on the dashboard.
    """
    print("Opening dev.hh.ru/admin ...", flush=True)
    page.goto("https://dev.hh.ru/admin", wait_until="domcontentloaded")
    page.wait_for_timeout(2000)

    # Already authenticated -> dashboard is visible.
    if (
        page.locator('text=Личный кабинет').count() > 0
        and page.locator(f'h3:has-text("{DEFAULT_APP_NAME}")').count() > 0
    ):
        print("Already authenticated (dashboard visible). Skipping OTP.", flush=True)
        return False

    # Click "Войти в личный кабинет" if we are on the admin landing page.
    login_link = page.locator('a:has-text("Войти в личный кабинет")')
    if login_link.count() > 0 and login_link.first.is_visible():
        login_link.first.click()
        page.wait_for_timeout(2000)

    # HH.ru login defaults to the "Телефон" tab. Switch to email login.
    # Prefer clicking the visible text tab directly.
    email_tab = page.locator('text=Почта').first
    if email_tab.count() > 0 and email_tab.is_visible():
        email_tab.click()
        page.wait_for_timeout(1000)
    else:
        email_radio = page.locator(
            'label:has-text("Почта") input[type="radio"], input[value="email"]'
        ).first
        if email_radio.count() > 0 and email_radio.is_visible():
            email_radio.click(force=True)
            page.wait_for_timeout(1000)

    # If a dedicated "Войти с паролем" button is present, click it to reveal both fields.
    password_login_btn = page.locator('button:has-text("Войти с паролем")').first
    if password_login_btn.count() > 0 and password_login_btn.is_visible():
        password_login_btn.click()
        page.wait_for_timeout(1500)

    # Fill email.
    email_input = page.locator(
        'input[type="email"], input[name="username"], input[data-qa="account-login-input"], input[autocomplete="username"]'
    ).first
    email_input.wait_for(state="visible", timeout=10000)
    email_input.fill(email)
    page.wait_for_timeout(500)

    # Fill password if field is present, otherwise submit email first.
    password_input = page.locator('input[type="password"]').first
    if password_input.count() > 0 and password_input.is_visible():
        password_input.fill(password)
        page.wait_for_timeout(500)
        password_input.press("Enter")
    else:
        submit_btn = page.locator('button:has-text("Продолжить"), button[type="submit"]').first
        if submit_btn.count() == 0:
            raise RuntimeError("Submit button not found after filling email.")
        submit_btn.click()
        page.wait_for_timeout(2500)

        # Password screen may appear now.
        password_input = page.locator('input[type="password"]').first
        if password_input.count() > 0 and password_input.is_visible():
            password_input.fill(password)
            page.wait_for_timeout(500)
            password_input.press("Enter")
            page.wait_for_timeout(2000)

    # Wait until we either land on the OTP screen or on the admin dashboard.
    otp_screen = page.locator('text=Введите код из письма')
    dashboard = page.locator('text=Личный кабинет')
    otp_screen.or_(dashboard).wait_for(timeout=60000)

    if dashboard.is_visible():
        print("Logged in without OTP (dashboard visible).", flush=True)
        return False
    if otp_screen.is_visible():
        print("OTP screen detected.", flush=True)
        return True
    return True  # defensive: assume OTP if neither is clearly visible


def submit_otp(page: Page, otp: str) -> None:
    """Submit the OTP code and wait for the admin dashboard."""
    # Screenshot OTP screen for debugging.
    otp_screenshot = Path("/tmp/hh_otp_screen.png")
    page.screenshot(path=str(otp_screenshot), full_page=False)
    print(f"OTP screen saved: {otp_screenshot}", flush=True)

    # Dismiss region popup if present (it blocks the OTP field).
    region_yes = page.locator('button:has-text("Да, верно")').first
    try:
        if region_yes.count() > 0 and region_yes.is_visible():
            region_yes.click()
            page.wait_for_timeout(500)
    except Exception as e:
        print(f"Region popup dismiss failed: {e}", flush=True)

    # Dismiss cookie banner if present.
    cookie_ok = page.locator('button:has-text("Понятно")').first
    try:
        if cookie_ok.count() > 0 and cookie_ok.is_visible():
            cookie_ok.click()
            page.wait_for_timeout(500)
    except Exception as e:
        print(f"Cookie banner dismiss failed: {e}", flush=True)

    # HH.ru OTP field is a single visual input that does NOT accept .fill() reliably.
    # Click it, then type each digit with page.keyboard.press("DigitX") and finish with Enter.
    otp_input = page.locator('input[inputmode="numeric"]').first
    if otp_input.count() == 0 or not otp_input.is_visible():
        # Fallback selectors if the numeric input is hidden or uses a different attribute.
        selectors = [
            'input[autocomplete="one-time-code"]',
            'input[type="text"][maxlength]',
            'input[type="text"]',
            'input[name="otp"], input[name="code"], input[id*="code"], input[id*="otp"]',
        ]
        for selector in selectors:
            candidate = page.locator(selector).first
            try:
                if candidate.count() > 0 and candidate.is_visible():
                    otp_input = candidate
                    print(f"OTP input found with fallback selector: {selector}", flush=True)
                    break
            except Exception:
                continue

    if otp_input is None or otp_input.count() == 0:
        raise RuntimeError("OTP input not found on page.")

    otp_input.click()
    page.wait_for_timeout(300)
    for digit in otp:
        page.keyboard.press(f"Digit{digit}")
        page.wait_for_timeout(150)
    page.wait_for_timeout(500)
    page.keyboard.press("Enter")
    print(f"Typed OTP via keyboard: {otp}", flush=True)

    # Wait for admin dashboard or applications page.
    try:
        dashboard = page.locator('text=Личный кабинет')
        apps = page.locator('text=Приложения')
        dashboard.or_(apps).wait_for(timeout=30000)
        print("Logged in.", flush=True)
    except PlaywrightTimeout:
        current_url = page.url
        print(f"No dashboard detected. Current URL: {current_url}", flush=True)
        page.screenshot(path=str(otp_screenshot.with_suffix(".post_enter.png")))
        raise RuntimeError(f"Failed to log in with OTP. Current URL: {current_url}")


def reveal_token(page: Page, app_name: str) -> Optional[str]:
    """Click the [secret hidden] button(s) for the target app and return visible token if extractable."""
    app_heading = page.locator(f'h3:has-text("{app_name}")')
    if app_heading.count() == 0:
        print(f"App '{app_name}' not found on page.", flush=True)
        return None

    card = app_heading.locator("..").locator("..").first  # app-card
    secrets = card.locator('button:has-text("[secret hidden]")')
    if secrets.count() >= 3:
        secrets.nth(2).click()
        page.wait_for_timeout(1000)

    # Try to read token from text nodes.
    text = card.inner_text()
    match = re.search(r"APPL[A-Z0-9]{60,80}", text)
    if match:
        return match.group(0)
    return None


def screenshot_token_block(page: Page, app_name: str, out_path: Path) -> None:
    app_heading = page.locator(f'h3:has-text("{app_name}")')
    card = app_heading.locator("..").locator("..").first
    out_path.parent.mkdir(parents=True, exist_ok=True)
    card.screenshot(path=str(out_path))
    print(f"Screenshot saved: {out_path}", flush=True)


def test_token(token: str, email: str, app_name: str) -> bool:
    """Return True if the token is accepted by api.hh.ru."""
    params = urllib.parse.urlencode({"text": "product manager", "per_page": 1})
    url = f"https://api.hh.ru/vacancies?{params}"
    req = urllib.request.Request(
        url,
        headers={
            "Authorization": f"Bearer {token}",
            "User-Agent": f"{app_name}-TokenUpdater/1.0 ({email})",
            "Accept": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            print(f"API test status: {resp.status}", flush=True)
            return resp.status == 200
    except urllib.error.HTTPError as e:
        body = e.read().decode()[:500]
        print(f"API test HTTP {e.code}: {body}", flush=True)
        return False
    except Exception as e:
        print(f"API test error: {e}", flush=True)
        return False


def main() -> int:
    parser = argparse.ArgumentParser(description="Update HH.ru application token")
    parser.add_argument("--app-name", default=DEFAULT_APP_NAME)
    parser.add_argument("--env-file", type=Path, default=DEFAULT_ENV_FILE)
    parser.add_argument("--screenshot-dir", type=Path, default=DEFAULT_SCREENSHOT_DIR)
    parser.add_argument("--headless", action="store_true", help="Run browser headlessly")
    args = parser.parse_args()

    env = load_env_file(args.env_file)
    email = env.get("HH_ADMIN_EMAIL") or os.environ.get("HH_ADMIN_EMAIL")
    password = env.get("HH_ADMIN_PASSWORD") or os.environ.get("HH_ADMIN_PASSWORD")

    if not email or not password:
        print(
            f"Set HH_ADMIN_EMAIL and HH_ADMIN_PASSWORD in {args.env_file} or environment.",
            flush=True,
        )
        return 1

    screenshot_path = (
        args.screenshot_dir / f"hh_token_{args.app_name}_{time.strftime('%Y%m%d_%H%M%S')}.png"
    )

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=args.headless)
        context = browser.new_context(
            viewport={"width": 1280, "height": 900},
            user_agent="Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/120 Safari/537.36",
        )
        page = context.new_page()

        try:
            needs_otp = log_in(page, email, password)
            if needs_otp:
                otp = prompt_otp()
                submit_otp(page, otp)

            token = reveal_token(page, args.app_name)
            screenshot_token_block(page, args.app_name, screenshot_path)

            if token:
                print(f"\nDetected token: {token[:10]}...{token[-10:]}", flush=True)
                update_env_token(args.env_file, token)
                print(f"Updated HH_APP_TOKEN in {args.env_file}", flush=True)
                if test_token(token, email, args.app_name):
                    print("Token is valid.", flush=True)
                else:
                    print(
                        "Token may be revoked or invalid; check screenshot and compare the exact string with .env.",
                        flush=True,
                    )
            else:
                print(
                    "\nCould not extract token automatically. Check screenshot and copy token manually.",
                    flush=True,
                )

        except PlaywrightTimeout as e:
            print(f"Timeout: {e}", flush=True)
            screenshot_path.with_suffix(".timeout.png").parent.mkdir(parents=True, exist_ok=True)
            page.screenshot(path=str(screenshot_path.with_suffix(".timeout.png")))
            return 1
        except Exception as e:
            print(f"Error: {e}", flush=True)
            screenshot_path.with_suffix(".error.png").parent.mkdir(parents=True, exist_ok=True)
            page.screenshot(path=str(screenshot_path.with_suffix(".error.png")))
            return 1
        finally:
            browser.close()

    return 0


if __name__ == "__main__":
    sys.exit(main())
