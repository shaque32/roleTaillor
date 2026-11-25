# RoleTailor UX audit

Covers every screen from sign-up to settings, on desktop and phone. Ranked by cost to the user. All fixes are frontend only.

| # | Screen | What's wrong | Fix |
|---|---|---|---|
| 1 | Onboarding → New tailoring | Skipping AI consent ("Not now") lets users fill in the whole tailoring form, then blocks them with an error that sends them back to onboarding and loses their input. | Ask for consent in a pop-up at the moment it is needed, then start automatically. |
| 2 | Review changes | Clicking Accept or Reject twice silently undoes the decision. Nothing says un-reviewed changes still go into the download. Changes carry internal codes ("b4") and an unexplained checkbox. | A clear two-way choice ("Use rewrite" / "Keep original") with an explicit Undo, an "accept all remaining" button, and a "4 of 6 reviewed" counter. |
| 3 | Review changes | Before/after highlights scattered single words in red and green; hard to read. | Highlight whole phrases; when most of a line changed, show clean before/after text. |
| 4 | Resumes, Applications (phone) | Text collapses to one word per line and overlaps the buttons. Dashboard cuts off names. | Stack text above actions; let names wrap. |
| 5 | New tailoring | Two browser-default dropdowns, a link/paste switch and a hidden optional section. | One box: "paste the job link or description". Resume shown as pick-cards; latest version by default. |
| 6 | Dashboard | A running row opens to "0 changes proposed" and greyed-out download buttons. The list never updates by itself. Jargon labels ("HM sim."). | Running rows show "In progress" and one button. The list refreshes itself. Plain labels; one click opens the review. |
| 7 | Review page | One long page of five boxed panels. | Result summary on top (score before → after, downloads), then three tabs: Changes, Missing keywords, Hiring-manager view. |
| 8 | All forms | A dozen browser-default dropdowns, small inputs, boxes inside boxes. | Larger, softer inputs; a custom dropdown; tappable choice cards for short lists; flat sections instead of nested boxes. |
| 9 | Settings | Consent shows "Grant" and "Withdraw" with no current state. | Show the state and the one relevant button; confirm before withdrawing. |
| 10 | Sign-in, onboarding, progress, empty states | Bare; progress gives little sense of movement. | Soft animated backdrop, clearer step tracker, livelier progress screen. |

## Also fixed

- Grey helper text and input outlines fail accessibility contrast; both darkened.
- Sign-out is an unlabeled icon; it gets a label.
- Phones get a bottom tab bar instead of a hamburger menu.
- The share-link pop-up gets a "Copy link" button.

## Deliberately not doing

- No decoration on work screens (dashboard, review, tracker, settings). Effects are limited to sign-in, onboarding, empty states and progress, and switch off for users who ask for reduced motion.
- No 3D or heavy backgrounds. One small animation library is added; five small visual components come from Aceternity UI and React Bits.
- The upload box and billing panel are restyled only through shared styles, with no line edits, because PR #3 is changing those two files.

## Decided

AI consent is asked at the first tailoring, in a pop-up, not as the first onboarding screen (Arsh, 2026-11-25). Onboarding is now two steps: your resume, then your first job.

Implementation detail: `frontend/dev/REDESIGN_SPEC.md`.
