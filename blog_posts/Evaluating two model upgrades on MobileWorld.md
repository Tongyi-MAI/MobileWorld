# Evaluating two model upgrades on MobileWorld

We ran two recent model upgrades — Anthropic's Opus 4.6 → 4.7 and Moonshot's Kimi K2.5 → K2.6 — through MobileWorld, our 161-task benchmark for mobile GUI agents driving an Android phone through real apps. This post summarizes what changed in each upgrade. Our focus is narrow: tasks performed on a phone, with the model issuing taps, drags, and (where applicable) calls to `ask_user`. We make no claims about coding, dialogue, or other domains.

## TL;DR

*   Opus 4.7 outperforms 4.6 by **+15.5pp** (42.7% → 58.2%); Kimi K2.6 outperforms K2.5 by **+9.3pp** (46.6% → 55.9%). Both improvements are large for a point-release.
    
*   The single largest source of improvement in both upgrades is **loop-breaking** — recognizing that an action produced no observable change and switching strategy. It accounts for 44% of Opus's new wins and 59% of Kimi's.
    
*   Opus 4.7's biggest jump is on **Agent–User Interaction** tasks (+25pp). 4.6 was meaningfully worse on these than on GUI-Only tasks; 4.7 closes that gap entirely.
    
*   Both upgrades show a small but distinct new failure mode: the new model is **more interpretive than the grader**, losing on tasks where the old behavior was loose enough to pass (4.7 preserving file extensions; K2.6 excluding pajamas from "short-sleeve T-shirts").
    
*   51 of the 154 intersection tasks fail in both 4.6 and 4.7; the same task clusters fail for Kimi. Mastodon advanced UIs, Mattermost decision workflows, PDF reading, and archive operations remain unsolved across both vendors.
    

## 1. Headline results

| Pair | Prior | Latest | Δ |
| --- | --- | --- | --- |
| Opus 4.6 → 4.7 | 67/157 = 42.7% | 92/158 = 58.2% | +15.5pp |
| Kimi K2.5 → K2.6 | 75/161 = 46.6% | 90/161 = 55.9% | +9.3pp |

On the 154-task intersection where both Opus runs finished, 4.7 wins 36 tasks that 4.6 lost, regresses on 11, and holds 107 (56 both pass, 51 both fail). Net +25. K2.6 has a similar shape: 27 new wins, 12 regressions, 122 unchanged. We note some cases among the full 161 were not completed due to consistent API errors (see §6).

MobileWorld tasks come in two flavors: **GUI-Only**, where the agent operates the phone autonomously, and **Agent–User Interaction**, where the task is intentionally underspecified and the agent must call `ask_user` for clarifications.

### Setup

All four runs used the `general_e2e` agent prompt with a 50-step task budget. Run dates and history-image counts:

| Run | Date | History images |
| --- | --- | --- |
| Opus 4.6 | 2026-02-05 | 1 |
| Opus 4.7 | 2026-04-22 | 1 |
| K2.5 (1-image rerun) | 2026-01-31 | 1 |
| K2.6 | 2026-04-22 | 3 |

Caveats on the K2.5 rerun and Opus 4.6 coverage are in §6.

## 2. Opus 4.6 → 4.7

We grouped the changes into three categories: wins where 4.6 had a recurring failure mode that 4.7 closes; patterns prominent enough in 4.6 that we noted them as their own categories during review (and that 4.7 no longer exhibits); and regressions, mostly clustered around 4.7 being more interpretive than 4.6.

