# 7 Product-Software

## Intellectual Property & Chain of Title

### IP Portfolio & Registration

Does the company maintain comprehensive records of all registered trademarks patents and domain names including their filing status and renewal schedules?

Verify that the legal entity is the registered owner for all assets and flag any domains or trademarks expiring within the next 12 months.

**Keywords:** Patent Trademark Domain Name IP Portfolio Registration Certificate Renewal Filing Status Jurisdictions

### Freedom to Operate (FTO)

Is there evidence of FTO searches or legal opinions confirming that core technologies and branding do not infringe on third-party rights?

Look for any "qualified" legal opinions that mention specific third-party patents which might require licensing or a design-around.

**Keywords:** FTO Search Legal Opinion Infringement Analysis Clearance Search Intellectual Property Clearance Prior Art Analysis

### Proprietary Assignment

Are fully executed IP assignment agreements available for all current and former employees founders and contractors to ensure clean ownership?

Specifically check the "Founding Period" and "External Contractors" to ensure work done before incorporation was formally transferred to the entity.

**Keywords:** IP Assignment Invention Assignment Proprietary Information Agreement Employment Contract Contractor Agreement Chain of Title

### Confidentiality Framework

Is there a repository of signed NDAs with partners vendors and prospective hires to protect trade secrets and proprietary know-how?

Check if the NDAs include "Non-Solicitation" clauses and verify that they are mutual to ensure the company’s data is equally protected.

**Keywords:** NDA Non-Disclosure Agreement Confidentiality Agreement MNDA Proprietary Information Trade Secret Protection

## Data Protection & Regulatory Compliance

### Data Governance Framework

Do the internal Data Management Policy and external Privacy Policy align with the actual data handling and retention practices?

Compare the "Data Retention Period" mentioned in the policy against actual system deletion logs to ensure the policy is being enforced.

**Keywords:** Privacy Policy Data Management Data Governance Data Handling Data Retention Policy Privacy Notice Data Mapping

### GDPR/CCPA Compliance Evidence

Is there documented proof of compliance such as Records of Processing Activities (RoPA) and Data Processing Agreements (DPAs) with sub-processors?

Verify that a signed DPA exists for every major sub-processor like AWS Stripe or Google Analytics mentioned in the infrastructure docs.

**Keywords:** GDPR CCPA RoPA Article 30 DPIA DPA Data Processing Agreement Privacy Impact Assessment Compliance Audit

### Data Residency & Sovereignty

Are data storage locations confirmed and compliant with international frameworks for cross-border data transfers?

Flag any EU-originated personal data stored on US-based servers without active Standard Contractual Clauses (SCCs) or a recognized adequacy framework.

**Keywords:** Data Residency Sovereignty Storage Location Cloud Region Cross-border Transfer Standard Contractual Clauses SCC Data Sovereignty

### Regulatory & Litigation History

Has the company disclosed all past or pending claims investigations or audits by data protection authorities?

Specifically look for correspondence from national regulators like the Swiss FDPIC or mentions of "DSAR" (Data Subject Access Request) escalations.

**Keywords:** Data Protection Audit Regulatory Claim Investigation Litigation Privacy Complaint Information Commissioner Data Breach Fine

## Cybersecurity & Risk Management

### Technical Safeguards

What security protocols are in place for encryption at rest and in transit IAM policies and MFA enforcement?

Confirm that MFA is mandatory for all production environment access and that "Encryption at Rest" is enabled for all primary databases.

**Keywords:** Encryption TLS SSL AES-256 IAM Access Control MFA 2FA Identity Management Security Protocol Data Encryption

### Vulnerability & Penetration Testing

Are there recent third-party penetration test reports and evidence that identified "Critical" or "High" vulnerabilities have been remediated?

Check the "Remediation Status" in the latest report; if high-risk findings are marked as "Accepted Risk" rather than fixed flag it for technical review.

**Keywords:** Penetration Test Pen Test Pentest Vulnerability Scan Security Audit Remediation Report OWASP CVE Scan Security Assessment

### Incident Response & Breach History

Is there a detailed log of historical security incidents and data breaches including the mitigation steps and root cause analysis?

If the log is empty verify if the "Incident Response Plan" has ever been tested or if there are "Post-Mortems" for past system downtime.

**Keywords:** Incident Response Plan Data Breach Security Incident Log Mitigation Steps Unauthorized Access Root Cause Analysis Post-mortem

### Business Continuity

Are there documented Backup and Disaster Recovery (DR) plans with recent RTO and RPO test results?

Compare the RTO (Recovery Time Objective) against the uptime commitments in the customer SLAs to identify potential liability gaps.

**Keywords:** Disaster Recovery DR Plan Business Continuity BCP Backup Policy RTO RPO Recovery Test Backup Log Failover

## Software Architecture & Engineering SDLC

### System Architecture & Documentation

Do the architecture diagrams clearly illustrate the interactions between microservices databases and external APIs?

Look for "Single Points of Failure" in the diagram such as a single monolithic database without a replica that could cause total system downtime.

**Keywords:** Architecture Diagram Microservices API Documentation System Design Database Schema High Level Design HLD Technical Architecture

### Infrastructure & Cloud Operations

Is the computing infrastructure across all environments clearly defined including regional data center locations and ISP redundancies?

Confirm "Environment Isolation" to ensure developers do not have direct access to "Production" data without an audited break-glass procedure.

**Keywords:** Cloud Infrastructure AWS Azure GCP Data Center Staging Environment Production Environment ISP Redundancy Hosting Infrastructure Schema

### Software Bill of Materials (S-BOM)

Is there an S-BOM identifying all open-source libraries to ensure no high-risk "copyleft" licenses are used?

Search specifically for "GPL" or "AGPL" licenses which could legally force the company to open-source its proprietary application logic.

**Keywords:** S-BOM Software Bill of Materials OSS Open Source License Compliance GPL AGPL Apache MIT Library Audit Scan

### SDLC & Engineering Governance

Is there evidence of formal coding standards and a mandatory source code review process for merges to production?

Verify that the Git history shows "At Least Two Reviewers" or a senior engineer's approval for all merges into the production branch.

**Keywords:** SDLC Coding Standards Pull Request PR Review Git Workflow Code Review Style Guide Commit History Senior Approval

### Deployment & CI/CD Pipeline

Is the deployment process automated with defined CI/CD toolchains and clear rollback procedures?

Evaluate the "Rollback Duration" documentation to see how quickly the system can revert to a stable state if a new deployment fails.

**Keywords:** CI/CD Pipeline Jenkins GitHub Actions GitLab CI Automated Deployment Rollback Procedure Environment Isolation Deployment Log

### Observability & Monitoring

Are uptime tracking error logging and real-time alerting frameworks active for the productive system?

Check if alerts are routed to a "Live On-Call" rotation or if they only go to a general email inbox which poses a response risk.

**Keywords:** Monitoring Observability Uptime Tracking Error Log Alerting Datadog New Relic Sentry Prometheus Logging Framework

### Quality & Security Certifications

Is there proof of formal certifications such as ISO 27001 SOC2 Type II or other industry-specific quality stamps?

Verify the "Period of Validity" and ensure the "Statement of Applicability" covers the specific product and infrastructure being used.

**Keywords:** SOC2 ISO 27001 Certification SOC2 Type II Security Certificate Compliance Badge Quality Stamp Audit Report
