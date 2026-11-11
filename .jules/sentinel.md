## 2023-11-11 - SSRF via urllib.request.urlopen

**Vulnerability:** `urllib.request.urlopen` accepts multiple URL schemes by default, including `file://`. When passing user input directly to this function without validation, an attacker could read arbitrary local files (e.g., `file:///etc/passwd`).

**Learning:** This is a classic SSRF (Server-Side Request Forgery) / LFI (Local File Inclusion) vulnerability. It's common in Python applications that accept URLs as input and fetch them.

**Prevention:** Always validate URLs before fetching them, ensuring they start with an expected scheme like `http://` or `https://` (and not `file://`, `ftp://`, etc. unless explicitly intended).