| Direction | Pattern | Freq | What 4.6 did | What 4.7 did | Featured replay | Other examples |
| --- | --- | --- | --- | --- | --- | --- |
| Win | Loop-breaking on stalled progress | 16 / 36 | Repeats the same action when nothing changes — clicks the same dead label, scrolls the same list | Detects no-progress, escalates action _type_ (click→drag, scroll→long-press) | [`AdjustBrightnessMaximumTask`](https://tongyi-mai.github.io/MobileWorld/arena?modelA=Claude-Opus-4.6&modelB=Claude-Opus-4.7&task=AdjustBrightnessMaximumTask&filter=fp&step=5) — 50 → 7 steps | `CountFileLinesTask`, `MastodonRemoveBookmarkTask`, `MastodonRevisePollTask` |
| Win | Ask-user integration | 7 / 36 | Terminates with "no email found" when key information is missing | Calls `ask_user`, gets the answer, proceeds | [`SearchTopInfoAskUserTask`](https://tongyi-mai.github.io/MobileWorld/arena?modelA=Claude-Opus-4.6&modelB=Claude-Opus-4.7&task=SearchTopInfoAskUserTask&filter=fp) — 4 → 19 steps | `CheckMealEventAskUserTask`, `DeleteItemsAskUserTask`, `SayHelloRoommatesAskUserTask2` |
| Win | Multi-app workflow completion | 5 / 36 | Loses state crossing email → calendar → SMS boundaries | Maintains task context across apps | [`CheckMealEventAskUserTask`](https://tongyi-mai.github.io/MobileWorld/arena?modelA=Claude-Opus-4.6&modelB=Claude-Opus-4.7&task=CheckMealEventAskUserTask&filter=fp) — 50 → 43 steps | `SendInvoiceWithInfoTask`, `ScheduleLunchViaSmsTask` |
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

## 3. Kimi K2.5 → K2.6

K2.6's gains are dominated by a single class of fix: K2.5 frequently repeated an action when the resulting observation didn't change. K2.6 detects stalled progress and pivots.

| Direction | Pattern | Freq | What K2.5 did | What K2.6 did | Featured replay | Other examples |
| --- | --- | --- | --- | --- | --- | --- |
| Win | Loop-breaking | 16 / 27 | Scrolls or clicks identically for 30–50 steps when actions don't move forward | Detects stalled progress and pivots, often within 5–10 steps | [`MattermostReplyToMessageTask`](https://tongyi-mai.github.io/MobileWorld/arena?modelA=Kimi-K2.5&modelB=Kimi-K2.6&task=MattermostReplyToMessageTask&filter=fp&step=5) — 50 → 18 steps | `InvoiceReceiptCopyTask`, `BidFileRenameTask`, `LocalFileManagementTask` |
| Win | Better environment knowledge | 5 / 27 | Misses app-specific patterns | Knows GitHub API endpoints, Mattermost member lists, Android "Copy to" flows | [`CheckGithubInfoTask`](https://tongyi-mai.github.io/MobileWorld/arena?modelA=Kimi-K2.5&modelB=Kimi-K2.6&task=CheckGithubInfoTask&filter=fp) | `MattermostCreateChannelTask`, `GoogleMapsAlibabaPhoneContactTask` |
| Win | Multi-app workflow completion | 4 / 27 | Burns step budget on app A, never reaches app B | Budgets steps across calendar→alarm, email→SMS, file→email | [`CheckEventAndSetAlarmAskUserTask`](https://tongyi-mai.github.io/MobileWorld/arena?modelA=Kimi-K2.5&modelB=Kimi-K2.6&task=CheckEventAndSetAlarmAskUserTask&filter=fp) | `ReplyEmailViaSmsAskUserTask`, `SendZipFilesAskUserTask1`, `DownloadSendReceiptTask` |
| Regression | Over-precise semantic interpretation | misc | Loose keyword match | Linguistically precise — excludes "短袖睡衣" (short-sleeve pajamas) from "短袖T恤" (short-sleeve T-shirts), failing the keyword-based grader | [`CartManagementTask`](https://tongyi-mai.github.io/MobileWorld/arena?modelA=Kimi-K2.5&modelB=Kimi-K2.6&task=CartManagementTask&filter=pf) | — |

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

## 4. What both upgrades still fail on

51 tasks fail in both Opus 4.6 and 4.7. The K2 figures are comparable (59 stable failures), and the clusters are consistent across both vendors:

| Cluster | What breaks |
| --- | --- |
| Mastodon advanced | Filter-language settings, multi-recipient invites, featured-hashtag management. Dense feeds with repeated UI elements. |
| Mattermost decision/triage workflows | Budget approval, customer-feedback synthesis, technical-debt triage. Multi-message thread context plus a decision policy plus a reply structure. |
| PDF / paper reading | The `ReadQwen3Papers` family. Zero models pass any of these. |
| File-system flows with archives | Zip extraction, line-summing across files, file-type detection from unfamiliar extensions. |

→ [The 51 tasks where both Opus 4.6 and 4.7 still fail](https://tongyi-mai.github.io/MobileWorld/arena?modelA=Claude-Opus-4.6&modelB=Claude-Opus-4.7&filter=ff)

## 5. Observations

**Behavioral discipline accounts for most of the headline gains.** Loop-breaking — detecting that an action produced no change and pivoting to a different one — is the largest single pattern in both upgrades, accounting for 44% of Opus's wins and 59% of Kimi's. That two independent vendors closed the same gap in the same release window suggests the limit was widely visible.

**Asking the user is its own axis.** Splitting Opus by task flavor: 4.6 scores 46.0% on GUI-Only versus 34.1% on Interaction; 4.7 closes that gap to 57.9% versus 59.1%. The largest single delta in the upgrade is on the interaction half — _when_ and _what_ to ask. We will report the two categories separately going forward.

**Both upgrades pay an "interpretive tax."** A small number of regressions arise from the new model interpreting an instruction more carefully than the grader was calibrated for: 4.7 preserving file extensions because changing them would alter file identity; K2.6 distinguishing pajamas from T-shirts in Chinese. Researchers maintaining graders should expect this category to grow as models improve.

**Kimi's wins are more concentrated; Opus's are more diversified.** K2.6's three named patterns cover 25 of 27 wins (93%); Opus 4.7's three named win-patterns cover 28 of 36 (78%). The remaining ~22% of Opus's gains are a long tail of smaller fixes — multi-constraint working memory, output-format adherence, response-termination — each individually small but collectively meaningful.

## 6. Limitations

*   **Single snapshot.** Trajectories were collected once each on the dates listed in §1. Both vendors may have shipped further changes since.
    
*   **Grader sensitivity.** Pass rates depend on a harness grader that uses keyword and structural matching for several tasks. The "interpretive tax" failures above are partly a property of the grader, not just the new models.
    
*   **K2.5 rerun.** The K2.5 trajectories used here are from a 1-image rerun (the original 3-image logs were lost). They score 46.6% overall vs the official leaderboard's 49.6% GUI-Only / 51.2% Interaction at 3 images. The K2.5 → K2.6 deltas in this post therefore slightly overstate the true upgrade gain.
    
*   **Opus 4.6 incomplete coverage.** API rate limits left a small number of tasks without final results in the 4.6 run, leaving 157 graded tasks versus 4.7's 158. The 154-task intersection used for the confusion matrix already excludes those.
    
*   **Per-task stochasticity.** Individual outcomes can shift run-to-run; the patterns above are each drawn from clusters of three or more supporting tasks.