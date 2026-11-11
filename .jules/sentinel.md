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
