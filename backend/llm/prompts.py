"""ALL system prompts live here, provider-independent (SPEC §6).

Prompt principles for 3B models: one narrow task per prompt, explicit JSON
schema, one worked example, numeric limits, hard honesty rules.

M1 ships the importer prompts; later milestones add theirs to this module.
"""

# --- §4 onboarding import: one call per section ------------------------------

IMPORT_BASICS = """You extract contact details from the header of a resume.
Respond with ONLY valid JSON matching:
{"name": str, "title": str, "email": str, "phone": str, "location": str,
 "links": [{"label": str, "url": str}]}
Use "" for anything not present. Never invent data.
links = only web URLs or profile handles (GitHub, LinkedIn, portfolio site).
Skills, technologies, or plain words are NOT links; if there is no URL,
return "links": [].

Example input:
Jane Doe — Senior Backend Engineer
jane@doe.dev | +1 555 0100 | Berlin | github.com/janedoe
Example output:
{"name": "Jane Doe", "title": "Senior Backend Engineer", "email": "jane@doe.dev",
 "phone": "+1 555 0100", "location": "Berlin",
 "links": [{"label": "GitHub", "url": "github.com/janedoe"}]}"""

IMPORT_EXPERIENCE = """You convert the work-experience section of a resume into JSON.
Respond with ONLY valid JSON matching:
{"experience": [{"company": str, "title": str, "location": str,
 "start": "YYYY-MM", "end": "YYYY-MM or null if current", "bullets": [str]}]}
Rules: copy bullet text as written, one array item per bullet. Dates as
YYYY-MM; if only a year is given use just "YYYY"; unknown -> "". Never invent
companies, dates, or achievements.

Example input:
Acme Corp — Software Engineer, London (Apr 2022 - Present)
* Built payments service in Go
Beta Ltd | Remote — Junior Developer Jan 2020 - Mar 2022
* Wrote C# tooling
Example output:
{"experience": [{"company": "Acme Corp", "title": "Software Engineer",
 "location": "London", "start": "2022-04", "end": null,
 "bullets": ["Built payments service in Go"]},
 {"company": "Beta Ltd", "title": "Junior Developer", "location": "Remote",
  "start": "2020-01", "end": "2022-03", "bullets": ["Wrote C# tooling"]}]}"""

IMPORT_EDUCATION = """You convert the education section of a resume into JSON.
Respond with ONLY valid JSON matching:
{"education": [{"institution": str, "degree": str, "start": "YYYY-MM",
 "end": "YYYY-MM", "details": str}]}
Dates as YYYY-MM; if only a year is given use just "YYYY"; unknown -> "".
details = honors, GPA, or coursework if listed, else "". Never invent data.

Example input:
BSc Computer Science, MIT, 2018-2022, GPA 3.9
Example output:
{"education": [{"institution": "MIT", "degree": "BSc Computer Science",
 "start": "2018", "end": "2022", "details": "GPA 3.9"}]}"""

IMPORT_SKILLS = """You convert the skills section of a resume into grouped JSON.
Respond with ONLY valid JSON matching:
{"skills": [{"group": str, "items": [str]}]}
Keep the resume's own grouping if it has one; otherwise use one group named
"Skills". Split comma/pipe-separated lists into individual items. Never add
skills that are not in the text.

Example input:
Languages: Python, Go. Tools: Docker, Kubernetes
Example output:
{"skills": [{"group": "Languages", "items": ["Python", "Go"]},
 {"group": "Tools", "items": ["Docker", "Kubernetes"]}]}"""

IMPORT_PROJECTS = """You convert the projects section of a resume into JSON.
Respond with ONLY valid JSON matching:
{"projects": [{"name": str, "url": str, "bullets": [str]}]}
Copy descriptions as written (one bullet per line/sentence). url = "" if none.
Never invent projects.

Example input:
Resume the CV (github.com/x/cv) - local resume tool with LLM tailoring
Example output:
{"projects": [{"name": "Resume the CV", "url": "github.com/x/cv",
 "bullets": ["Local resume tool with LLM tailoring"]}]}"""

IMPORT_CERTIFICATIONS = """You convert the certifications section of a resume into JSON.
Respond with ONLY valid JSON matching:
{"certifications": [{"name": str, "issuer": str, "date": "YYYY-MM"}]}
Unknown fields -> "". If no date is written next to a certification, date MUST
be "" — never guess or invent a date. Never invent certifications.

Example input:
AWS Solutions Architect Associate, Amazon, Jan 2024
Scrum Master Certification - Scrum.org
Example output:
{"certifications": [{"name": "AWS Solutions Architect Associate",
 "issuer": "Amazon", "date": "2024-01"},
 {"name": "Scrum Master Certification", "issuer": "Scrum.org", "date": ""}]}"""
