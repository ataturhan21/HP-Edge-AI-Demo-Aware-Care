HEALTHGUIDE MOCKUP PACKAGE
A complete visual and interaction handoff for the mock-data website.

START HERE
1. Read HealthGuide_All_Screen_Mockups.pdf for the full screen catalogue.
2. Open HealthGuide_Interactive_Reference.html in a desktop browser. It works as a local file without a server or network.
3. Attach the ZIP and PDF to the Sites conversation. Paste SITES_BUILD_PROMPT.txt as the build instruction.
4. If ZIP extraction is unavailable in that conversation, attach the standalone HTML, build prompt and the most relevant PNGs directly. The HTML includes its own CSS, JavaScript and screen registry.

CONTENTS
- 24 desktop screenshots and 24 mobile screenshots, named by stable screen ID.
- 9 additional desktop state screenshots: consent validation, question validation, guidance loading, failure, stale result, no matches, offline directory, contact confirmation, deletion confirmation.
- A self-contained interactive HTML reference with the same visual system.
- theme.css and app.js, the editable reference sources.
- spec/screens.json: exact routes, IDs, owners and product requirement mappings.
- spec/fixtures.json: fictional scenarios, questions and providers.
- spec/captures.json: image-to-screen manifest.
- SITES_BUILD_PROMPT.txt: complete build instruction, scope overrides and acceptance criteria.
- QA_REPORT.txt: actual checks performed on the downloadable reference.

IMPORTANT DISTINCTION
This is a mock-data design package. The supplied HTML is a working interaction reference, not the future secure/clinical backend implementation. No model, hardware, health records, real doctors or medical assessment are connected. Use fictional examples only. The original Product Master Document v2.0 remains the future connected-product plan.

VISUAL CONVENTIONS
HealthGuide is a working name. Blue is the primary action, teal marks completion/context, warm accents mark attention, and red marks an urgent/error demonstration. All doctors are fictional and use initials instead of generated photos. No logo implies an approved official HP product.

SCREEN FAMILIES
W01-W05: public website.
A01-A16: setup, consultation, guidance, care navigation, history, settings and exceptions.
O01-O03: open-access demo studio, explicitly simulated.

REFERENCE NAVIGATION
Use ordinary buttons for a true sample journey. The bottom Design Reference selector intentionally seeds valid fixture state so a reviewer can inspect any screen without completing the prior steps. It is a review tool, not evidence that route prerequisites may be bypassed in the built product.
