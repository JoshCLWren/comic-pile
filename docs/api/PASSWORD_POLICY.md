# Password length policy

New registrations and password resets require at least six characters and at
most 72 UTF-8 bytes, the bcrypt input limit. The limit counts bytes, so a
multibyte password can reach it with fewer than 72 characters. Oversized input
receives HTTP 422 before hashing or consuming a reset token. Passwords are never
silently truncated.

Sign-in preserves support for existing shorter passwords. Input above the bcrypt
byte limit is rejected as an invalid credential rather than causing HTTP 500.
