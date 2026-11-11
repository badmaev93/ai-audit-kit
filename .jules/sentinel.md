## 2023-11-11 - SSRF via urllib.request.urlopen

**Vulnerability:** `urllib.request.urlopen` accepts multiple URL schemes by default, including `file://`. When passing user input directly to this function without validation, an attacker could read arbitrary local files (e.g., `file:///etc/passwd`).

**Learning:** This is a classic SSRF (Server-Side Request Forgery) / LFI (Local File Inclusion) vulnerability. It's common in Python applications that accept URLs as input and fetch them.

**Prevention:** Always validate URLs before fetching them, ensuring they start with an expected scheme like `http://` or `https://` (and not `file://`, `ftp://`, etc. unless explicitly intended).

## 2024-11-11 - CSV Injection (Formula Injection)

**Vulnerability:** Untrusted text output from LLMs (or the users) was being written directly into a CSV file via `csv.DictWriter` without any sanitization. If the output starts with `=`, `+`, `-`, or `@`, spreadsheet applications like Microsoft Excel or LibreOffice Calc will interpret it as a formula, which can lead to remote code execution on the machine of the person reviewing the CSV file.

**Learning:** Data exported to CSV must be treated as untrusted, especially when it originates from user input or external models like LLMs. CSV injection is a common and dangerous vulnerability in reporting and export features.

**Prevention:** Always sanitize strings before writing them to a CSV by checking if they start with characters that trigger formulas (`=`, `+`, `-`, `@`, `\t`, `\r`) and neutralizing them, typically by prepending a single quote (`'`).

## 2026-11-11 - CSV Injection Whitespace Bypass

**Vulnerability:** The existing CSV sanitization logic checked if untrusted strings started with characters that trigger spreadsheet formulas (`=`, `+`, `-`, `@`, `\t`, `\r`). However, this check was susceptible to bypass: an attacker could prepend one or more whitespace characters (like `" =1+1"` or `" @SUM(A1)"`) to the payload. Spreadsheet applications (like Excel and Calc) ignore leading whitespace in cells and will still evaluate the hidden formula, leading to formula injection.

**Learning:** Sanitization functions must account for the parsers they are protecting against. Spreadsheet parsers strip leading whitespace before checking for formula syntax, so our sanitization logic must do the same.

**Prevention:** Before checking if a string begins with a dangerous character in the context of CSV export, always strip leading whitespace using `.lstrip()` or an equivalent method.

## 2026-11-11 - Credential Leak via HTTP Redirect

**Vulnerability:** When `urllib.request.urlopen` followed HTTP redirects (like 302 Found) to a different host, it included the original `Authorization` header by default. An attacker could exploit this by providing a target URL or malicious redirect that forwarded the request to their own server, successfully stealing the secret API key or bearer token.

**Learning:** The Python standard library `urllib` handles HTTP redirects automatically but does not strip sensitive headers on cross-origin redirects. Other modern libraries like `requests` drop authorization headers when the hostname changes, but `urllib` requires manual intervention to ensure security.

**Prevention:** Use a custom `HTTPRedirectHandler` that explicitly removes the `Authorization` header from the new request upon redirect, and install it globally using `urllib.request.install_opener`.

## 2026-11-11 - SSRF via Redirection to file://

**Vulnerability:** The existing protection against Server-Side Request Forgery (SSRF) for `file://` URIs only validated the *initial* URL passed to `urllib.request.urlopen`. However, `urllib` natively follows HTTP redirects (e.g., 302 Found) to any supported scheme by default. An attacker could bypass the initial URL check by providing an HTTP URL that immediately redirects to `file:///etc/passwd`, causing the application to read and return local system files.

**Learning:** URL scheme validation must happen at every stage of the request lifecycle, especially during redirects. Trusting the initial URL does not protect against malicious redirects when the underlying HTTP client automatically follows them across different protocol schemes.

**Prevention:** Override the `redirect_request` method in a custom `urllib.request.HTTPRedirectHandler` and ensure that the `newurl` scheme is strictly limited to `http://` or `https://` before allowing the redirect to proceed.
