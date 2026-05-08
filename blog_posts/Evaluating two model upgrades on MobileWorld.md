---
authors: Quyu Kong, Yue Wang
---

# Evaluating two model upgrades on MobileWorld

We ran two recent model upgrades — Anthropic's Opus 4.6 → 4.7 and Moonshot's Kimi K2.5 → K2.6 — through MobileWorld, our 161-task benchmark for mobile GUI agents driving an Android phone. This post summarizes what changed in each upgrade.

## TL;DR

*   Opus 4.7 outperforms 4.6 by **+15.5pp** (42.7% → 58.2%); Kimi K2.6 outperforms K2.5 by **+9.3pp** (46.6% → 55.9%). Both are large gains for a point-release.
    
*   The largest source of improvement in both upgrades is **loop-breaking** — recognizing that an action produced no observable change and switching strategy. It accounts for 44% of Opus's new wins and 59% of Kimi's.
    
*   Opus 4.7's biggest jump is on **Agent–User Interaction** tasks (+25pp), driven by knowing _when_ to ask: 4.6 frequently terminated early when key information was missing, whereas 4.7 issues an `ask_user` call and proceeds with the answer.
    
*   Several task clusters remain unsolved: Mastodon settings whose Android client lacks parity with the web UI, long-horizon Mattermost workflows that exceed the step budget, PDF tasks where the agent gets trapped in search-and-scroll loops inside the mobile viewer, and archive workflows where date-range filtering over a long file list consumes the step budget before the zip+email finale.
    

## 1. Headline results

| Pair | Prior | Latest | Δ |
| --- | --- | --- | --- |
| Opus 4.6 → 4.7 | 67/157 = 42.7% | 92/158 = 58.2% | +15.5pp |
| Kimi K2.5 → K2.6 | 75/161 = 46.6% | 90/161 = 55.9% | +9.3pp |

On the 154-task intersection where both Opus runs finished, 4.7 wins 36 tasks that 4.6 lost, regresses on 11, and holds 107 (56 both pass, 51 both fail). Net +25. K2.6 has a similar shape: 27 new wins, 12 regressions, 122 unchanged. We note some cases among the full 161 were not completed due to consistent API errors (see §5).

MobileWorld tasks come in three flavors: **GUI-Only**, where the agent operates the phone autonomously; **Agent–User Interaction**, where the task is intentionally under-specified and the agent must call `ask_user` for clarifications; and **MCP**, where the agent calls remote tools alongside the GUI. This post covers only the first two.

### Setup

All four runs used the `general_e2e` agent prompt with a 50-step task budget. Run dates and history-image counts:

| Run | Date | History images |
| --- | --- | --- |
| Opus 4.6 | 2026-02-05 | 1 |
| Opus 4.7 | 2026-04-22 | 1 |
| K2.5 (1-image rerun) | 2026-01-31 | 1 |
| K2.6 | 2026-04-22 | 3 |

Caveats on the K2.5 rerun and Opus 4.6 coverage are in §5.

## 2. Opus 4.6 → 4.7

We grouped the changes into three categories: wins where 4.6 had a recurring failure mode that 4.7 closes; patterns prominent enough in 4.6 that we noted them as their own categories during review (and that 4.7 no longer exhibits); and regressions, mostly clustered around 4.7 being more interpretive than 4.6.

