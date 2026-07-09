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

# --- §5.2 bullet optimizer ----------------------------------------------------

BULLET_REWRITE = """You tighten one resume bullet point. Respond with ONLY valid JSON:
{"tightened": str or null}
tightened = the same achievement in max 24 words, starting with a strong
past-tense action verb, filler removed, wording sharpened. Keep ALL facts
exactly. Never invent facts, numbers, employers, or technologies. If the bullet
is already tight and strong with nothing to improve, use null.

Example input:
Bullet: Responsible for helping with the migration of various legacy services to AWS which resulted in improvements in reliability
Flags: filler, no metric, too long
Example output:
{"tightened": "Migrated legacy services to AWS, improving reliability"}"""

BULLET_METRIC = """You add a measurement placeholder to a resume bullet that has
no number. Respond with ONLY valid JSON: {"metric_variant": str}
Rewrite the bullet inserting ONE bracketed placeholder — like [X%], [N],
[$Y], [N users], [Nx] — at the single spot where a real, quantifiable result
would most strengthen it. The placeholder is a blank the user fills in later.
Rules: insert placeholders ONLY, never a real number. Keep every existing fact.
Change as little else as possible. Always return a metric_variant (this bullet
was already selected because it lacks a metric).

Example input:
Reduced page load time on the checkout flow
Example output:
{"metric_variant": "Reduced checkout page load time by [X%]"}

Example input:
Managed a team of engineers to ship the mobile app
Example output:
{"metric_variant": "Managed a team of [N] engineers to ship the mobile app"}"""

# --- §5.1 job tailoring ---------------------------------------------------------

JD_EXTRACT = """You extract structured data from job descriptions.
Respond with ONLY valid JSON matching:
{"target_title": str, "hard_skills": [str], "soft_skills": [str],
 "keywords": [str], "action_verbs": [str], "must_have_qualifications": [str]}
hard_skills = technologies, tools, languages, and methods explicitly named.
soft_skills = interpersonal/work-style traits explicitly asked for.
keywords = other domain terms an ATS would match (not already in hard_skills).
action_verbs = verbs the JD uses for the work itself (build, own, design…).
must_have_qualifications = short paraphrases of explicit requirements.
Max 15 items per list; [] when nothing fits. Copy terms as written in the JD.
Never add skills or requirements the JD does not mention.

Example input:
Senior Backend Engineer. You will design Go microservices on Kubernetes and
own our PostgreSQL data layer. Requirements: 5+ years backend experience,
strong communication skills, CI/CD experience.
Example output:
{"target_title": "Senior Backend Engineer",
 "hard_skills": ["Go", "Kubernetes", "PostgreSQL", "CI/CD"],
 "soft_skills": ["communication"],
 "keywords": ["microservices", "backend", "data layer"],
 "action_verbs": ["design", "own"],
 "must_have_qualifications": ["5+ years backend experience"]}"""

TAILOR_REWRITE = """You rewrite one resume bullet so it naturally includes a
keyword from a job description. Respond with ONLY valid JSON:
{"rewrite": str or null}
A rewrite is honest ONLY when the bullet already shows the same thing in
other words: expanding an abbreviation (UE5 -> Unreal Engine 5), or using the
keyword as the exact name/category of what the bullet already describes.
Never invent facts, numbers, employers, technologies, versions, or experience
the bullet does not show. A different version or tool is NOT the same thing:
UE4 is not Unreal Engine 5, MySQL is not PostgreSQL. Keep every original
fact. Max 30 words. When in doubt, "rewrite" MUST be null.
The input may include "User guidance" describing tone or emphasis; follow it
for style only. It NEVER permits inventing facts — if honesty and the guidance
conflict, honesty wins and "rewrite" is null.

Example input:
Keyword: Unreal Engine 5
Bullet: Designed a custom UE5 editor plugin in C++ to automate level checks
Example output:
{"rewrite": "Designed a custom Unreal Engine 5 editor plugin in C++ to automate level checks"}

Example input:
Keyword: Unreal Engine 5
Bullet: Built an automated patching pipeline for our UE4 title using Jenkins
Example output:
{"rewrite": null}

Example input:
Keyword: data visualization
Bullet: Built Grafana dashboards to monitor API latency across services
Example output:
{"rewrite": "Built Grafana dashboards for data visualization of API latency across services"}

Example input:
Keyword: multiplayer networking
Bullet: Wrote unit tests for the payments API
Example output:
{"rewrite": null}"""

# --- §5.3 summary + headline generator ------------------------------------------

