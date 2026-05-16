---
name: startup_profile
description: Generates a neutral, objective 5-point diagnostic of a startup. It bypasses marketing narratives to expose the structural reality of the business, prioritizing external risks and identifying specific tasks for an investment analyst. Use this skill when the user asks "Profile this startup", "Run startup diagnostic", or "What does this startup do?". Note that if no context/document is provided via the GUI, the <STARTUP_NAME> must be clearly specified in the query.
---

# Startup Profile

This skill generates a neutral, objective 5-point diagnostic of a startup using the 5-Point Framework.

## Framework

1. **Oneliner:** Cold, objective description of what they actually do.
2. **Core industry:** The specific industry/market.
3. **Technology:** Technical reality, highlighting dependencies and technical single points of failure.
4. **Business model:** How they claim to make money, highlighting structural risks.
5. **Current challenges:** Critical data gaps, barriers to entry, and domains requiring expert due diligence.

## Usage

```bash
python -m skills.startup_profile --startup "<STARTUP_NAME>" [--files <file1> <file2> ...]
```