| Direction | Pattern | Freq | What 4.6 did | What 4.7 did | Featured replay | Other examples |
| --- | --- | --- | --- | --- | --- | --- |
| Win | Loop-breaking on stalled progress | 16 / 36 | Repeats the same action when nothing changes — clicks the same dead label, scrolls the same list | Detects no-progress, escalates action _type_ (click→drag, scroll→long-press) | [`AdjustBrightnessMaximumTask`](https://tongyi-mai.github.io/MobileWorld/arena?modelA=Claude-Opus-4.6&modelB=Claude-Opus-4.7&task=AdjustBrightnessMaximumTask&filter=fp&step=5) — 50 → 7 steps | `CountFileLinesTask`, `MastodonRemoveBookmarkTask`, `MastodonRevisePollTask` |
| Win | Ask-user integration | 7 / 36 | Terminates with "no email found" when key information is missing | Calls `ask_user`, gets the answer, proceeds | [`SearchTopInfoAskUserTask`](https://tongyi-mai.github.io/MobileWorld/arena?modelA=Claude-Opus-4.6&modelB=Claude-Opus-4.7&task=SearchTopInfoAskUserTask&filter=fp) — 4 → 19 steps | `CheckMealEventAskUserTask`, `DeleteItemsAskUserTask`, `SayHelloRoommatesAskUserTask2` |
| Win | Multi-app workflow completion | 5 / 36 | Loses state crossing email → calendar → SMS boundaries | Maintains task context across apps | [`CheckMealEventAskUserTask`](https://tongyi-mai.github.io/MobileWorld/arena?modelA=Claude-Opus-4.6&modelB=Claude-Opus-4.7&task=CheckMealEventAskUserTask&filter=fp) — 50 → 43 steps | `SendInvoiceWithInfoTask`, `ScheduleLunchViaSmsTask` |
| Win | Upfront task decomposition | 5 / 36 | Wanders across apps and folders before locating the right starting screen, losing context on the way | Decomposes the task once, opens the correct app first, executes linearly | [`SendInterviewInvitationTask`](https://tongyi-mai.github.io/MobileWorld/arena?modelA=Claude-Opus-4.6&modelB=Claude-Opus-4.7&task=SendInterviewInvitationTask&filter=fp) — 33 → 13 steps | `CheckCandidateAskUserTask1` (50 → 19), `MastodonUpdateContactsTask` (50 → 28) |
| Quietly fixed | Strict refusals on personal tasks | recurring | Refuses with _"I can't help with this request. I'm designed to assist with software development, coding…"_ | Attempts the task | [`PhotoManagementTask`](https://tongyi-mai.github.io/MobileWorld/arena?modelA=Claude-Opus-4.6&modelB=Claude-Opus-4.7&task=PhotoManagementTask&filter=ff) | — |
| Quietly fixed | Malformed action JSON | 2 occurrences in 4.6 | Emits invalid JSON: `{"action_type", "click", "coordinate":[154, 393]}` (missing colon) → parser throws `Expecting ':' delimiter` → run terminates | Doesn't produce these | [`ReadQwen3PaperTask2`](https://tongyi-mai.github.io/MobileWorld/arena?modelA=Claude-Opus-4.6&modelB=Claude-Opus-4.7&task=ReadQwen3PaperTask2) | — |
| Quietly fixed | Action-knowledge gaps | misc | `long_press` to "clear text" (which on Android opens a context menu) | Calls `input_text` directly — knows it auto-clears the focused field | [`MastodonMallPurchaseCommodityTask`](https://tongyi-mai.github.io/MobileWorld/arena?modelA=Claude-Opus-4.6&modelB=Claude-Opus-4.7&task=MastodonMallPurchaseCommodityTask&filter=fp) | — |
| Regression | Premature termination on semantic match | 4 / 11 | Continued past a partial match to actually complete the task | Conflates "found evidence" with "done"; emits `goal_status: complete` early | [`CheckRegistrationTask`](https://tongyi-mai.github.io/MobileWorld/arena?modelA=Claude-Opus-4.6&modelB=Claude-Opus-4.7&task=CheckRegistrationTask&filter=pf&step=2) — 13 → 2 steps | `DeleteEventAskUserTask`, `MattermostCreateChannelTask` |
| Regression | Action repetition on dense UIs | 3 / 11 | Recovered from misclicks on Mastodon and checkout flows | Stuck in `navigate_back` ↔ `click` cycles when the menu opens on the wrong post | [`MastodonPinTootsTask`](https://tongyi-mai.github.io/MobileWorld/arena?modelA=Claude-Opus-4.6&modelB=Claude-Opus-4.7&task=MastodonPinTootsTask&filter=pf) | `MastodonAddBookmarkTask`, `MastodonExportFollowsTask` |
| Regression | Over-precise interpretation | 2 / 11 | Took instructions loosely (forgiving keyword match) | Applies a "don't break the file's identity" heuristic over explicit instruction | [`BidFileRenameAskUserTask`](https://tongyi-mai.github.io/MobileWorld/arena?modelA=Claude-Opus-4.6&modelB=Claude-Opus-4.7&task=BidFileRenameAskUserTask&filter=pf&step=42) | `MastodonRevisePhotoAltTask` |

The clearest illustration of the loop-breaking pattern is `AdjustBrightnessMaximumTask` (set device brightness to maximum). 4.6 spends all 50 steps clicking various non-interactive elements — the brightness label, the row header, the back button — never attempting a drag. A representative step:

```plaintext
Thought: I need to click on "Brightness level" to access the brightness slider and set it to maximum.
Action: {"action_type": "click", "coordinate": [288, 451]}


```

Each click produces no observable change. 4.7, after one click that doesn't move the needle, escalates the action type:

```plaintext
Thought: I can see the brightness slider at the top of the screen. It's currently at about 48%.
I need to drag the slider to the maximum (right end).
Action: {"action_type": "drag", "start_coordinate": [279, 115], "end_coordinate": [540, 115]}


```

The task completes in 7 steps.

The over-precise interpretation regression is worth dwelling on. On `BidFileRenameAskUserTask` (rename four files in chronological order to `bid_1.doc`, `bid_2.doc`, `bid_3.doc`, `bid_4.doc`), 4.7 silently preserved each file's original extension — `bid_1.txt`, `bid_2.pdf`, `bid_3.doc`, `bid_4.txt` — applying a "don't change what the file _is_" heuristic that violates the explicit specification. 4.6 took the instruction literally and passed. The same shape of regression appears in K2.6 (§3); we suspect it is a side effect of training signal that rewards thoughtful interpretation in ambiguous contexts.

Splitting Opus by task flavor: 4.6 scored 46.0% on GUI-Only versus 34.1% on Interaction; 4.7 scores 57.9% versus 59.1%, closing the gap. The largest single delta in this upgrade is on the interaction half — _when_ and _what_ to ask.

## 3. Kimi K2.5 → K2.6

K2.6's gains are dominated by a single class of fix: K2.5 frequently repeated an action when the resulting observation didn't change. K2.6 detects stalled progress and pivots.

| Direction | Pattern | Freq | What K2.5 did | What K2.6 did | Featured replay | Other examples |
| --- | --- | --- | --- | --- | --- | --- |
| Win | Loop-breaking | 16 / 27 | Scrolls or clicks identically for 30–50 steps when actions don't move forward | Detects stalled progress and pivots, often within 5–10 steps | [`MattermostReplyToMessageTask`](https://tongyi-mai.github.io/MobileWorld/arena?modelA=Kimi-K2.5&modelB=Kimi-K2.6&task=MattermostReplyToMessageTask&filter=fp&step=5) — 50 → 18 steps | `InvoiceReceiptCopyTask`, `BidFileRenameTask`, `LocalFileManagementTask` |
| Win | Better environment knowledge | 5 / 27 | Misses app-specific patterns | Knows GitHub API endpoints, Mattermost member lists, Android "Copy to" flows | [`CheckGithubInfoTask`](https://tongyi-mai.github.io/MobileWorld/arena?modelA=Kimi-K2.5&modelB=Kimi-K2.6&task=CheckGithubInfoTask&filter=fp) | `MattermostCreateChannelTask`, `GoogleMapsAlibabaPhoneContactTask` |
| Win | Multi-app workflow completion | 4 / 27 | Burns step budget on app A, never reaches app B | Budgets steps across calendar→alarm, email→SMS, file→email | [`CheckEventAndSetAlarmAskUserTask`](https://tongyi-mai.github.io/MobileWorld/arena?modelA=Kimi-K2.5&modelB=Kimi-K2.6&task=CheckEventAndSetAlarmAskUserTask&filter=fp) | `ReplyEmailViaSmsAskUserTask`, `SendZipFilesAskUserTask1`, `DownloadSendReceiptTask` |
| Regression | Over-precise semantic interpretation | misc | Loose keyword match | Linguistically precise — excludes "短袖睡衣" (short-sleeve pajamas) from "短袖T恤" (short-sleeve T-shirts), failing the keyword-based task evaluator | [`CartManagementTask`](https://tongyi-mai.github.io/MobileWorld/arena?modelA=Kimi-K2.5&modelB=Kimi-K2.6&task=CartManagementTask&filter=pf) | — |

Loop-breaking is best illustrated by `MattermostReplyToMessageTask` (reply to your own earlier message in a channel). K2.5 enters the channel and from step 4 onward produces this output character-for-character for the remaining 47 steps:

```plaintext
<think>
I'm seeing messages from Sep 9 now. I need to continue scrolling to find the user's
own message about OSWorld eval. The user said they want to reply to their "own earlier
message" - so I need to find a message from the current user (not from others like
lina, chen, harry, sam, arjun).
</think>
Action: {"action_type": "scroll", "direction": "down"}


```

`harry` is the current user. K2.5 never checks. K2.6, after a single scroll that produces no progress:

```plaintext
<think>
...the current user might be one of these. Let me check the profile to see who I am.
</think>
Action: click profile icon


```

Five steps later, K2.6 reads "harry (you)" off the Members panel, returns to the channel, and replies — 18 steps and 48% fewer tokens.

Loop-breaking is the largest single pattern in both upgrades — 44% of Opus's wins, 59% of Kimi's. Two independent vendors closing the same gap in the same release window suggests the limit was widely visible.

## 4. What both upgrades still fail on

51 tasks fail in both Opus 4.6 and 4.7; K2 fails on a comparable 59. The four clusters below cover most of the joint failures, and the failure mechanisms are mundane — none are "the model can't reason." They are variants of "the agent can't navigate the app, budget its steps, or extract structured data from a screen."

**Mastodon advanced UIs — Android client missing features that exist on web, plus naming traps.** The Android Mastodon app omits several settings the task implicitly assumes are present (e.g., importing muted accounts from a CSV). 4.7 correctly notices the option is missing but does not switch to a web fallback; it terminates. A second mode is naming ambiguity: in `MastodonChangeLanguageTask` the language list shows "Chinese" with no "Simplified" qualifier, and 4.7 also confuses *posting language* with *account language*, declaring success on the wrong toggle (`actual_language=en != expected_language=zh-CN`). These are app-knowledge gaps, not reasoning gaps.

**Mattermost long-thread workflows — phantom attachments and step-budget exhaustion.** Two mechanisms, both load-bearing. *Phantom execution*: in `MattermostEmailTask`, 4.7's thought log claims "the email has been sent successfully with the contract attached," but the trace shows it never executed an attach action; the evaluator reports `Attachment is not the contract: []`. *Step exhaustion on synthesis*: `MattermostResourceConflictResolutionTask` spends all 50 steps cross-referencing requests in the calendar UI and never reaches the email phase. These tasks need the agent to read 10+ messages, form a decision, and produce structured output — the working-memory load is high and the 50-step budget is unforgiving.

**PDF / paper reading — search-and-scroll loops; finds references but not table cells.** All three `ReadQwen3Paper` tasks hit step 50 with `could not parse answer as number`. The model finds *mentions* of "AIME25" in body text but never navigates to the table that contains the numeric value, oscillating between the in-viewer search and scroll attempts. The bottleneck is PDF navigation in a mobile viewer — locating Table 13 from a search hit two pages above — not visual hallucination.

**Archive workflows — date-range filtering over a long file list eats the step budget before the zip+email finale.** `SendZipFilesAskUserTask1` (compress files modified in the past 3 months, email them) burns all 50 steps scrolling Files trying to determine which entries fall inside the date window. Zip creation and attachment never happen. The task is two simple operations gated on one tedious filtering step the agent cannot delegate to a query.

→ [The 51 tasks where both Opus 4.6 and 4.7 still fail](https://tongyi-mai.github.io/MobileWorld/arena?modelA=Claude-Opus-4.6&modelB=Claude-Opus-4.7&filter=ff)

## 5. Limitations

*   **Single snapshot.** Trajectories were collected once each on the dates listed in §1. Both vendors may have shipped further changes since.
    
*   **Task evaluator sensitivity.** Pass rates depend on a harness task evaluator that uses keyword and structural matching for several tasks. The over-precise interpretation regressions in §2 are partly a property of the evaluator, not just the new models.
    
*   **K2.5 rerun.** The K2.5 trajectories used here are from a 1-image rerun (the original 3-image logs were lost). They score 46.6% overall vs the official leaderboard's 49.6% GUI-Only / 51.2% Interaction at 3 images. The K2.5 → K2.6 deltas in this post therefore slightly overstate the true upgrade gain.
    
*   **Opus 4.6 incomplete coverage.** API rate limits left a small number of tasks without final results in the 4.6 run, leaving 157 graded tasks versus 4.7's 158. The 154-task intersection used for the confusion matrix already excludes those.
    
*   **Per-task stochasticity.** Individual outcomes can shift run-to-run; the patterns above are each drawn from clusters of three or more supporting tasks.