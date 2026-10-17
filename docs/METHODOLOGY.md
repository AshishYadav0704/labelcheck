# How LabelCheck scores food

This document is for anyone checking the health claims the app makes: nutritionists,
reviewers, examiners. Every number in a report comes from a fixed rule below and a
reference file in `backend/app/data/`. **AI never decides a score, a risk or a health
claim.** AI is used only to read label photos and, optionally, to re-word a finished
report in simpler language using the report's own facts.

## 1. Inputs

The rules read, per 100 g (solid foods) or per 100 ml (drinks):

- energy, fat, saturated fat, trans fat, carbohydrate, sugars, added sugars, fibre, protein and sodium/salt
  (salt = sodium × 2.5)
- the ingredient list, including INS / E numbers
- serving size, the FSSAI veg / non-veg mark, and allergen statements

These come from a label photo (AI vision or offline OCR), typed or pasted label text,
or Open Food Facts (by barcode). Photo and text readings are shown to the user to
**check and correct before the report is made**. Readings that look implausible (for
example, energy that doesn't match fat + carbohydrate + protein) are flagged.

## 2. Health score (0–100) and grade

| Part | Points | Rule |
|---|---|---|
| Nutrition | 0–60 | Nutri-Score points (2017 algorithm, Santé publique France), mapped linearly: −1 or less → 60, 25 or more → 0. Drinks use the drink scale (0 → 60, 15 → 0). |
| Processing | 0–20 | Estimated NOVA group: 1 → 20, 2 → 16, 3 → 12, 4 → 4. |
| Additives | 0–20 | 20 minus 10 for each *high*-concern and 4 for each *moderate*-concern additive. |
| Penalties | | −3 per "HIGH" front-of-pack warning (max −9); −10 for a drink with ≥ 8 g sugar per 100 ml; −10 for trans fat ≥ 0.2 g/100 g or hydrogenated fat in the ingredients. |
| Cap | | An additive banned in India (e.g. potassium bromate) caps the score at 10. |

Grades: **A** ≥ 80 · **B** 60–79 · **C** 40–59 · **D** 20–39 · **E** < 20.

A personal score adjusts this for the user's profile (for example −15 for a high-sugar
product when the profile says diabetes). Every adjustment is listed in the report.

## 3. Reference limits

Daily limits (WHO, adult, 2000 kcal reference; scaled to 1500 kcal for children):

| Nutrient | Limit | Source |
|---|---|---|
| Salt | < 5 g (2 g sodium) | WHO salt reduction fact sheet |
| Free sugars | < 50 g (10% energy), ideally < 25 g | WHO sugars guideline (2015) |
| Saturated fat | < 22 g (10% energy) | WHO healthy diet / 2023 fatty-acid guideline |
| Trans fat | < 2.2 g (1% energy), ideally 0 | WHO trans fat fact sheet |
| Total fat | < 67 g (30% energy) | WHO healthy diet |
| Fibre | ≥ 25 g | WHO carbohydrate guideline (2023) |

"HIGH" warnings (per 100 g / 100 ml) currently use the UK Food Standards Agency
front-of-pack "high" criteria: fat > 17.5 / 8.75, saturated fat > 5 / 2.5, sugars
> 22.5 / 11.25, salt > 1.5 / 0.75. FSSAI has proposed red hexagon "HIGH FAT / HIGH
SUGAR / HIGH SALT" warnings, but had not published final thresholds when this was
written (October 2026). When FSSAI notifies them, change `high_thresholds` in
`standards.json`. No code change is needed.

## 4. Additives (142 entries)

`additives.json` holds, for each INS number: name and aliases, function, the
acceptable daily intake (ADI, mg/kg body weight/day) with its source (JECFA unless
stated, EFSA where it differs), IARC group, FSSAI status, status elsewhere (EU, USA),
who should be careful, and whether it can be of animal origin.

"Concern" is the app's plain-language summary, not a regulatory status:

- **high**: banned in India or major markets, or a Group 1 carcinogen context (sodium nitrite in processed meat, potassium bromate, BVO)
- **moderate**: a regulatory warning or restriction exists somewhere (e.g. EU hyperactivity warning on azo dyes, US ban on erythrosine, IARC 2B), or the ADI can realistically be approached
- **low**: permitted, with a minor or unconfirmed concern
- **none**: no concern at normal use

An additive approved and used within its ADI is **not described as toxic**. Where
regulators disagree (e.g. aspartame: IARC 2B, JECFA ADI unchanged), the report shows both.

## 5. Processing (NOVA, estimated)

NOVA 4 (ultra-processed) if the list contains a cosmetic additive (colour, flavour
enhancer, sweetener, emulsifier, thickener, glazing or gelling agent) or an industrial
ingredient (hydrogenated/interesterified fat, maltodextrin, glucose/invert syrup,
modified starch, protein isolate, flavouring, whey, lactose…). Otherwise NOVA 3 if it
contains salt, sugar, oil or simple preservatives; NOVA 2 for a single culinary
ingredient; NOVA 1 for minimally processed foods. Always labelled "estimated".

## 6. Linked health effects

`health_links.json` maps triggers (high salt, sugary drink, trans fat, NOVA 4, nitrites,
refined + low fibre, sweeteners, azo colours, phosphates, caffeine…) to effects with an
evidence level and a source link:

- **strong**: WHO/IARC consensus, consistent trials and cohorts
- **moderate**: consistent observational evidence
- **limited**: early or mixed evidence

Wording is always "linked with regular, excess intake", never "causes".

## 7. Long-term illustration ("what if I eat this regularly")

For each body system, a daily load is the share of the daily limit this product uses
at the chosen frequency (salt, sugar, saturated and trans fat, energy), plus small
fixed terms for NOVA 4, low fibre, processed meat and phosphates. Strain after *y*
years is `1 − exp(−0.24 × load × y)`, shown as minimal / mild / moderate / high.
This is a **design model to make general evidence visible, not a clinical
prediction**, and the video says so on every frame.

## 8. Diet checks

Vegetarian follows the Indian meaning (no meat, fish or egg), matching FSSAI's green
mark. The app also supports vegetarian + egg, vegan and Jain. Checks use ingredient
keywords, additives of animal origin (e.g. carmine 120, bone phosphate 542) and the veg
mark. Additives whose source isn't stated (e.g. 471, 631) are shown as a caution, not
a verdict.

## 9. Known limitations

- Labels list additives but not their amounts, so the app can't compute how close a
  person gets to an ADI. It shows the ADI and who should be careful.
- Total sugars on Indian labels include natural milk and fruit sugar. Added sugars are
  used where printed.
- OCR is weaker than AI vision on curved or glossy packs. That's why every reading goes
  through user review.
- Nutri-Score's special cases for cheese and added fats are not implemented.

## 10. Keeping the data right

Before a public launch, a qualified nutritionist or food scientist should review every
entry in `backend/app/data/` against the primary sources (JECFA database, EFSA
opinions, IARC Monographs list, FSSAI Food Products Standards and Food Additives
Regulations). Re-review at least every six months, since regulatory status changes. Each
file carries `last_reviewed` in its `meta` block, and the test suite checks that every
entry is complete and every health link has a source.
