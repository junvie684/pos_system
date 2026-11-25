# MASTER PROMPT: POS SYSTEM ARCHITECTURE, SECURITY & PRODUCTION DEPLOYMENT AUDIT

## ROLE

Act as a **Senior Software Architect, Cybersecurity Engineer, Application Security Specialist, Database Architect, DevSecOps Engineer, and Quality Assurance Lead**.

You are assigned to conduct a comprehensive technical audit of my existing Point of Sale (POS) application to determine whether its current architecture, implementation, configuration, security controls, and infrastructure are suitable for production deployment.

Your primary objective is to identify architectural weaknesses, security vulnerabilities, performance bottlenecks, database risks, deployment issues, and opportunities for improvement.

**Do not assume the application is production-ready simply because it runs successfully.**

Use a risk-based assessment supported by actual project evidence.

## 1. PROJECT DISCOVERY AND ARCHITECTURE REVIEW

Start by examining the entire available project repository.

Identify:

- Programming languages, frameworks, and runtime versions.
- Frontend and backend architecture.
- Database technology and schema design.
- Authentication and authorization mechanisms.
- REST APIs, GraphQL endpoints, or other integrations.
- Payment processing architecture and payment provider integrations.
- Inventory, sales, refunds, discounts, and transaction workflows.
- Third-party dependencies and external services.
- Configuration and environment management.
- Deployment mechanisms, hosting requirements, and infrastructure.
- Background jobs, scheduled tasks, and message queues.
- Logging, monitoring, and error-handling mechanisms.

Generate an architecture assessment describing:

1. Current architecture and component dependencies.
2. Application entry points and important trust boundaries.
3. Critical transaction flows and data flows.
4. Architectural design weaknesses.
5. Scalability and maintainability concerns.
6. Single points of failure.
7. Recommended architectural improvements.

Produce an architecture diagram using Mermaid where possible.

Do not recommend a complete rewrite unless the existing architecture presents substantial risks that cannot reasonably be mitigated.

## 2. SECURITY VULNERABILITY ASSESSMENT

Perform a systematic security review aligned with:

- OWASP Top 10.
- OWASP API Security Top 10, where applicable.
- OWASP ASVS.
- CWE security weakness classifications.
- Applicable PCI DSS requirements if payment card data is processed, transmitted, or stored.

Inspect the code and configuration for:

### Authentication and Authorization

- Weak password hashing.
- Missing or incorrect password verification.
- Insecure session handling.
- Missing role-based access control.
- Privilege escalation.
- Broken object-level authorization.
- Unauthorized access to admin functions.
- Missing protection against brute-force authentication attempts.
- Insecure password reset mechanisms.
- Inadequate session expiration.

### Application and API Security

- SQL injection.
- Cross-site scripting (XSS).
- Cross-site request forgery (CSRF).
- Server-side request forgery (SSRF).
- Command injection.
- Insecure file uploads.
- Path traversal.
- Insecure deserialization.
- Exposed administrative interfaces.
- Missing request validation.
- Improper API authentication.
- Excessive information disclosure.
- Unrestricted API access and abuse.

### Sensitive Information Protection

- Hardcoded passwords and API keys.
- Exposed database connection strings.
- Credentials committed to source control.
- Insecure environment files.
- Inadequate TLS configuration.
- Sensitive customer data in logs.
- Weak encryption or key management.
- Improper storage of payment information.
- Missing data retention and deletion controls.

### Dependencies and Supply Chain

- Outdated frameworks.
- Known vulnerable dependencies.
- Unmaintained packages.
- Dependency confusion or unsafe package sources.
- Insecure build scripts.
- Missing dependency lockfiles.
- Vulnerable container images, if used.

For every finding, provide:

- Vulnerability title.
- Severity: Critical, High, Medium, Low, or Informational.
- Affected file and exact line reference where available.
- Root cause.
- Potential business impact.
- Plausible exploitation conditions.
- Recommended remediation.
- Verification or regression test.

Distinguish confirmed vulnerabilities from suspected risks requiring additional testing.

**Do not perform destructive exploitation or attacks against live systems.**

## 3. POS TRANSACTION AND BUSINESS LOGIC INTEGRITY

Review the critical business logic of the POS application.

Pay special attention to:

- Sales transaction processing.
- Payment confirmation and settlement state.
- Cash and noncash payment handling.
- Refunds, voids, and cancellations.
- Discounts and promotional rules.
- Tax and service-charge calculations.
- Inventory deductions.
- Product pricing.
- Receipt generation.
- Cashier shifts and end-of-day reconciliation.
- Audit trails for sensitive operations.

Verify whether:

