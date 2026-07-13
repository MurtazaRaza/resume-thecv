// ATS-safe resume template (SPEC §7): single column, no tables/icons/photos,
// standard section headers, plain-text bullets. Data comes pre-formatted from
// backend/core/render.py as JSON (dates already turned into display strings).

#let data = json(sys.inputs.data)

#set page(paper: "a4", margin: (x: 1.7cm, y: 1.5cm))
#set text(font: ("Helvetica", "Libertinus Serif"), size: 10.5pt)
#set par(justify: false, leading: 0.55em)
#set list(indent: 0.6em, body-indent: 0.5em, spacing: 0.65em)

#let section(title, space: 12pt) = {
  v(space)
  text(size: 10.5pt, weight: "bold", tracking: 0.06em, upper(title))
  v(-7pt)
  line(length: 100%, stroke: 0.6pt + luma(120))
  v(1pt)
}

#let entry-line(left-part, right-part) = {
  grid(columns: (1fr, auto), column-gutter: 8pt,
    left-part, align(right, text(size: 9.5pt, right-part)))
}

// ---- header ----------------------------------------------------------------
#align(center)[
  #text(size: 19pt, weight: "bold", data.basics.name)
  #if data.basics.title != "" [
    #v(-6pt)
    #text(size: 11pt, data.basics.title)
  ]
  #v(-4pt)
  #text(size: 9.5pt, data.contact_line)
]

// ---- section bodies (keyed by name, dispatched via data.section_order) ------
#let render-summary(space: 12pt) = {
  if data.summary != "" {
    section("Summary", space: space)
    data.summary
  }
}

#let render-experience(space: 12pt) = {
  if data.experience.len() > 0 {
    section("Experience", space: space)
    for e in data.experience {
      block(breakable: true, above: 8pt, below: 0pt)[
        #entry-line[
          #text(weight: "bold", e.title)#if e.company != "" [, #e.company]
          #if e.location != "" [ — #e.location]
        ][#e.dates]
        #for b in e.bullets [
          - #b.text
        ]
      ]
    }
  }
}

#let render-education(space: 12pt) = {
  if data.education.len() > 0 {
    section("Education", space: space)
    for e in data.education {
      block(above: 6pt, below: 0pt)[
        #entry-line[
          #text(weight: "bold", e.degree)#if e.institution != "" [, #e.institution]
        ][#e.dates]
        #if e.details != "" [ #text(size: 9.5pt, e.details) ]
      ]
    }
  }
}

#let render-skills(space: 12pt) = {
  if data.skills.len() > 0 {
    section("Skills", space: space)
    for s in data.skills [
      #if s.group != "" [#text(weight: "bold", s.group): ]#s.items.join(", ") \
    ]
  }
}

#let render-projects(space: 12pt) = {
  if data.projects.len() > 0 {
    section("Projects", space: space)
    for p in data.projects {
      block(above: 6pt, below: 0pt)[
        #text(weight: "bold", p.name)#if p.url != "" [ — #p.url]
        #for b in p.bullets [
          - #b.text
        ]
      ]
    }
  }
}

#let render-certifications(space: 12pt) = {
  if data.certifications.len() > 0 {
    section("Certifications", space: space)
    for c in data.certifications [
      - #c.name#if c.issuer != "" [, #c.issuer]#if c.date != "" [ (#c.date)]
    ]
  }
}

#let renderers = (
  summary: render-summary,
  experience: render-experience,
  education: render-education,
  skills: render-skills,
  projects: render-projects,
  certifications: render-certifications,
)

// section_spacing holds only overrides (points); default gap is 12pt.
#let spacing = data.at("section_spacing", default: (:))
#for name in data.section_order {
  let r = renderers.at(name, default: none)
  if r != none { r(space: spacing.at(name, default: 12) * 1pt) }
}
