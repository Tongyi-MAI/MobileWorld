---
authors: Liangyu Chen, Hanzhang Zhou, Quyu Kong, Xu Zhang, Wenxuan Wang, Qin Jin, Yue Wang
---

# Why your AI Agent keeps misclicking? A Practical Guide to GUI Grounding for Frontier Models

Many major AI companies have released **demo videos where a model navigates a mobile or desktop interface with perfect precision. Reproducing those results is a different story.** We spent a lot of time testing frontier models on GUI grounding — the seemingly simple task of clicking the right pixel — and discovered that the gap between reports and deployment hides in details that nobody publishes: grounding paradigms, coordinate systems, prompt templates, thinking patterns, and tool augmentations. This post summarizes our journey and lessons learned from reproducing those details.

![GUI grounding overview](blog_posts/Why%20your%20AI%20Agent%20keeps%20misclicking/Blog.png)

---

## The Problem Nobody Talks About

In 2026, almost every major multimodal model ships with a GUI grounding score on its technical report. The vision is compelling: imagine never touching a mouse again. You say "file a reimbursement for yesterday's lunch," and an AI agent opens the portal, clicks through three dropdown menus, uploads the receipt, and hits submit — all from a single sentence. That's the promise that has made GUI grounding an important metric for every frontier multimodal model in 2026. But a metric on a spec sheet and a working agent on your desktop are very different things.

The major AI labs showcase grounding as a headline capability. Technical reports show impressive numbers. Demo videos show flawless execution. What they rarely share is *how they got there*: which grounding paradigm, coordinate system, what image resolution, whether a zoom-in tool was involved, and what the prompt actually used. **For anyone trying to build on top of these models, this opacity is the real obstacle.**

