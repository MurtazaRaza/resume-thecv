// ATS-safe resume template (SPEC §7): single column, no tables/icons/photos,
// standard section headers, plain-text bullets. Data comes pre-formatted from
// backend/core/render.py as JSON (dates already turned into display strings).

#let data = json(sys.inputs.data)

#set page(paper: "a4", margin: (x: 1.7cm, y: 1.5cm))
#set text(font: ("Helvetica", "Libertinus Serif"), size: 10.5pt)
#set par(justify: false, leading: 0.55em)
#set list(indent: 0.6em, body-indent: 0.5em, spacing: 0.65em)

#let section(title) = {
  v(12pt)
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

// ---- summary ---------------------------------------------------------------
#if data.summary != "" {
  section("Summary")
  data.summary
}

// ---- experience ------------------------------------------------------------
#if data.experience.len() > 0 {
  section("Experience")
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

// ---- education -------------------------------------------------------------
#if data.education.len() > 0 {
  section("Education")
  for e in data.education {
    block(above: 6pt, below: 0pt)[
      #entry-line[
        #text(weight: "bold", e.degree)#if e.institution != "" [, #e.institution]
      ][#e.dates]
      #if e.details != "" [ #text(size: 9.5pt, e.details) ]
    ]
  }
}

// ---- skills ----------------------------------------------------------------
#if data.skills.len() > 0 {
  section("Skills")
  for s in data.skills [
    #if s.group != "" [#text(weight: "bold", s.group): ]#s.items.join(", ") \
  ]
}

// ---- projects --------------------------------------------------------------
#if data.projects.len() > 0 {
  section("Projects")
  for p in data.projects {
    block(above: 6pt, below: 0pt)[
      #text(weight: "bold", p.name)#if p.url != "" [ — #p.url]
      #for b in p.bullets [
        - #b.text
      ]
    ]
  }
}

// ---- certifications ---------------------------------------------------------
#if data.certifications.len() > 0 {
  section("Certifications")
  for c in data.certifications [
    - #c.name#if c.issuer != "" [, #c.issuer]#if c.date != "" [ (#c.date)]
  ]
}
