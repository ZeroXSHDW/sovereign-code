# Task packs

A pack is everything an agent needs to work a whole project category: skills,
Hugging Face queries, guardrails, steps and deliverables.

```sh
sovereign pack list
sovereign pack show pentest
sovereign pack brief pentest --path AGENTS.md   # writes the brief + SCOPE.md
sovereign pack models forensics
sovereign pack verify forensics --model qwen3.5:9b
sovereign pack install pentest --target opencode
```

Packs: pentest, redteam, blueteam, soc, threatintel, threatmodel, purpleteam,
malware, cloudsec, appsec, vulnerability, risk, vendor, legal, compliance,
forensics, finance.

Pentest and other offensive-security packs stop unless `SCOPE.md` lists the
targets — a guardrail, not an option.