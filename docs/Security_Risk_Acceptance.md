# Security Risk Acceptance: LocalStorage JWT

## Overview
The MetaMind application currently stores the Supabase authentication JWT in the browser's `localStorage`. This document outlines the security risk associated with this pattern, the business justification for accepting it during the initial MVP phase, and the required mitigations.

## Identified Risk
**Cross-Site Scripting (XSS) Token Theft**
`localStorage` is accessible via JavaScript on the same origin. If an attacker successfully injects malicious JavaScript into the application (XSS), they can read the JWT from `localStorage` and exfiltrate it to a remote server. The attacker can then use the token to impersonate the user until the token expires.

This is a known architectural vulnerability compared to using `httpOnly` cookies, which are immune to JavaScript extraction.

## Justification for Acceptance
1. **Frontend Architecture Simplicity:** The Supabase client libraries (`@supabase/supabase-js`) default to `localStorage` for session management in single-page applications (SPAs). Migrating to a Backend-BFF (Backend for Frontend) or SSR-based `httpOnly` cookie flow requires a significant rewrite of the auth layer and API boundary.
2. **Current Threat Model:** For the MVP, the application does not handle high-value financial data, PII (beyond email), or irreversible high-stakes actions. 
3. **Data Sandboxing:** Row Level Security (RLS) ensures that even if a token is stolen, the attacker can only access data belonging to that specific user. They cannot elevate privileges or access system-wide data.

## Mitigations Implemented (Defense-in-Depth)
Because we are accepting the `localStorage` risk, we must aggressively minimize the likelihood of XSS:
- **Strict Content Security Policy (CSP):** The frontend will be served with a strict CSP that disallows `unsafe-inline` scripts and `eval`. This prevents the execution of injected script tags.
- **React Escaping:** The frontend is built using React, which automatically escapes user-provided content during rendering, drastically reducing the attack surface for reflected and stored XSS.
- **Short Token Expiry:** The Supabase JWT has a relatively short lifespan (typically 1 hour), limiting the window of opportunity for token reuse.

## Future Remediation (Phase 8+)
When the application scales or if the threat model changes to include highly sensitive data, this risk acceptance will be revoked. The remediation path is:
1. Implement a backend auth proxy that intercepts the Supabase JWT and issues a secure, `SameSite=Strict`, `httpOnly` cookie to the browser.
2. The frontend will rely exclusively on the cookie for authentication with the backend.
