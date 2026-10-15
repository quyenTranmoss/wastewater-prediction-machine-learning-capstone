"""
Account storage for the login page — the database side of authentication.

Passwords are hashed with Argon2 (argon2-cffi) and only ever stored as a hash.
The plain password is never written to the database, a file, or a log.

Create a local test account:
    python database/users.py add <username>          # prompts for the password
    python database/users.py list                    # usernames only

The backend imports the two functions it needs:
    from database.users import verify_user, create_user
"""
import getpass
import os
import sqlite3
import sys

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "wastewater.db")

# argon2-cffi's defaults follow the RFC 9106 recommendations. Leave them alone
# unless there is a measured reason to change them; if they ever do change,
# verify_user() rehashes existing accounts automatically on next login.
ph = PasswordHasher()


def _connect():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def create_user(username: str, password: str) -> None:
    """Add an account. Raises sqlite3.IntegrityError if the username is taken."""
    with _connect() as conn:
        conn.execute("INSERT INTO users (username, password_hash) VALUES (?, ?)",
                     (username, ph.hash(password)))


def verify_user(username: str, password: str) -> bool:
    """True if the credentials are valid. Use this from the login endpoint.

    Returns False for both a wrong password and an unknown username so the
    response cannot be used to discover which usernames exist.
    """
    with _connect() as conn:
        row = conn.execute("SELECT id, password_hash FROM users WHERE username = ?",
                           (username,)).fetchone()
        if row is None:
            # Hash anyway so a missing user takes the same time as a wrong
            # password - otherwise response timing leaks which usernames exist.
            ph.hash(password)
            return False
        try:
            ph.verify(row["password_hash"], password)
        except (VerifyMismatchError, InvalidHashError):
            return False
        # Upgrade the stored hash if the Argon2 parameters have changed since
        # this account was created. We have the plain password only right here.
        if ph.check_needs_rehash(row["password_hash"]):
            conn.execute("UPDATE users SET password_hash = ? WHERE id = ?",
                         (ph.hash(password), row["id"]))
        return True

#change password function, 
# takes in a username and new password, 
# hashes the new password and updates the database with the new hash. Raises ValueError if the user does not exist.
def change_password(userame: str, new_password: str) -> None:
    """Change the password for an existing account."""
    with _connect() as conn:
        result = conn.execute(
            "UPDATE users SET password_hash = ? WHERE username = ?",
            (ph.hash(new_password), username)
        )

        if result.rowcount == 0:
            raise ValueError(f"User {username!r} does not exist.")

def list_users() -> list[str]:
    with _connect() as conn:
        return [r["username"] for r in
                conn.execute("SELECT username FROM users ORDER BY username")]


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    if cmd == "add" and len(sys.argv) == 3:
        username = sys.argv[2]
        password = getpass.getpass(f"Password for {username}: ")
        if password != getpass.getpass("Confirm: "):
            sys.exit("Passwords did not match - nothing was created.")
        try:
            create_user(username, password)
        except sqlite3.IntegrityError:
            sys.exit(f"User {username!r} already exists.")
        print(f"Created {username!r}.")
    elif cmd == "list":
        users = list_users()
        print("\n".join(users) if users else "No accounts yet.")
    elif cmd == "change" and len(sys.argv) == 3:
        username = sys.argv[2]
        new_password = getpass.getpass(f"New password for {username}: ")
        if new_password != getpass.getpass("Confirm: "):
            sys.exit("Passwords did not match - nothing was changed.")
        try:
            change_password(username, new_password)
        except ValueError as e:
            sys.exit(str(e))
        print(f"Password changed for {username!r}.")
    else:
        sys.exit(__doc__)