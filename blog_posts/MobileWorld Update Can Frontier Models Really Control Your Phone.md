---
authors: Quyu Kong, Xu Zhang, Hanzhang Zhou, Liangyu Chen, Yue Wang
---

# MobileWorld Update: Can Frontier Models Really Control Your Phone? Evaluating End-to-End Mobile-Use on Real Devices

*TL;DR: We adapted mainstream end-to-end models — **Gemini 3 Pro**, **Claude Sonnet 4.5**, **Kimi K2.5**, **Qwen-3.5**, and **Seed-2.0-Pro** — and benchmarked their mobile-use capabilities, analyzed current task performance on MobileWorld, and demonstrated how these models actually work on real phones.*

![MobileWorld banner](blog_posts/MobileWorld%20Update%20Can%20Frontier%20Models%20Really%20Control%20Your%20Phone/mobileworld_banner_v8.jpg)

---

It's been a few months since we released [MobileWorld](https://github.com/Tongyi-MAI/MobileWorld), our benchmark for evaluating mobile agents on realistic, long-horizon tasks. Back then, we only evaluated models through agentic frameworks — pairing a reasoning LLM with a separate grounding model. But many frontier models have since shipped built-in GUI grounding capabilities, and the natural question is: **can they handle mobile tasks end-to-end, without any external grounding module?**

We spent the last few weeks finding out, and this post shares everything we learned. We'll walk through how we adapted five frontier models for direct end-to-end evaluation by understanding their coordinate systems, action formats, and multi-turn structures — none of which is well-documented. We'll show which model came out on top, what it actually costs to run them, and how choices like the number of history screenshots can make or break performance in ways that differ across models. Most importantly, we'll demonstrate these models working on real physical phones and show you how to set this up yourself in just 6 steps.

But first — here's what it actually looks like.

## See It in Action: Frontier Models Controlling Real Phones

We got Gemini and Claude running on actual physical devices, not just emulators. Watch them navigate complex, multi-step tasks end-to-end:

