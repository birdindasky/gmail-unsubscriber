# -*- coding: utf-8 -*-
"""
Authentication module - Gmail OAuth 2.0 authorization.
Handles fetching and refreshing Google OAuth tokens, then returns a ready-to-use
Gmail API service object.

How it works:
1. On first run, it opens a browser for user authorization
2. After authorization, the token is saved to token.json (already gitignored)
3. On later runs, token.json is loaded automatically and refreshed if expired
"""

import os
import sys
import logging

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

logger = logging.getLogger(__name__)

# Gmail scope: modify allows reading and labeling messages, but not permanent deletion
# modify is used instead of readonly because unsubscribed emails need labels applied
SCOPES = ["https://www.googleapis.com/auth/gmail.modify"]

# Credentials file path (downloaded from Google Cloud Console)
CREDENTIALS_FILE = os.path.join(os.path.dirname(__file__), "credentials.json")

# Token cache file path (created automatically after first authorization)
TOKEN_FILE = os.path.join(os.path.dirname(__file__), "token.json")


def authenticate() -> Credentials:
    """
    Run the OAuth 2.0 flow and return a valid credentials object.

    Flow:
    - If token.json exists and is valid, use it directly
    - If the token is expired but has a refresh token, refresh it automatically
    - Otherwise, start the browser-based authorization flow

    Returns:
        google.oauth2.credentials.Credentials: Authenticated credentials object

    Raises:
        FileNotFoundError: Raised when credentials.json does not exist
        SystemExit: Exits the program if the user cancels authorization
    """
    if not os.path.exists(CREDENTIALS_FILE):
        logger.error("Could not find credentials.json. Download it from Google Cloud Console first.")
        print("\n❌ Error: credentials.json file not found")
        print("   See the Google Cloud Console setup steps in docs/USAGE_GUIDE.md")
        print(f"   Place the file at: {CREDENTIALS_FILE}")
        sys.exit(1)

    # Tighten credentials file permissions to 0o600 if they are too broad
    try:
        os.chmod(CREDENTIALS_FILE, 0o600)
    except OSError:
        pass

    creds = None

    # Try loading the token from the cache file
    if os.path.exists(TOKEN_FILE):
        try:
            creds = Credentials.from_authorized_user_file(TOKEN_FILE, SCOPES)
            logger.debug("Loaded token from token.json")
        except Exception as e:
            logger.warning(f"Failed to read token.json, re-authorizing: {e}")
            creds = None

    # Token is missing, invalid, or expired
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            # Token expired but can be refreshed
            try:
                logger.info("Token expired; refreshing automatically...")
                creds.refresh(Request())
                logger.info("Token refreshed successfully")
            except Exception as e:
                logger.warning(f"Token refresh failed, re-authorizing: {e}")
                creds = None

        if not creds:
            # Start the browser-based authorization flow
            print("\n🔐 Google account authorization required (first use)")
            print("   Your browser will open. Sign in and grant Gmail access...\n")
            try:
                flow = InstalledAppFlow.from_client_secrets_file(
                    CREDENTIALS_FILE, SCOPES
                )
                creds = flow.run_local_server(port=0)
                logger.info("OAuth authorization succeeded")
            except KeyboardInterrupt:
                print("\n\nAuthorization cancelled. Exiting.")
                sys.exit(0)
            except Exception as e:
                logger.error(f"OAuth authorization failed: {e}")
                print(f"\n❌ Authorization failed: {e}")
                sys.exit(1)

        # Save the token for future runs with 0o600 permissions
        try:
            fd = os.open(
                TOKEN_FILE,
                os.O_WRONLY | os.O_CREAT | os.O_TRUNC,
                0o600,
            )
            with os.fdopen(fd, "w") as f:
                f.write(creds.to_json())
            # os.open will not fix permissions on an existing file, so correct them explicitly
            os.chmod(TOKEN_FILE, 0o600)
            logger.debug(f"Saved token to {TOKEN_FILE}")
        except IOError as e:
            logger.warning(f"Failed to save token (does not affect this run): {e}")

    return creds


def get_gmail_service():
    """
    Return an authenticated Gmail API service object.

    Returns:
        googleapiclient.discovery.Resource: Gmail API service object

    Raises:
        SystemExit: Exits the program if authentication fails
    """
    creds = authenticate()
    try:
        service = build("gmail", "v1", credentials=creds)
        logger.info("Gmail API service initialized successfully")
        return service
    except HttpError as e:
        logger.error(f"Failed to initialize Gmail API: {e}")
        print(f"\n❌ Could not connect to the Gmail API: {e}")
        sys.exit(1)