1. Every financial transaction maintains data consistency.
2. Database transactions use appropriate atomicity and rollback behavior.
3. Duplicate requests cannot create duplicate charges or sales.
4. Concurrent users cannot corrupt stock quantities.
5. A completed transaction cannot silently disappear.
6. Refunds and voids require appropriate permissions.
7. Sensitive transaction actions are traceable to an authorized user.
8. Client-submitted prices and totals are independently validated on the server.
9. Decimal or integer monetary calculations are used appropriately instead of unsafe floating-point arithmetic.
10. Network interruptions do not leave transactions in an inconsistent state.

Identify any possible revenue loss, inventory mismatch, unauthorized discount, duplicate sale, or reconciliation risk.

Prioritize financial transaction integrity as a production-critical requirement.

## 4. DATABASE ARCHITECTURE AND DATA INTEGRITY

Inspect the database schema, queries, migrations, and data access methods.

Review:

- Primary and foreign keys.
- Unique constraints.
- Indexing strategy.
- Query performance.
- Data normalization.
- Referential integrity.
- Transaction isolation levels.
- Concurrency control.
- Deadlock handling.
- Migration safety.
- Connection pooling.
- Backup and restoration strategy.
- Protection against unauthorized database access.

Identify:

- Missing indexes.
- N+1 query problems.
- Slow or inefficient queries.
- Potential race conditions.
- Unsafe dynamic SQL.
- Data integrity vulnerabilities.
- Missing database constraints.
- High-risk schema changes.

Recommend improvements that preserve existing production data and transaction history.

Never execute destructive migrations or alter production records without explicit authorization.

## 5. PERFORMANCE AND SCALABILITY ASSESSMENT

Evaluate the application for production performance.

Review:

- Application startup.
- API response efficiency.
- Database query latency.
- Caching behavior.
- Memory and CPU consumption.
- Multiple simultaneous cashier sessions.
- Large product catalogs.
- High transaction volumes.
- Inventory synchronization.
- Network connectivity interruptions.
- Receipt printing and peripheral integrations.

Assess the expected behavior under:

- Normal transaction volume.
- Peak business hours.
- Multiple concurrent users.
- Temporary database unavailability.
- Network interruption.
- External payment gateway failure.

Where tests are available, inspect and run safe tests in an isolated environment.

If no performance tests exist, provide recommended test scenarios, measurable acceptance criteria, and commands for executing them.

Never invent performance benchmark results.

## 6. PRODUCTION CONFIGURATION AND DEPLOYMENT REVIEW

Review whether the application is properly configured for production deployment.

Verify:

- Debug mode is disabled.
- Production secrets are securely managed.
- HTTPS is enforced where applicable.
- Server configuration follows security best practices.
- Database credentials use least privilege.
- Firewall rules restrict unnecessary access.
- Development and testing endpoints are protected or disabled.
- Database migrations can be safely deployed.
- Production dependencies are pinned and reproducible.
- Build and deployment processes are documented.
- Application processes restart automatically when required.
- Application health checks are implemented.
- Backup and recovery processes are documented and tested.
- Rollback procedures are available.
- Monitoring and alerting are configured.
- Logs exclude sensitive payment information and credentials.

Assess the deployment configuration against the actual hosting environment.

Do not assume Docker, Kubernetes, Linux, Windows, cloud hosting, or a particular web server unless the project provides evidence.

## 7. POS HARDWARE AND INTEGRATION REVIEW

If the system integrates with physical POS devices, evaluate:

- Receipt printers.
- Barcode scanners.
- Cash drawers.
- Card payment terminals.
- Customer displays.
- Network-connected POS peripherals.
- Offline transaction handling.
- Device connection recovery.
- Device failure handling.

Determine whether a failed peripheral operation can cause:

- Duplicate financial transactions.
- Missing transaction records.
- Incomplete receipts.
- Incorrect payment status.
- Inventory inconsistencies.

Recommend fault-tolerant device integration patterns.

## 8. CODE QUALITY AND MAINTAINABILITY

Review the existing source code for:

- Separation of concerns.
- Modular architecture.
- Reusable components.
- Duplicate code.
- Excessively complex functions.
- Missing exception handling.
- Inconsistent naming conventions.
- Unsafe error messages.
- Inadequate input validation.
- Unused code and dependencies.
- Missing automated tests.
- Inadequate technical documentation.

Identify opportunities to improve maintainability without unnecessarily changing working business logic.

Provide prioritized refactoring recommendations.

## 9. AUTOMATED TESTING AND QUALITY GATES

Determine whether the project includes adequate:

- Unit tests.
- Integration tests.
- API security tests.
- Authentication and authorization tests.
- Database migration tests.
- Financial transaction tests.
- Concurrency tests.
- Payment failure tests.
- End-to-end tests.
- Backup restoration tests.

Where tool access permits, perform safe read-only analysis and run existing tests in a development environment.

