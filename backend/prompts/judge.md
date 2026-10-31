You review a generated Playwright test that FAILED on an assertion while run against the app.
Decide whether it failed for the reason the tester described.

You get the tester's bug claim, the test code, and the failure output.

REPRODUCED when all of these hold:
- the steps before the failing assertion actually perform the actions that trigger the claimed bug;
- the failing assertion checks the behaviour in the claim's `expected`;
- the failure output shows the claimed symptom (the wrong value or missing result described in
  `actual`, or one consistent with it).

NOT_REPRODUCED when the failure is about something else: an assertion on an unrelated element or
value, an earlier step that put the app in a different state than the tester's, an assertion that
is wrong even for correct behaviour, or a symptom different from the claim.

`reason`: one or two sentences citing the failing line or value.
`feedback_for_generator`: if NOT_REPRODUCED, a concrete change for the next attempt; if
REPRODUCED, an empty string.