- **[Claude on Xiaohongshu](https://player.bilibili.com/player.html?isOutside=true&aid=116247953935314&bvid=BV1SswYzwEP7&cid=36780507493&p=1)** — *帮我去小红书整理下我关注的 WebAgentLab 转发的 5 篇最近的论文 title，整理给我* (Please go to Xiaohongshu and collect the titles of the 5 most recent papers reposted by the account WebAgentLab that I follow.)
- **[Gemini on X / Twitter](https://player.bilibili.com/player.html?isOutside=true&aid=116247886825035&bvid=BV128wYzZEt5&cid=36780049107&p=1)** — Go to X and navigate to Elon Musk's profile page. Find his 5 most recent tweets and provide a summary of their main topics and content.

Now let's dig into how we got here.

---

## The Challenge: Making Frontier Models Work as Mobile Agents End-to-End

If you've tried to use GPT-5, Gemini 3 Pro, or Claude Sonnet 4.5 as GUI agents, you'll know it's not as simple as just sending screenshots and asking for actions. A comprehensive review of the leaderboards for [AndroidWorld](https://docs.google.com/spreadsheets/d/1cchzP9dlTZ3WXQTfYNhh3avxoLipqHN75v1Tb86uhHo/edit?gid=0#gid=0) reveals that the majority of existing research focuses on constructing agent frameworks based on general-purpose models (e.g., [AutoDevice](https://autodevice.io/benchmark/) using Gemini-3-Pro, [DroidRun](https://github.com/droidrun/droidrun) using GPT-5). The end-to-end execution capabilities of these models for mobile GUI tasks have been significantly overlooked. Each model has its own quirks around coordinate systems, action formats, and multi-turn conversation structures.

**Grounding capabilities.** One of the first hurdles is *grounding* — getting models to output precise screen coordinates for taps and gestures. Different models handle this differently:

| Model | Coordinate System | Notes |
| --- | --- | --- |
| Gemini 3 Pro | Relative (0–1000) | Uses normalized coordinates |
| Seed-2.0-Pro | Relative (0–1000) | Native `<point>x y</point>` format |
| Qwen-3.5 | Relative (0–1000) | Normalized coordinates |
| Kimi K2.5 | Relative (0–1) | Float coordinates |
| Claude Sonnet 4.5 | Absolute pixels | Requires image resize to 1280×720 |
| GPT-5 | — | Relatively weak grounding capabilities; not evaluated |

*(For a deeper dive into grounding evaluation, see our companion [grounding benchmark blog post](blog_post.html?post=Why%20your%20AI%20Agent%20keeps%20misclicking).)*

**System prompts and multi-turn organization.** We took two approaches to prompting:

- **[General End-to-End Prompt](https://github.com/Tongyi-MAI/MobileWorld/blob/8e65ed01bd770a8dd893347e6ee82e9f7741b7aa/src/mobile_world/agents/utils/prompts.py#L206).** Building on our MobileWorld evaluation, we distilled a highly adaptable, general end-to-end prompt for direct coordinate output. Designed to maximize compatibility across a diverse spectrum of general-purpose LLMs, this framework establishes a fair and unified benchmark for rigorously evaluating models' instruction-following and GUI-operation capabilities. Key design decisions:
    - **Structured action space.** A comprehensive set of actions (`click`, `long_press`, `drag`, `scroll`, `input_text`, etc.) with explicit JSON schemas that include coordinate parameters.
    - **Normalized coordinates.** Actions like `click` expect `{"action_type": "click", "coordinate": [x, y]}` where coordinates are normalized to a configurable scale factor (0–1000 for Gemini, absolute pixels for Claude).
    - **Thought–Action format.** Each response follows a `Thought: ... Action: {...}` structure, making it easy to parse and debug agent reasoning.
    - **User interaction support.** We include `ask_user` and `answer` actions to handle MobileWorld's user-interaction tasks.
- **[Model-Specific Adaptation](https://github.com/Tongyi-MAI/MobileWorld/blob/8e65ed01bd770a8dd893347e6ee82e9f7741b7aa/src/mobile_world/agents/utils/prompts.py#L294).** For Seed-2.0-Pro, we adapted the [`seed_agent.py`](https://github.com/xlang-ai/OSWorld/blob/main/mm_agents/seed_agent.py) prompt from the OSWorld repository to better match its expected input format.

## Results: What Actually Works?

### Overall Performance

| Model | GUI-Only | Ask User |
| --- | --- | --- |
| Seed-2.0-Pro | **63.2** | **61.4** |
| Gemini 3 Pro | 51.3 | 29.5 |
| Kimi K2.5 | 49.6 | 51.2 |
| Claude Sonnet 4.5 | 47.8 | 38.6 |
| Qwen3.5-397B-A17B | 42.7 | 54.4 |

The overall results reveal a clear tier structure. Seed-2.0-Pro leads convincingly on GUI-Only tasks at 63.2% and maintains strong performance on user-interaction tasks at 61.4%, making it the most well-rounded end-to-end model we tested. Gemini 3 Pro and Kimi K2.5 form a competitive middle tier on GUI-Only tasks (51.3% and 49.6% respectively), but diverge sharply on user interaction: Kimi holds up at 51.2% while Gemini drops to 29.5%, suggesting Gemini struggles with the back-and-forth dialogue required when agents need to ask users for clarification. Claude Sonnet 4.5 sits at 47.8% on GUI-Only with moderate user-interaction performance at 38.6%. Qwen3.5-397B-A17B presents an interesting inversion: it scores the lowest on GUI-Only at 42.7% but jumps to 54.4% on user interaction — the second-best score in that category — indicating strong conversational reasoning despite weaker visual grounding. Overall, GUI grounding and user-interaction handling are largely independent capabilities. Excelling at one does not guarantee the other, and the best mobile agent needs both.

### General vs. Specialized Prompts

| Model | Prompt | GUI-Only | Ask User |
| --- | --- | --- | --- |
| Seed-2.0-Pro | General E2E | 45.7% | 59.5% |
| Seed-2.0-Pro | seed_agent | **63.2%** | **61.4%** |

For Seed-2.0-Pro, the specialized `seed_agent` prompt significantly outperforms the general end-to-end prompt on GUI-Only tasks (63.2% vs. 45.7%), but the gap nearly vanishes on user interaction (61.4% vs. 59.5%). This suggests that prompt tailoring matters most for GUI grounding, where precise alignment with the model's coordinate conventions directly affects execution accuracy, while conversational tasks are less sensitive to prompt format.

### How Many History Images Should You Include?

This one surprised us. The optimal number of historical screenshots varies significantly by model:

| Model | History Images | GUI-Only | Ask User |
| --- | --- | --- | --- |
| **Gemini 3 Pro** | 3 | 51.3% | 29.5% |
|  | 2 | **53.0%** | 25.0% |
|  | 1 | 48.7% | 27.3% |
| **Claude Sonnet 4.5** | 3 | **47.0%** | 38.6% |
|  | 2 | 41.0% | 40.9% |
|  | 1 | 41.0% | **45.5%** |

Gemini performs best with 2 history images on GUI-Only tasks, while Claude shows interesting behavior on user-interaction tasks where fewer images actually help. This likely reflects differences in how each model handles context and visual reasoning.

### The Cost: Which Model Gives You the Best Bang for Your Buck?

Running 161 tasks across different models, here's what the bills looked like:

| Model | Tasks (GUI-Only and User-Int) | Prompt Tokens | Completion Tokens | Total Cost |
| --- | --- | --- | --- | --- |
| Claude Sonnet 4.5 | 161 | 33.8M | 531K | **$109.45** |
| Gemini 3 Pro E2E | 161 | 23.7M | 271K | **$50.57** |
| MAI-UI-235B | 161 | 48.5M | 319K | **$14.42** |

The difference is stark. Claude costs roughly 2× what Gemini costs, and Gemini costs 3.5× what MAI-UI-235B costs. If you're optimizing for cost-effectiveness, the open-weight MAI-UI model is looking very attractive — especially when you consider it's essentially **$0 if you're running on your own hardware**.

### Agentic Framework vs. End-to-End

One of the key questions we wanted to answer: **do you actually need a separate grounding model, or can frontier models handle everything end-to-end?** The leaderboard tells an interesting story:

- **End-to-end models now take the crown.** Seed-2.0-Pro tops the leaderboard at 62.7% overall, surpassing the best agentic framework GPT-5 + UI-Ins-7B (56.2%). Compared to its predecessor Seed-1.8 (45.9%), this represents a major leap, especially on user-interaction tasks (29.5% → 61.4%). The best general-purpose LLMs no longer need a separate grounding module.
- **Agentic approaches still have a niche.** GPT-5 + UI-Ins-7B remains competitive, and Gemini-3-Pro scores higher on GUI-Only in its agentic setup (55.6%) than end-to-end (51.3%), suggesting a dedicated grounding model can still help when native grounding is weaker.
- **The bottleneck has shifted.** User interaction used to be the clear weakness of end-to-end models. Not anymore. Seed-2.0-Pro (61.4%), GUI-Owl-1.5-32B (56.1%), and Qwen3.5 (54.4%) all handle it well, while the agentic Gemini-3-Pro + UI-Ins-7B collapses to 24.4%. What matters now is the model's own conversational reasoning, not whether it uses an agentic framework.

## Turn a Frontier LLM into Your Phone's GUI Agent in 6 Steps

**1. Download and install ADB on your local machine.** Download the official [ADB package](https://developer.android.com/tools/releases/platform-tools?hl=zh-cn) and extract it to a custom directory. Configure your environment variables:

```bash
# macOS — assuming the extracted directory is ~/Downloads/platform-tools
export PATH=${PATH}:~/Downloads/platform-tools
```

For Windows, refer to [third-party tutorials](https://blog.csdn.net/x2584179909/article/details/108319973) for configuration steps.

**2. Connect your Android phone via USB and enable USB debugging.**

- *Enable Developer Mode.* Go to Settings → About Phone → Build Number and tap rapidly about 10 times until a "Developer mode has been enabled" pop-up appears. Steps may vary slightly by device.
- *Enable USB Debugging.* In Settings → Developer Options → USB Debugging, check the box. Some devices may require a restart.
- *Verify the connection.*

```bash
# Check connected devices
adb devices

# The output should display your device, e.g.:
# List of devices attached
# emulator-5554   device
```

**3. Install ADB Keyboard (for text input).** Download the [APK](https://github.com/senzhk/ADBKeyBoard/blob/master/ADBKeyboard.apk) and install it on the device. After installation, enable ADB Keyboard in Settings → Input Methods (or run `adb shell ime enable com.android.adbkeyboard/.AdbIME`). This step is **optional** — MobileWorld will install it automatically.

**4. Clone the latest MobileWorld code.**

```bash
git clone https://github.com/Tongyi-MAI/MobileWorld.git
```

**5. Start the MobileWorld server.**

```bash
uv run mobile-world server
```

**6. Execute commands** (tasks can be modified accordingly). Using Qwen3.5 hosted on Dashscope as an example:

```bash
uv run mw test "set an alarm at 8:00 am" \
  --agent-type general_e2e \
  --model_name qwen3.5-plus \
  --llm_base_url https://dashscope.aliyuncs.com/compatible-mode/v1 \
  --aw-host http://127.0.0.1:6800 \
  --api_key xxx
```

---

*If you want to try MobileWorld yourself, check out our [GitHub repository](https://github.com/Tongyi-MAI/MobileWorld). We'd love to see what you find. Have questions or interesting results with other models? Open an issue or reach out on Twitter/X.*

If you find MobileWorld useful in your research, please cite our paper:

```bibtex
@inproceedings{kong2025mobileworld,
  title={MobileWorld: Benchmarking Autonomous Mobile Agents in Agent-User Interactive, and MCP-Augmented Environments},
  author={Quyu Kong and Xu Zhang and Zhenyu Yang and Nolan Gao and Chen Liu and Panrong Tong and Chenglin Cai and Hanzhang Zhou and Jianan Zhang and Liangyu Chen and Zhidan Liu and Steven Hoi and Yue Wang},
  booktitle={Proceedings of the 64th Annual Meeting of the Association for Computational Linguistics (ACL)},
  year={2026},
  url={https://arxiv.org/abs/2512.19432},
}
```