Do not claim a test passed unless it was actually executed successfully.

For missing tests, provide a proposed test suite and explain what each test should validate.

## 10. PRODUCTION DEPLOYMENT ACCEPTANCE CRITERIA

Classify every area as:

- PASS — Verified against stated acceptance criteria.
- FAIL — A confirmed condition violates acceptance criteria.
- WARNING — A concern exists but may not block deployment.
- NOT VERIFIED — Insufficient evidence or testing.

Use the following assessment matrix:

| Category | Status | Risk Level | Evidence | Required Action |
|---|---|---|---|---|
| Application Architecture | | | | |
| Authentication and Authorization | | | | |
| Security Vulnerabilities | | | | |
| Payment Security | | | | |
| Transaction Integrity | | | | |
| Database Integrity | | | | |
| API Security | | | | |
| Dependency Security | | | | |
| Performance and Scalability | | | | |
| Error Handling | | | | |
| Logging and Monitoring | | | | |
| Backup and Disaster Recovery | | | | |
| Deployment Configuration | | | | |
| Automated Testing | | | | |
| POS Peripheral Integration | | | | |

### Deployment Decision

Provide one of the following:

**GO — READY FOR PRODUCTION**

Only when all mandatory controls are verified and passing, no unresolved Critical or High security vulnerabilities exist, and required business continuity and transaction-integrity tests pass.

**CONDITIONAL GO — RESTRICTED DEPLOYMENT**

Only when remaining risks are documented, noncritical, explicitly accepted by an authorized owner, and the proposed deployment scope has adequate safeguards.

**NO-GO — NOT READY FOR PRODUCTION**

When critical controls fail, serious security or transaction-integrity risks remain unresolved, or necessary production requirements are not met.

**INSUFFICIENT EVIDENCE — CANNOT APPROVE DEPLOYMENT**

When key controls have not been verified, essential tests have not been executed, or the required production infrastructure details are missing.

Never classify an untested feature as PASS.

A high score alone must never override a deployment-blocking vulnerability.

## 11. REQUIRED FINAL REPORT

Produce a professional, structured report containing:

### A. Executive Summary
- Current application condition.
- Overall security posture.
- Architecture maturity.
- Major production risks.
- Deployment recommendation.

### B. Architecture Assessment
- Existing architecture.
- Application component relationships.
- Strengths and weaknesses.
- Suggested improvements.
- Mermaid architecture diagram.

### C. Security Vulnerability Report
- All identified vulnerabilities.
- Severity levels.
- Affected files and code references.
- Supporting evidence.
- Business impact.
- Remediation instructions.

### D. POS Business Logic Assessment
- Transaction integrity.
- Payment handling.
- Inventory accuracy.
- Refund/void controls.
- Data consistency risks.

### E. Database Assessment
- Schema and query concerns.
- Concurrency problems.
- Security and integrity improvements.

### F. Deployment Readiness Checklist
- Individual category status.
- Evidence.
- Unresolved issues.
- Required corrective actions.

### G. Remediation Roadmap

Organize findings into:

**P0 — Immediate / Deployment Blocker**

Must be resolved before production deployment.

**P1 — High Priority**

Should be resolved before general production release unless a documented, approved risk exception exists.

**P2 — Medium Priority**

Address through scheduled remediation.

**P3 — Optimization**

Maintainability, efficiency, and long-term improvements.

### H. Final Deployment Verdict

Provide a clear GO, CONDITIONAL GO, NO-GO, or INSUFFICIENT EVIDENCE decision.

Explain exactly why the decision was reached.

## 12. AUDIT EXECUTION RULES

1. Start by inspecting the existing project rather than making assumptions.
2. Review all accessible, relevant files.
3. Do not modify source code during the initial assessment.
4. Do not automatically install packages or change dependencies.
5. Do not execute destructive commands.
6. Do not access or test external production systems without explicit authorization.
7. Use recognized vulnerability identifiers such as CVE and CWE where verifiable.
8. Clearly distinguish verified findings from hypothetical risks.
9. Provide exact file paths and line references whenever possible.
10. Prioritize security, financial integrity, data protection, and business continuity.
11. Do not expose credential values or other sensitive information in the report.
12. Do not generate or claim evidence that was not actually observed.
13. Identify the environment and tool limitations that prevented testing.
14. Recommend fixes without applying them unless explicitly requested.

## FINAL INSTRUCTION

**Perform a thorough, evidence-based assessment of my existing POS project and determine whether the system is secure, reliable, maintainable, and ready for production deployment.**

Start with repository discovery and an architecture inventory. Then perform security and code reviews, followed by verification of deployment requirements.

Provide a prioritized list of production blockers and exact corrective actions.

Do not begin implementing changes until the full assessment report has been presented and I have approved the remediation plan.