// Cover letter template (SPEC §5.5). Single column, plain text, ATS-safe —
// same philosophy as cv.typ. Data comes pre-assembled from
// backend/core/render.py as JSON: a sender header, a date, and the letter body
// already split into paragraphs.

#let data = json(sys.inputs.data)

#set page(paper: "a4", margin: (x: 2cm, y: 2cm))
#set text(font: ("Helvetica", "Libertinus Serif"), size: 11pt)
#set par(justify: false, leading: 0.62em, first-line-indent: 0pt, spacing: 0.9em)

// ---- sender header ----------------------------------------------------------
#text(size: 15pt, weight: "bold", data.name)
#if data.contact_line != "" [
  #v(-6pt)
  #text(size: 9.5pt, data.contact_line)
]

#v(6pt)
#if data.date != "" [ #data.date \ ]
#if data.company != "" [ #data.company ]

#v(6pt)

// ---- body -------------------------------------------------------------------
#for para in data.paragraphs [
  #para

]