We set out to close this gap. We evaluated **Gemini-3-Pro**, **Claude-Sonnet-4.5**, **Seed1.8**, **Kimi-K2.5**, and **our** [**MAI-UI**](https://github.com/Tongyi-MAI/MAI-UI) across two challenging benchmarks:

- [**OSWorld-G (Refined)**](https://github.com/xlang-ai/OSWorld-G) — a desktop grounding benchmark with carefully written, unambiguous instructions.
- [**ScreenSpot-Pro**](https://github.com/likaixin2000/ScreenSpot-Pro-GUI-Grounding) — a high-resolution benchmark featuring dense, complex layouts that stress-test spatial precision.

Our goal was threefold:

1. **Standardize evaluation paradigms** by systematically comparing Set-of-Mark, End-to-End, and Interactive settings.
2. **Replicate reported performance** by reverse-engineering the exact configurations that make each model work.
3. **Probe the boundaries** by asking harder questions: Does reasoning help? When do tools backfire? How much latent ability are these models leaving on the table?

---

## The Evolution of Grounding Paradigms

The way models approach grounding has evolved significantly over time. Understanding this evolution is essential context for reproducing the grounding performance of the latest models.

### Set-of-Mark: Let a Parser Do the Seeing

During earlier development stages, MLLMs lacked fine-grained grounding capabilities. Consequently, researchers employed specialized, small-scale models to identify UI elements and overlay bounding boxes on the interface. In this paradigm, the MLLM functions as a reasoning engine to select the appropriate identifier based on natural language instructions.

We evaluated Claude-Sonnet-4.5, Seed1.8, and Kimi-K2.5 on the refined OSWorld-G benchmark, utilizing SoM extracted via [**OmniParser V2**](https://github.com/microsoft/OmniParser?tab=readme-ov-file). To mitigate the impact of visual noise as shown in Figure 1, we provided the original unmarked images alongside the SoM visualizations, ensuring that bounding-box overlays did not obscure critical interface details.

![SoM example](blog_posts/Why%20your%20AI%20Agent%20keeps%20misclicking/SOM.png)

**Figure 1.** A SoM example. The visual noise is heavy due to the UI element density.

As illustrated in Table 1, the **Set-of-Mark (SoM)** paradigm yields remarkably poor results across all evaluated models. Notably, every model fails to reach even a 30-point threshold in this setting. This suboptimal performance is primarily attributed to the high density of UI elements and persistent overlap issues. These factors introduce significant visual ambiguity and impede the reasoning engine's ability to accurately select identifiers within the complex interface.

**Table 1.** Grounding accuracy in the SoM setting.

| Model | OSWorld Acc. (SoM) |
| --- | --- |
| Claude-Sonnet-4.5 | 13.7 |
| Seed1.8 | 20.0 |
| Kimi-K2.5 | 18.6 |

### End-to-End (E2E): Direct Pixel-to-Coordinate Mapping

As MLLMs develop stronger internal spatial awareness, the industry has transitioned toward the End-to-End (E2E) paradigm. This approach eliminates reliance on external UI parsers by enabling the model to process raw screenshots directly and predict (x, y) coordinates.

We evaluate these models in an end-to-end setting. As shown in Table 2, two things stand out. First, models that excel on OSWorld-G may struggle badly on ScreenSpot-Pro — Claude-Sonnet-4.5 drops from 69.0 to 35.0, revealing that high-resolution displays with dense layouts are a much harder problem. Second, there's a suspicious gap between what we measured and what was reported. Gemini-3-Pro's reproduced score of 39.0 is **33 points below** its published 72.7. Seed1.8 falls 6 points short. These aren't rounding errors.

As shown in our [MAI-UI technical report](https://arxiv.org/abs/2512.22047), we found that utilizing a crop-and-zoom (Zoom-In) tool can significantly improve a model's grounding performance. This realization sent us down the path that became the most revealing part of our investigation.

**Table 2.** Overall E2E performance across benchmarks.

| Model | OSWorld-G Acc. | Report | SS-Pro Acc. | Report |
| --- | --- | --- | --- | --- |
| Gemini-3-Pro | – | – | 39.0 | [72.7](https://blog.google/products-and-platforms/products/gemini/gemini-3/#gemini-3-deep-think) |
| Claude-Sonnet-4.5 | 69.0 | – | 35.0 | [36.2](https://lf3-static.bytednsdoc.com/obj/eden-cn/lapzild-tss/ljhwZthlaukjlkulzlp/research/Seed-1.8-Modelcard.pdf) |
| Seed-1.8 | 70.2 | – | 67.0 | [73.1](https://lf3-static.bytednsdoc.com/obj/eden-cn/lapzild-tss/ljhwZthlaukjlkulzlp/research/Seed-1.8-Modelcard.pdf) |
| Kimi-K2.5 | 60.8 | – | 59.5 | – |
| MAI-UI-32B (Ours) | **73.9** | 75.0 | **67.9** | [67.9](https://arxiv.org/abs/2512.22047) |

### Inference-Phase Optimization Techniques

A popular approach in GUI grounding is utilizing inference-phase optimization techniques. This incorporates a reflection process or "Zoom-In" tools to transform grounding from a single-step execution into a multi-step interactive process. In our evaluation, we implemented a single-stage Zoom-In tool to simulate a controllable tool-call mechanism. As shown in Table 3, with zoom-in enabled, Gemini-3-Pro jumps from 39.0 to 69.7 on ScreenSpot-Pro — within 3 points of its reported 72.7. Seed1.8 goes from 67.0 to 73.3, *slightly higher than* its published number. Claude Sonnet 4.5 nearly doubles its ScreenSpot-Pro score, from 35.0 to 54.0. Our MAI-UI-32B goes from 67.9 to 73.5, exceeding 10% relative performance. The "missing" capability was there all along — it just required the right evaluation protocol to surface it.

This has a direct practical implication: on high-resolution screens, **if you're deploying these models for GUI automation without a zoom-in step, you're likely leaving significant performance on the table.**

**Table 3.** Inference-phase optimized performance and report comparison.

| Model | OSWorld-G Acc. | Report | SS-Pro Acc. | Report |
| --- | --- | --- | --- | --- |
| Gemini-3-Pro | – | – | 69.7 | [72.7](https://blog.google/products-and-platforms/products/gemini/gemini-3/#gemini-3-deep-think) |
| Claude-Sonnet-4.5 | 76.8 | – | 54.0 | [36.2](https://lf3-static.bytednsdoc.com/obj/eden-cn/lapzild-tss/ljhwZthlaukjlkulzlp/research/Seed-1.8-Modelcard.pdf) |
| Seed-1.8 | **77.0** | – | 73.3 | [73.1](https://lf3-static.bytednsdoc.com/obj/eden-cn/lapzild-tss/ljhwZthlaukjlkulzlp/research/Seed-1.8-Modelcard.pdf) |
| Kimi-K2.5 | 66.7 | – | 69.8 | – |
| MAI-UI-32B (Ours) | 75.0 | 75.0 | **73.5** | [73.5](https://arxiv.org/abs/2512.22047) |

---

## Reproducing the Numbers: A Practical Guide

One of our primary goals was to produce a transparent, reproducible recipe for each model. The details matter more than you might expect — a wrong coordinate system or resize resolution can easily cost 10+ accuracy points. Below, we document the exact configurations we used to reproduce each model's reported numbers.

### Gemini-3-Pro

- **Coordinate system:** relative (0–1000)
- **Temperature:** 0.01
- **Media resolution:** "Ultra High"
- **Zoom-in strategy:** two-stage. The model performs initial grounding, then the system crops a region centered on the prediction (¼ of the original width and height), resizes to 1920×1080, and grounds again.

```text
You are an expert UI element locator. Given a GUI image and a user's element description, provide your reasoning process first, finally provide the coordinates of the specified element as a single point. For elements with area, return the center point.

Give your reasoning process first, then output the coordinate pair ranging from 0 to 1000 exactly in format:
(x,y)
```

### Claude Sonnet 4.5

- **Coordinate system:** relative (0–1)
- **Image resize:** 1280×720 (found in [OSWorld repo](https://github.com/xlang-ai/OSWorld?tab=readme-ov-file))
- **Zoom-in strategy:** 50% crop ratio, upscaled to 1280×720

This configuration achieves over 70% on standard 1080p benchmarks. The performance drop on ScreenSpot-Pro comes from extreme downsampling — the model literally cannot see small elements after the image is shrunk to 1280×720. The zoom-in step recovers most of this lost information.

```text
You are an expert UI element locator. Given a GUI image and a user's element description, provide your reasoning process first, finally provide the coordinates of the specified element as a single (x,y) point. For elements with area, return the center point.

Output the coordinate pair exactly in format:
(x,y)
```

### Seed1.8

- **Coordinate system:** relative (0–1000)
- **Output format:** `<point>x y</point>`
- **Zoom-in strategy:** 50% crop ratio

Seed1.8 is the most robust in a pure E2E setting. Its structured output format appears well-calibrated to its training, and a simple zoom-in step pushes it to state-of-the-art levels.

```text
You are an expert UI element locator. Given a GUI image and a user's element description, provide your reasoning process first, finally provide the coordinates of the specified element as a single <point>x y<point> point. For elements with area, return the center point.

Give your reasoning process first, then output the coordinate pair ranging from 0 to 1000 exactly in format:
<point>x y<point>
```

### Kimi-K2.5

- **Coordinate system:** (0–1000)
- **Zoom-in strategy:** similar to Seed1.8

We also tested Kimi-K2.5's IPython tool-use mode, where the model can execute code for visualization and reflection. The results were unexpected, as shown in Table 4: the IPython tool currently hurts performance.

**Table 4.** Kimi-K2.5 E2E vs. IPython tool.

| Setting | OSWorld Acc. | SS-Pro Acc. |
| --- | --- | --- |
| E2E | 60.8 | 58.5 |
| IPython Tool | 56.0 | 47.2 |

Inspection of reasoning traces shows the model reflecting and visualizing, but not performing the specific crop-and-zoom operations that make interactive grounding effective.

```text
You are Kimi, a professional and meticulous expert in information collection and organization.
You fully understand user needs, skillfully use various tools, and complete tasks with the
highest efficiency.
# Task Description
After receiving users' questions, you need to fully understand their needs and think
about and plan how to complete the tasks efficiently and quickly.
# Available Tools
To help you complete tasks better and faster, I have provided you with the following tools:
1. Search tool: You can use the search engine to retrieve information, supporting multiple
queries in parallel.
2. Browser tools: You can visit web links (web pages, PDFs, etc.), get page content, and
perform interactions such as clicking, inputting, finding, and scrolling.
3. Sub Agent tools:
- 'create_subagent': Create a new sub-agent with a unique name and clear, specific
system prompt.
- 'assign_task': Delegate tasks to created sub-agents. Sub-agents can also use search
and browser tools.
4. Other tools: Including code execution (IPython, Shell).
You should locate the UI element in screenshot by user's instruction.
Finally you should give the coordinate normalized in 0-1 of the UI element in format: (x,y)
```

### MAI-UI

- **Coordinate system:** (0–1000)
- **Zoom-in strategy:** same as Seed1.8.
- **Image resize:** smart resize with 6,335,600 max pixels (4,800 image tokens)

Our MAI-UI uses a relative coordinate system. Even at 32B parameters, MAI-UI outperforms other closed models.

```text
You are a GUI grounding agent.
## Task
Given a screenshot and the user's grounding instruction. Your task is to accurately locate a UI element based on the user's instructions.
First, you should carefully examine the screenshot and analyze the user's instructions, translate the user's instruction into an effective reasoning process, and then provide the final coordinate.
## Output Format
Return a json object with a reasoning process in <grounding_think></grounding_think> tags, a [x,y] format coordinate within <answer></answer> XML tags:
<grounding_think>...</grounding_think>
<answer>
{"coordinate": [x,y]}
</answer>
## Input instruction
```

---

## Beyond the Surface: Insights in GUI Grounding

### 1. Thinking Doesn't Always Help

The intuition seems obvious: let the model reason through the problem, and it should ground more accurately. We tested this by comparing free-form reasoning against direct prediction:

**Table 5.** Free-form reasoning provides negligible benefit and sometimes hurts performance.

| Model | OSWorld-G (no thinking) | OSWorld-G (thinking) | SS-Pro (no thinking) | SS-Pro (thinking) |
| --- | --- | --- | --- | --- |
| Claude Sonnet 4.5 | 69.8 | 69.0 | 33.1 | 35.0 |
| Seed1.8 | 72.2 | 70.2 | 67.8 | 67.0 |
| Kimi-K2.5 | 64.4 | 60.8 | 59.5 | 58.5 |

Free-form reasoning hardly benefits GUI grounding. This aligns with recent findings from [UI-Ins](https://arxiv.org/pdf/2510.20286), which demonstrate that "Instruction-as-Reasoning" — using low-level, observation-focused instructions as the reasoning content — consistently outperforms free-form reasoning for GUI grounding. We show those perceptual and useful reasoning perspectives in Figure 2 (from [UI-Ins](https://arxiv.org/pdf/2510.20286)).

<p align="center"><img src="Why%20your%20AI%20Agent%20keeps%20misclicking%20A%20Practical%20Gu/image.png" width="50%" /></p>

**Figure 2.** Diverse instruction perspectives in GUI grounding.

### 2. The Zoom-In Tool Can Backfire

Zoom-in tools are powerful, but they're not free. The crop ratio and target resolution interact in ways that can quietly destroy performance, as shown in Table 6. The best config (1/4 crop, resized to 1920×1080) outperforms the worst by **11.4 points**. The mechanism becomes clear with ScreenSpot-Pro's resolution distribution in Table 7.

**Table 6.** Gemini-3-Pro on ScreenSpot-Pro with different zoom-in configurations.

| Crop Ratio | Zoom-In Resolution | SS-Pro Acc. |
| --- | --- | --- |
| 1/2 | 1920×1080 | 58.3 |
| 1/4 | 1920×1080 | **69.7** |
| 1/4 | Original image size | 64.5 |

**Table 7.** ScreenSpot-Pro contains wildly varied resolutions, including concatenated multi-monitor screenshots.

| Resolution | % of Dataset | Resolution | % of Dataset |
| --- | --- | --- | --- |
| 2560×1440 | 32.5% | 5120×1440 | 3.9% |
| 3840×2160 | 17.1% | 3456×2160 | 3.2% |
| 3840×1080 | 11.5% | 2560×1664 | 3.0% |
| 3456×2234 | 10.2% | 1920×1080 | 1.2% |
| 2160×1440 | 6.3% | 6016×3384 | 0.7% |
| 2880×1800 | 5.2% | 2992×1870 | 0.5% |
| 5120×2880 | 4.4% | 2560×1600 | 0.4% |

A resolution like 5120×1440 typically represents two 2560×1440 monitors stitched side by side. Cropping a region from this panoramic image and naively upscaling it to the original image resolution warps the aspect ratio of every UI element inside the crop. Buttons become stretched. Text becomes distorted. The model's spatial priors, trained on standard aspect ratios, are violated. A too-aggressive crop ratio (1/2) also captures too large a region to provide meaningful magnification. Furthermore, zoom-in tools are less effective in low-resolution scenarios: they over-magnify already low-resolution images, which amplifies visual noise and makes UI element sizes look unrealistic. This iterative process also introduces significant latency — a dual-stage grounding pass often requires 2.0× more inference time than a standard end-to-end evaluation. Those findings told us: the zoom-in tool isn't a free lunch — it needs to be tuned for different scenarios.

### 3. Models Have Latent Potential They Aren't Using

Our final experiment was the most intriguing. We tested two test-time scaling strategies:

- **Pass@k.** Take the best of *k* independent attempts.
- [**GUI-RCPO**](https://arxiv.org/abs/2508.05615). Generate *k* predictions, construct a 50×50 pixel bounding box around each, and compute the intersection center as the final answer.

**Table 8.** Test-time scaling reveals significant latent grounding ability. RCPO consistently outperforms Pass@k.

| Model | OSW Pass@1 | OSW Pass@4 | OSW RCPO | SSP Pass@1 | SSP Pass@4 | SSP RCPO |
| --- | --- | --- | --- | --- | --- | --- |
| Claude Sonnet 4.5 | 69.0 | 69.3 | 69.4 | 35.0 | 36.1 | 37.2 |
| Seed1.8 | 70.2 | 75.2 | 74.9 | 67.0 | 72.7 | **76.6** |
| Kimi-K2.5 | 60.8 | 69.0 | 69.9 | 58.5 | 64.0 | 69.5 |

Kimi-K2.5 jumps from 60.8 to 69.9 on OSWorld-G with RCPO — a **15% relative improvement** just from aggregating multiple predictions. Seed1.8 reaches 76.6 on ScreenSpot-Pro, nearly 10 points above its Pass@1 baseline. Crucially, RCPO consistently outperforms the Pass@k oracle on the harder benchmark, suggesting that ensemble aggregation does more than just pick the best guess — it actively corrects spatial errors.

This tells us something important: the models *know* where the element is, in a distributional sense. Their individual predictions are noisy, but that noise is roughly centered on the correct answer. By aggregating multiple spatial hypotheses, RCPO filters out stochastic variance and converges on the true location. The capability is latent. The challenge is extracting it efficiently.

---

## What This Means

We started with a simple question: why do AI agents misclick? The answer turned out to be less about fundamental model limitations and more about the invisible scaffolding surrounding evaluation.

**The black box is the real bottleneck.** The largest performance gaps we found weren't between models — they were between disclosed and undisclosed evaluation protocols. A model can appear 33 points worse simply because you used the wrong coordinate system or skipped a zoom-in step. For anyone trying to build on top of these models, understanding these implementation details isn't optional — it's a prerequisite.

**Paradigms matter more than model size.** The shift from Set-of-Mark to End-to-End to inference-phase optimization is the most consequential axis of improvement we observed. Native pixel-to-coordinate mapping now decisively outperforms SoM approaches, and adding a well-configured zoom-in step can nearly double accuracy on high-resolution displays.

**Reasoning needs direction, not freedom.** Free-form reasoning doesn't improve GUI grounding. Structured, observation-focused reasoning does. This is a practical insight for anyone designing agent prompts today.

**The precision–efficiency tradeoff is the next frontier.** Zoom-in tools and test-time scaling demonstrate that models possess far more grounding ability than single-shot evaluation reveals. But every additional inference step adds latency and cost. Given enough compute, these models can achieve very high accuracy even on highly complex tasks; the question for the rest of 2026 is not just how to push the upper bound higher, but how to get there in a single step.

## Citation

If you find this blog useful for your research, please consider citing:

```bibtex
@misc{why_your_ai_agent_keeps_misclicking,
  author       = {Liangyu Chen and Hanzhang Zhou and Quyu Kong and Xu Zhang and Wenxuan Wang and Qin Jin and Yue Wang},
  title        = {{Why your AI Agent keeps misclicking? A Practical Grounding Guide for Frontier Models}},
  year         = {2026},
  howpublished = {Blog Post},
  url          = {https://tongyi-mai.github.io/MobileWorld/blog_post.html?post=Why%20your%20AI%20Agent%20keeps%20misclicking},
}
```
