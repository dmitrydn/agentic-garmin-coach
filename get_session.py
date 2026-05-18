import os, pathlib, sys
from garminconnect import Garmin

SESSION_FILE = pathlib.Path(__file__).parent / ".garmin_session"

def main():
    email = os.environ.get("GARMIN_EMAIL")
    password = os.environ.get("GARMIN_PASSWORD")

    if not email or not password:
        print("Please set GARMIN_EMAIL and GARMIN_PASSWORD environment variables.")
        sys.exit(1)

    if SESSION_FILE.exists():
        print(f"Session already exists at {SESSION_FILE}. Testing login...")
        c = Garmin(email, password)
        c.login(str(SESSION_FILE))
        print("Login with existing session successful!")
    else:
        print("Session not found. Attempting interactive login (MFA may be prompted)...")
        c = Garmin(email, password, prompt_mfa=lambda: input("Garmin MFA code: "))
        c.login()
        c.garth.dump(str(SESSION_FILE))
        print(f"Session successfully saved to → {SESSION_FILE}")

if __name__ == "__main__":
    main()
