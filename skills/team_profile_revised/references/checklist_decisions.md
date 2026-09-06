# Revised team checklist decisions

The user clarified that `team_profile_revised` uses `batch_audit`, begins with cached startup and related-person profiles, applies the same workflow to screening and DD, retrieves only from the data room, focuses on founders and produces evidence-referenced category summaries without scores.

The [original register](original_team_questions.md), [additional questions and amendments](additional_team_questions.md), and [working hierarchy](team_question_hierarchy.md) are preserved as supplied design records. Their scoring instructions and application/DD variants are superseded by those clarifications. They are not loaded into runtime prompts.

## Consolidation

The 72 tracked IDs comprise 67 proposed checklist items and five framework questions. There are now **40 executable checks across four main-category checklists**; 66 original IDs remain represented in check names and descriptions. Overlapping topics share one assessment. Q029 becomes a general evidence rule; the five framework questions remain outside the executable checklist. The mapping below accounts for every ID exactly once.

- N001's narrative trait assessment is generated in the optional person-profile founder section and reused in the team audit. N002 role readiness stays venture-specific. Neither produces numeric scores.
- Q011 now derives the principal execution risk from the next consequential venture-specific bottleneck and explains uncertainty rather than imposing a universal risk.
- Q003/Q004 use only explicitly disclosed relationships. Q016/Q027 share one collaboration-history check.
- Q117 tests concrete authority/accountability problems. Q143 tests material concentration beyond ordinary founder dependence. Q144 assesses control without requiring succession planning.
- Q129 covers any material advisor expertise. Q132 tests whether advisor prominence is supported by operating evidence, without counting advisors against customers.
- Q125/Q127/Q133 assess supplied reference evidence and propose human follow-ups. They do not claim the agent can contact references or verify reachability.
- Governance and evidence-verification topics remain available for DD. Missing records are unknown, not presumed adverse. Larger-team evidence is considered only where material to founder execution, governance or support.
- N005 explicitly distinguishes an established uncovered function from insufficient evidence of coverage.

## ID mapping