SUMMARY_VARIANTS = """You write resume professional-summary lines from a candidate
digest. Respond with ONLY valid JSON: {"variants": [str, str, str]}
Exactly 3 variants. Each is 2-3 sentences, third person with NO first-person
pronouns (no "I", "my", "me"), plain professional English. State role, years of
experience, strongest skills, and one signature strength. If a target role is
given, angle the wording toward it — but only using facts in the digest.
Banned words (never use): passionate, dynamic, results-driven, motivated,
detail-oriented, team player, hardworking, go-getter, synergy, proven track
record, thought leader, ninja, guru, rockstar, seasoned, wheelhouse.
Never invent employers, numbers, titles, or skills not in the digest.

Example input:
Years: 6. Current title: Backend Engineer. Top skills: Python, Go, PostgreSQL,
Kubernetes. Signature achievements: Cut API latency by 40%; Led migration of 12
services to AWS. Target role: Senior Platform Engineer
Example output:
{"variants": [
 "Backend engineer with 6 years building high-throughput services in Python and Go. Cut API latency 40% and led the migration of 12 services to AWS, with deep PostgreSQL and Kubernetes experience.",
 "Platform-focused backend engineer with 6 years of experience owning reliability and infrastructure. Known for cutting API latency 40% and moving 12 services to AWS on Kubernetes.",
 "Engineer with 6 years across Python, Go, and Kubernetes who ships reliable backends. Delivered a 40% latency reduction and a 12-service AWS migration."]}"""

HEADLINE_VARIANTS = """You write resume headline / title lines from a candidate
digest. Respond with ONLY valid JSON: {"headlines": [str, str, str]}
Exactly 3 options for the CV title line under the name. Each is a short plain-text
line naming a role plus 2-3 core specialties, separated by " · " (middle dot).
Max ~9 words. NO pipes or emojis — an ATS must parse it as plain text.
The specialties MUST be copied verbatim from the digest's "Top skills" list.
NEVER add a technology, tool, or skill that is not in that list, even if the
target role suggests it — a target role can only reorder or reword the ROLE
part, never introduce new skills. If a skill is not in the digest, do not use it.

Example input:
Years: 6. Current title: Backend Engineer. Top skills: Python, Go, PostgreSQL,
Kubernetes. Target role: Senior Platform Engineer
Example output:
{"headlines": [
 "Senior Platform Engineer · Python · Kubernetes",
 "Backend Engineer · Go · PostgreSQL",
 "Platform Engineer · Python · PostgreSQL · Kubernetes"]}"""

# --- §5.5 cover letter pipeline -------------------------------------------------

LETTER_OUTLINE = """You outline a cover letter as 4 short beats. Respond with ONLY
valid JSON: {"beats": [{"name": "hook", "point": str},
{"name": "fit1", "point": str}, {"name": "fit2", "point": str},
{"name": "close", "point": str}]}
Each "point" is ONE sentence stating what that beat should say — a plan, not the
prose. hook = why this candidate + this role; fit1 and fit2 = map a specific
candidate achievement to a top job requirement (name both); close = enthusiasm +
call to action. Use only the candidate digest and job requirements given. Never
invent achievements, employers, or numbers.

Example input:
Role: Senior Backend Engineer at Acme. Top requirements: Go microservices,
PostgreSQL, CI/CD. Candidate digest: 6 yrs backend; cut API latency 40%; led
12-service AWS migration; strong in Python, Go, PostgreSQL, Kubernetes.
Example output:
{"beats": [
 {"name": "hook", "point": "Open with genuine interest in Acme's backend role and 6 years of relevant experience."},
 {"name": "fit1", "point": "Connect the 12-service AWS migration to Acme's need for someone who owns Go microservices at scale."},
 {"name": "fit2", "point": "Connect the 40% API latency reduction and PostgreSQL depth to the data-layer and CI/CD requirements."},
 {"name": "close", "point": "Express eagerness to contribute and invite a conversation."}]}"""

LETTER_BEAT = """You write ONE paragraph of a cover letter from a single beat
instruction and the relevant candidate facts. Respond with ONLY valid JSON:
{"paragraph": str}
Write 2-4 sentences of natural, professional prose in the first person ("I").
Match the requested tone. Use ONLY the facts provided — never invent employers,
numbers, achievements, or skills. Do not add a greeting or sign-off; just the
paragraph. No clichés (passionate, results-driven, team player, dynamic).

Example input:
Tone: professional
Beat: Connect the 40% API latency reduction to the data-layer requirement.
Relevant facts: Cut API latency by 40% by tuning PostgreSQL queries and caching.
Example output:
{"paragraph": "Your emphasis on a reliable data layer maps directly to my recent work: I cut API latency by 40% by tuning PostgreSQL queries and introducing a caching layer. That experience has made me comfortable owning performance and correctness across a service's data path."}"""

# --- §5.4 LLM grammar pass ----------------------------------------------------

GRAMMAR = """You proofread resume text. Report grammar, spelling, and punctuation
errors only — never style or content rewrites. Respond with ONLY valid JSON:
{"issues": [{"quote": str, "issue": str, "fix": str}]}
quote = the exact words copied from the text that contain the error (max 10
words). Max 5 issues. If there are no errors return {"issues": []}. Never
invent errors just to fill the list.

Example input:
Lead a team of five engineer to deliver the the payments platform
Example output:
{"issues": [{"quote": "Lead a team", "issue": "wrong tense", "fix": "Led a team"},
 {"quote": "five engineer", "issue": "missing plural", "fix": "five engineers"},
 {"quote": "the the payments", "issue": "duplicated word", "fix": "the payments"}]}"""
