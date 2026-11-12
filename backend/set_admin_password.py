"""Set the admin login. Prompts for a password (hidden) and writes ../.env."""
import getpass
import pathlib
import re
import secrets

import bcrypt

env = pathlib.Path(__file__).resolve().parent.parent / ".env"
example = env.with_name(".env.example")
text = env.read_text() if env.exists() else example.read_text()

user = input("Admin username [admin]: ").strip() or "admin"
pw = getpass.getpass("Admin password (min 10 chars): ")
if len(pw) < 10 or pw != getpass.getpass("Repeat password: "):
    raise SystemExit("Passwords must match and be at least 10 characters.")

hashed = bcrypt.hashpw(pw.encode(), bcrypt.gensalt()).decode()


def setvar(t, key, val):
    line = f"{key}={val}"
    return re.sub(rf"^{key}=.*$", lambda _: line, t, flags=re.M) if re.search(rf"^{key}=", t, re.M) else t + "\n" + line + "\n"


text = setvar(text, "ADMIN_USERNAME", user)
# Single quotes: bcrypt hashes contain "$", which Docker Compose would otherwise try to expand.
text = setvar(text, "ADMIN_PASSWORD_HASH", f"'{hashed}'")
if "change-me" in text:
    text = setvar(text, "JWT_SECRET", secrets.token_urlsafe(48))
env.write_text(text)
print(f"Saved to {env}")