| Original ID | Revised location or disposition |
|---|---|
| N001 | [N001 / Q026 / Q028 — Individual founder traits](../../../config/team_profile_revised/checklists/1_individual_founder_quality.md) |
| N002 | [N002 / R002 — Founder responsibilities and role readiness](../../../config/team_profile_revised/checklists/1_individual_founder_quality.md) |
| N003 | [N003 — Personal commitment and exposure](../../../config/team_profile_revised/checklists/1_individual_founder_quality.md) |
| N004 | [N004 — Duration of commitment and progress](../../../config/team_profile_revised/checklists/1_individual_founder_quality.md) |
| N005 | [N005 — Essential functional coverage](../../../config/team_profile_revised/checklists/2_founding_team_strength.md) |
| N006 | [N006 — Founder allocation to support functions](../../../config/team_profile_revised/checklists/2_founding_team_strength.md) |
| Q001 | [Q001 / Q002 / R001 — Actual founding team and organisation](../../../config/team_profile_revised/checklists/2_founding_team_strength.md) |
| Q002 | [Q001 / Q002 / R001 — Actual founding team and organisation](../../../config/team_profile_revised/checklists/2_founding_team_strength.md) |
| Q003 | [Q003 / Q004 — Disclosed personal relationships and safeguards](../../../config/team_profile_revised/checklists/2_founding_team_strength.md) |
| Q004 | [Q003 / Q004 — Disclosed personal relationships and safeguards](../../../config/team_profile_revised/checklists/2_founding_team_strength.md) |
| Q005 | [Q005 — Domain and technical capability](../../../config/team_profile_revised/checklists/1_individual_founder_quality.md) |
| Q006 | [Q006 — Business and commercial understanding](../../../config/team_profile_revised/checklists/1_individual_founder_quality.md) |
| Q007 | [Q007 — Demonstrated selling experience](../../../config/team_profile_revised/checklists/1_individual_founder_quality.md) |
| Q008 | [Q008 / Q009 / R010 — Recognition of gaps and concrete hiring plans](../../../config/team_profile_revised/checklists/2_founding_team_strength.md) |
| Q009 | [Q008 / Q009 / R010 — Recognition of gaps and concrete hiring plans](../../../config/team_profile_revised/checklists/2_founding_team_strength.md) |
| Q010 | Framework definition: credible gap-closing plans are defined in Q008 / Q009 / R010 through ownership, responsibilities, timing, resourcing and candidate access. |
| Q011 | [Q011 — Ownership of the principal execution risk](../../../config/team_profile_revised/checklists/1_individual_founder_quality.md) |
| Q014 | [Q014 — Founder compensation and financing dependence](../../../config/team_profile_revised/checklists/1_individual_founder_quality.md) |
| Q015 | [Q015 / Q017 / Q018 — Spinoff and parent-company dependencies](../../../config/team_profile_revised/checklists/3_governance_and_extended_support.md) |
| Q016 | [Q016 / Q027 — Prior shared history and collaboration](../../../config/team_profile_revised/checklists/2_founding_team_strength.md) |
| Q017 | [Q015 / Q017 / Q018 — Spinoff and parent-company dependencies](../../../config/team_profile_revised/checklists/3_governance_and_extended_support.md) |
| Q018 | [Q015 / Q017 / Q018 — Spinoff and parent-company dependencies](../../../config/team_profile_revised/checklists/3_governance_and_extended_support.md) |
| Q019 | [Q019 / Q020 — Consistency of roles and dates](../../../config/team_profile_revised/checklists/4_evidence_credibility_and_verifiability.md) |
| Q020 | [Q019 / Q020 — Consistency of roles and dates](../../../config/team_profile_revised/checklists/4_evidence_credibility_and_verifiability.md) |
| Q021 | [Q021 — Conflicting commitments](../../../config/team_profile_revised/checklists/1_individual_founder_quality.md) |
| Q022 | [Q022 / Q023 / Q024 / Q129 — Relevant and active extended support](../../../config/team_profile_revised/checklists/3_governance_and_extended_support.md) |
| Q023 | [Q022 / Q023 / Q024 / Q129 — Relevant and active extended support](../../../config/team_profile_revised/checklists/3_governance_and_extended_support.md) |
| Q024 | [Q022 / Q023 / Q024 / Q129 — Relevant and active extended support](../../../config/team_profile_revised/checklists/3_governance_and_extended_support.md) |
| Q025 | [Q025 — Experience in different operating environments](../../../config/team_profile_revised/checklists/1_individual_founder_quality.md) |
| Q026 | [N001 / Q026 / Q028 — Individual founder traits](../../../config/team_profile_revised/checklists/1_individual_founder_quality.md) |
| Q027 | [Q016 / Q027 — Prior shared history and collaboration](../../../config/team_profile_revised/checklists/2_founding_team_strength.md) |
| Q028 | [N001 / Q026 / Q028 — Individual founder traits](../../../config/team_profile_revised/checklists/1_individual_founder_quality.md) |
| Q029 | Evidence assessability is handled in every check through Assessed / Insufficient information / Not applicable and source limitations; it is not a substantive startup question. |
| Q030 | Framework calibration: one workflow without a stage switch; materiality follows the actual venture and current priorities. No industry weighting or scoring yet. |
| Q117 | [Q117 — Alignment of operating responsibility and decision authority](../../../config/team_profile_revised/checklists/2_founding_team_strength.md) |
| Q118 | [Q118 / Q122 — Consistency of statements and recorded management changes](../../../config/team_profile_revised/checklists/4_evidence_credibility_and_verifiability.md) |
| Q119 | [Q119 — Founder departure and leaver arrangements](../../../config/team_profile_revised/checklists/3_governance_and_extended_support.md) |
| Q120 | [Q120 — Founders' agreement and documented commitments](../../../config/team_profile_revised/checklists/3_governance_and_extended_support.md) |
| Q121 | [Q121 — Founder involvement in the assessment interaction](../../../config/team_profile_revised/checklists/1_individual_founder_quality.md) |
| Q122 | [Q118 / Q122 — Consistency of statements and recorded management changes](../../../config/team_profile_revised/checklists/4_evidence_credibility_and_verifiability.md) |
| Q123 | [Q123 / Q125 / Q127 / Q133 — Supplied diligence and reference evidence](../../../config/team_profile_revised/checklists/4_evidence_credibility_and_verifiability.md) |
| Q124 | [Q124 / Q138 — Related-party transactions and interests](../../../config/team_profile_revised/checklists/3_governance_and_extended_support.md) |
| Q125 | [Q123 / Q125 / Q127 / Q133 — Supplied diligence and reference evidence](../../../config/team_profile_revised/checklists/4_evidence_credibility_and_verifiability.md) |
| Q126 | Framework threshold remains undecided. No minimum reference count is imposed; Q123 / Q125 / Q127 / Q133 reports supplied corroboration and its limits. |
| Q127 | [Q123 / Q125 / Q127 / Q133 — Supplied diligence and reference evidence](../../../config/team_profile_revised/checklists/4_evidence_credibility_and_verifiability.md) |
| Q128 | Outside this agent workflow: no informal network checks or outreach. Relevant evidence already supplied can be assessed. |
| Q129 | [Q022 / Q023 / Q024 / Q129 — Relevant and active extended support](../../../config/team_profile_revised/checklists/3_governance_and_extended_support.md) |
| Q130 | [Q130 — Documented board activity](../../../config/team_profile_revised/checklists/3_governance_and_extended_support.md) |
| Q131 | [Q131 — Limits of advisor support for a team gap](../../../config/team_profile_revised/checklists/2_founding_team_strength.md) |
| Q132 | [Q132 — Advisor prominence versus operating evidence](../../../config/team_profile_revised/checklists/3_governance_and_extended_support.md) |
| Q133 | [Q123 / Q125 / Q127 / Q133 — Supplied diligence and reference evidence](../../../config/team_profile_revised/checklists/4_evidence_credibility_and_verifiability.md) |
| Q134 | [Q134 / R005 — Identity and operating-location evidence](../../../config/team_profile_revised/checklists/4_evidence_credibility_and_verifiability.md) |
| Q135 | [R003 / Q135 — Demonstrated record and supporting credentials](../../../config/team_profile_revised/checklists/1_individual_founder_quality.md) |
| Q136 | [Q136 / Q139 / R006 / R007 — Supplied debt-enforcement and criminal-record evidence](../../../config/team_profile_revised/checklists/4_evidence_credibility_and_verifiability.md) |
| Q137 | [Q137 — Adverse-information evidence already supplied](../../../config/team_profile_revised/checklists/4_evidence_credibility_and_verifiability.md) |
| Q138 | [Q124 / Q138 — Related-party transactions and interests](../../../config/team_profile_revised/checklists/3_governance_and_extended_support.md) |
| Q139 | [Q136 / Q139 / R006 / R007 — Supplied debt-enforcement and criminal-record evidence](../../../config/team_profile_revised/checklists/4_evidence_credibility_and_verifiability.md) |
| Q140 | [Q140 / Q141 — Response to feedback and self-assessment](../../../config/team_profile_revised/checklists/1_individual_founder_quality.md) |
| Q141 | [Q140 / Q141 — Response to feedback and self-assessment](../../../config/team_profile_revised/checklists/1_individual_founder_quality.md) |
| Q142 | Framework policy deferred: no assumption that SICTIC will close a gap. Report the team’s documented plan and proposed human follow-ups. |
| Q143 | [Q143 — Material concentration of execution dependencies](../../../config/team_profile_revised/checklists/2_founding_team_strength.md) |
| Q144 | [Q144 — Unilateral control and safeguards](../../../config/team_profile_revised/checklists/3_governance_and_extended_support.md) |
| R001 | [Q001 / Q002 / R001 — Actual founding team and organisation](../../../config/team_profile_revised/checklists/2_founding_team_strength.md) |
| R002 | [N002 / R002 — Founder responsibilities and role readiness](../../../config/team_profile_revised/checklists/1_individual_founder_quality.md) |
| R003 | [R003 / Q135 — Demonstrated record and supporting credentials](../../../config/team_profile_revised/checklists/1_individual_founder_quality.md) |
| R004 | [R004 — Employment and conflicting obligations](../../../config/team_profile_revised/checklists/3_governance_and_extended_support.md) |
| R005 | [Q134 / R005 — Identity and operating-location evidence](../../../config/team_profile_revised/checklists/4_evidence_credibility_and_verifiability.md) |
| R006 | [Q136 / Q139 / R006 / R007 — Supplied debt-enforcement and criminal-record evidence](../../../config/team_profile_revised/checklists/4_evidence_credibility_and_verifiability.md) |
| R007 | [Q136 / Q139 / R006 / R007 — Supplied debt-enforcement and criminal-record evidence](../../../config/team_profile_revised/checklists/4_evidence_credibility_and_verifiability.md) |
| R008 | [R008 — ESOP and PSOP arrangements](../../../config/team_profile_revised/checklists/3_governance_and_extended_support.md) |
| R009 | [R009 — Goal setting and performance management](../../../config/team_profile_revised/checklists/2_founding_team_strength.md) |
| R010 | [Q008 / Q009 / R010 — Recognition of gaps and concrete hiring plans](../../../config/team_profile_revised/checklists/2_founding_team_strength.md) |
