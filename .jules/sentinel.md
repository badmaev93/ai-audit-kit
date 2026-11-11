## 2023-11-11 - SSRF via urllib.request.urlopen

**Vulnerability:** `urllib.request.urlopen` accepts multiple URL schemes by default, including `file://`. When passing user input directly to this function without validation, an attacker could read arbitrary local files (e.g., `file:///etc/passwd`).

**Learning:** This is a classic SSRF (Server-Side Request Forgery) / LFI (Local File Inclusion) vulnerability. It's common in Python applications that accept URLs as input and fetch them.

**Prevention:** Always validate URLs before fetching them, ensuring they start with an expected scheme like `http://` or `https://` (and not `file://`, `ftp://`, etc. unless explicitly intended).

## 2024-11-11 - CSV Injection (Formula Injection)

**Vulnerability:** Untrusted text output from LLMs (or the users) was being written directly into a CSV file via `csv.DictWriter` without any sanitization. If the output starts with `=`, `+`, `-`, or `@`, spreadsheet applications like Microsoft Excel or LibreOffice Calc will interpret it as a formula, which can lead to remote code execution on the machine of the person reviewing the CSV file.

**Learning:** Data exported to CSV must be treated as untrusted, especially when it originates from user input or external models like LLMs. CSV injection is a common and dangerous vulnerability in reporting and export features.

**Prevention:** Always sanitize strings before writing them to a CSV by checking if they start with characters that trigger formulas (`=`, `+`, `-`, `@`, `\t`, `\r`) and neutralizing them, typically by prepending a single quote (`'`).
