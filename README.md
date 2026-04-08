<p align="center">
  <img src="./assets/mw_title_v1.png" alt="Banner">
</p>


<p align="center">
  <a href="https://tongyi-mai.github.io/MobileWorld/#leaderboard">Leaderboard</a> •
  <a href="https://tongyi-mai.github.io/MobileWorld/">Website</a> •
  <a href="https://arxiv.org/abs/2512.19432">Paper</a> •
  <a href="https://github.com/Tongyi-MAI/MobileWorld/tree/main/docs">Docs</a> •
  <a href="https://github.com/Tongyi-MAI/MobileWorld/issues">Issues</a>
</p>

<p align="center">
    <a href="https://img.shields.io/badge/PRs-Welcome-red">
        <img src="https://img.shields.io/badge/PRs-Welcome-red">
    </a>
    <a href="https://img.shields.io/github/last-commit/Tongyi-MAI/MobileWorld?color=green">
        <img src="https://img.shields.io/github/last-commit/Tongyi-MAI/MobileWorld?color=green">
    </a>
    <a href="https://opensource.org/licenses/Apache-2.0">
        <img src="https://img.shields.io/badge/License-Apache%202.0-blue.svg">
    </a>
    <a href="https://img.shields.io/badge/Python-3.12-blue.svg">
        <img src="https://img.shields.io/badge/Python-3.12-blue.svg">
    </a>

</p>


While maintaining the same level of rigorous, reproducible evaluation as AndroidWorld, **MobileWorld** offers a more challenging online mobile-use benchmark by introducing four additional features that better capture real-world agent behavior.

- 🎯 **Broad Real-World Coverage**: 201 carefully curated tasks across 20 mobile applications
- 🔄 **Long-Horizon Tasks**: Multi-step reasoning and cross-app workflows
- 👥 **Agent-User Interaction**: Novel tasks requiring dynamic human-agent collaboration
- 🔧 **MCP-Augmented Tasks**: Support Model Context Protocol (MCP) to evaluate hybrid tool usage

<p align="center">
  <img src="./assets/compare_to_aw_v1.png" alt="Comparison to AndroidWorld" width="800">
  <br>
  <em>Difficulty comparison between MobileWorld and AndroidWorld</em>
</p>

## 📢 Updates
- **2026-04-08: AndroidWorld Integration (Experimental) 🧪**
    MobileWorld now supports evaluating [AndroidWorld](https://github.com/google-research/android_world) tasks alongside its own benchmark suite, sharing a **unified AVD** (Pixel 8 / API 34) so you can switch between suites without restarting the emulator.
    * 🧩 **Unified AVD:** both suites run on the same `Pixel_8_API_34_x86_64` image; no second emulator is installed, keeping the container slim (~22 GB).
    * 📦 **New image tag:** `ghcr.io/tongyi-mai/mobile_world:plus-aw-latest` ships with all 24 AndroidWorld apps pre-installed and the `aw_init_state` snapshot baked in.
    * ⚙️ **Evaluation parity:** uses the official AndroidWorld `TaskEval` code (via the `resources/android_world/` submodule) with a MobileWorld adapter layer; includes fixes for a few upstream evaluator bugs and swiftshader-GPU compatibility patches.
    * ♿ **A11y gRPC support:** UI state is read through Google's AccessibilityForwarder (same mechanism as official AndroidWorld), so tasks like `ClockStopWatchRunning` that rely on animating screens work reliably.
    * 🚧 **Experimental:** Results may differ from the official AndroidWorld numbers due to the API 33 → 34 upgrade and GPU backend differences. See [docs/android_world_integration.md](docs/android_world_integration.md) for the full integration notes, known issues, and parity caveats.
    * **Quick start:**
        ```bash
        # Launch AndroidWorld-enabled containers
        uv run mw env run --count 5 --prefix aw_test \
            --image ghcr.io/tongyi-mai/mobile_world:plus-aw-latest

        # Run all 91 AndroidWorld tasks
        uv run mw eval \
            --agent_type seed_agent \
            --tasks ALL \
            --suite-family android_world \
            --seed 42 \
            --max_round 50 \
            --model_name <your_model> \
            --llm_base_url <openai_compatible_url> \
            --env-prefix aw_test \
            --env-image ghcr.io/tongyi-mai/mobile_world:plus-aw-latest \
            --max-concurrency 5 \
            --log_file_root traj_logs/aw_run
        ```
        The `--suite-family android_world` flag selects the AndroidWorld suite; `--seed 42` pins the per-task random parameters for reproducibility. Specific tasks can be selected with `--tasks MarkorCreateNote,SimpleSmsSend,...`.
- **2026-03-20: End-to-End Frontier Model Evaluation & Real Device Support🔥**
    We benchmarked five frontier models — **Seed-2.0-Pro**, **Gemini 3 Pro**, **KIMI K2.5**, **Claude Sonnet 4.5**, and **Qwen-3.5** — for end-to-end mobile-use, and demonstrated real-phone execution. See our [blog post](https://tongyi-mai.github.io/MAI-UI-blog/MobileWorld-Blog-Post) for the full write-up.
    * 🏆 **New SOTA:** **Seed-2.0-Pro** leads at **63.2%** GUI-Only and **61.4%** User-Interaction, overtaking Seed-1.8 as the top end-to-end model.
    * 📊 **Expanded Leaderboard:**
        * **KIMI K2.5** (49.6% GUI-Only, 51.2% User-Int)
        * **Qwen-3.5-397B-A17B** (42.7% GUI-Only, 54.4% User-Int)
        * **GUI-Owl-1.5-32B** (43.9% GUI-Only, 56.1% User-Int)
        * **UI-Venus-1.5-30B** (17.1% GUI-Only)
    * 📱 **Real Device Support:** You can now run frontier models on physical Android phones. See the [Testing on Real Devices](#-testing-on-real-devices) section.
    * **New Agents:** `gui_owl_1_5` ([code](src/mobile_world/agents/implementations/gui_owl_1_5.py)), `ui_venus_agent` ([code](src/mobile_world/agents/implementations/ui_venus_agent.py))
- **2026-01-16: Expanded Model Evaluation Support🔥**
    We have introduced evaluation implementations for the latest frontier models, covering both end-to-end and agentic workflows.
    * 🚀 **Leaderboard Upgrade with Multi-Dimensional Filtering:** We now support focused comparisons within **GUI-Only** and **User-Interaction** categories. This allows for a more balanced assessment of core navigation capabilities, especially for models not yet optimized for MCP-hybrid tool calls or complex user dialogues.
    * 🏆 **New Performance Records:**
        * **GUI-Only Tasks:** **Seed-1.8** secured the Top-1 spot for end-to-end performance with a **52.1%** success rate, followed by **Gemini-3-Pro** (**51.3%**) and **Claude-4.5-Sonnet** (**47.8%**).
        * **Combined GUI & User Interaction:** **MAI-UI-235B-A22B** leads the leaderboard with a **45.4%** success rate, surpassing **Claude-4.5-Sonnet** (**43.2%**) and **Seed-1.8** (**40.8%**).    
    * **Supported Models:**
        * **End-to-End:**  MAI-UI, Gemini-3-Pro, Claude-4.5-sonnet, Seed-1.8, and GELab-Zero.
        * **Agentic:** Gemini-3-Pro, Claude-4.5-sonnet, and GPT-5.
    * **Implementation Details:**
        * [**MAI-UI**](https://tongyi-mai.github.io/MAI-UI/) ([code](src/mobile_world/agents/implementations/mai_ui_agent.py))
        * [**Gemini-3-Pro**](https://deepmind.google/models/gemini/pro/): End-to-end version adapted from our agentic framework utilizing Gemini’s built-in grounding ([code](src/mobile_world/agents/implementations/general_e2e_agent.py)).
        * [**Seed-1.8**](https://seed.bytedance.com/en/seed1_8): Adapted from [OSWorld](https://github.com/xlang-ai/OSWorld/blob/main/mm_agents/seed_agent.py) for mobile action spaces, as GUI capability is not yet officially supported ([code](src/mobile_world/agents/implementations/seed_agent.py)).
        * [**GELab-Zero**](https://arxiv.org/abs/2512.15431) ([code](src/mobile_world/agents/implementations/gelab_agent.py)).
    * **Note on GPT-5:** While supported for agentic tasks, **GPT-5** is currently excluded from end-to-end evaluation as its grounding mechanisms remain unclear for standardized testing.
- **2025-12-29**: We released [MAI-UI](https://tongyi-mai.github.io/MAI-UI/), achieving SOTA performance with a 41.7% success rate in the end-to-end models category on the MobileWorld benchmark.
- **2025-12-23**: Initial release of MobileWorld benchmark. Check out our [paper](https://arxiv.org/abs/2512.19432) and [website](https://tongyi-mai.github.io/MobileWorld/)🔥.
- **2025-12-23**: Docker image `ghcr.io/Tongyi-MAI/mobile_world:latest` available for public use.


## 📋 Table of Contents
- [Updates](#-updates)
- [Overview](#-overview)
- [Installation](#-installation)
- [Quick Start](#-quick-start)
- [Testing on Real Devices](#-testing-on-real-devices)
- [Available Commands](#-available-commands)
- [Documentation](#-documentation)
- [Benchmark Statistics](#-benchmark-statistics)
- [Contact](#-contact)
- [Acknowledgements](#-acknowledgements)
- [Citation](#-citation)


---

## 📖 Overview

<p align="center">
  <img src="./assets/mw_overview.jpg" alt="MobileWorld Overview" width="800">
</p>

MobileWorld is a comprehensive benchmark for evaluating autonomous mobile agents in realistic scenarios. Our benchmark features a robust infrastructure and deterministic evaluation methodology:

### 🏗️ System Architecture

**Containerized Environment**  
The entire evaluation environment runs in Docker-in-Docker containers, including:
- Rooted Android Virtual Device (AVD)
- Self-hosted application backends
- API server for orchestration

This design eliminates external dependencies and enables consistent deployment across different host systems.

**Open-Source Applications**  
We build stable, reproducible environments using popular open-source projects:
- **Mattermost**: Enterprise communication (Slack alternative)
- **Mastodon**: Social media platform (X/Twitter alternative)  
- **Mall4Uni**: E-commerce platform

Self-hosting provides full backend access, enabling precise control over task initialization and deterministic verification.

**Snapshot-Based State Management**  
AVD snapshots capture complete device states, ensuring each task execution begins from identical initial conditions for reproducible results.

### ✅ Task Evaluation

We implement multiple complementary verification methods for reliable assessment:

- **Textual Answer Verification**: Pattern matching and string comparison for information retrieval tasks
- **Backend Database Verification**: Direct database queries to validate state changes (messages, posts, etc.)
- **Local Storage Inspection**: ADB-based inspection of application data (calendar events, email drafts, etc.)
- **Application Callbacks**: Custom APIs capturing intermediate states for validation

## 💾 Installation

### System Requirements

- **Docker** with privileged container support
- **KVM** (Kernel-based Virtual Machine) for Android emulator acceleration
- **Python 3.12+**
- **Linux** host system (or Windows with WSL2 + KVM enabled), MacOS support is in progress.

### Quick Install

```bash
# Clone the repository
git clone https://github.com/Tongyi-MAI/MobileWorld.git
cd MobileWorld

# Install dependencies with uv
uv sync
```

### Environment Configuration

Create a `.env` file from `.env.example` in the project root:

```bash
cp .env.example .env
```

Edit the `.env` file and configure the following parameters:

**Required for Agent Evaluation:**
- `API_KEY`: Your OpenAI-compatible API key for the agent model
- `USER_AGENT_API_KEY`: API key for user agent LLM (used in agent-user interactive tasks)
- `USER_AGENT_BASE_URL`: Base URL for user agent API endpoint
- `USER_AGENT_MODEL`: Model name for user agent (e.g., `gpt-4.1`)

**Required for MCP-Augmented Tasks:**
- `DASHSCOPE_API_KEY`: DashScope API key for MCP services
- `MODELSCOPE_API_KEY`: ModelScope API key for MCP services

**Example `.env` file:**
```bash
API_KEY=your_api_key_for_agent_model
DASHSCOPE_API_KEY=dashscope_api_key_for_mcp
MODELSCOPE_API_KEY=modelscope_api_key_for_mcp

USER_AGENT_API_KEY=your_user_agent_llm_api_key
USER_AGENT_BASE_URL=your_user_agent_base_url
USER_AGENT_MODEL=gpt-4.1
```

> **Note**: 
> - MCP API keys are only required if you plan to run MCP-augmented tasks
> - User agent settings are only required for agent-user interactive tasks
> - See [MCP Setup Guide](docs/mcp_setup.md) for detailed MCP server configuration

---

## 🚀 Quick Start

### 1. Check Environment & Pull Docker Image

```bash
sudo uv run mw env check
```

This command verifies Docker, KVM support, and prompts to pull the latest `mobile_world` Docker image if needed.

### 2. Launch Docker Containers

```bash
sudo uv run mw env run --count 5 --launch-interval 20
```

This launches 5 containerized Android environments with:
- `--count 5`: Number of parallel containers
- `--launch-interval 20`: Wait 20 seconds between container launches

### 3. Run Evaluation

```bash
sudo uv run mw eval \
    --agent_type qwen3vl \
    --task ALL \
    --max_round 50 \
    --model_name Qwen3-VL-235B-A22B \
    --llm_base_url [openai_compatible_url] \
    --step_wait_time 3 \
    --log_file_root traj_logs/qwen3_vl_logs \
    --enable_mcp \
    --enable_user_interaction
```

> **Flags:**
> - `--enable_mcp`: Include MCP-augmented tasks in evaluation
> - `--enable_user_interaction`: Include agent-user interaction tasks. Without this flag, only GUI-only tasks are evaluated.

### 4. View Results

```bash
uv run mw logs view --log_dir traj_logs/qwen3_vl_logs
```

Opens an interactive web-based visualization at `http://localhost:8760` to explore task trajectories and results.

---

## 📱 Testing on Real Devices

Beyond the containerized emulator environment, MobileWorld supports running frontier models on **real physical Android phones**. This lets you evaluate models like Gemini, Claude, Qwen, and others as true end-to-end mobile agents.

### Prerequisites

- A physical Android phone connected via USB
- ADB (Android Debug Bridge) installed on your local machine
- An API key for the model you want to test

### Step 1: Install ADB

Download the official [ADB platform-tools](https://developer.android.com/tools/releases/platform-tools) and extract it.

**macOS/Linux:**
```bash
# Assuming extracted to ~/Downloads/platform-tools
export PATH=${PATH}:~/Downloads/platform-tools
```

**Windows:** Refer to [this guide](https://blog.csdn.net/x2584179909/article/details/108319973) for configuration steps.

### Step 2: Connect Your Phone & Enable USB Debugging

1. **Enable Developer Mode:** Go to *Settings > About Phone > Build Number* and tap rapidly ~10 times until you see "Developer mode has been enabled."
2. **Enable USB Debugging:** Go to *Settings > Developer Options > USB Debugging* and enable it. Some devices may require a restart.
3. **Verify the connection:**

```bash
adb devices

# Expected output:
# List of devices attached
# <your_device_id>   device
```

### Step 3: Install ADB Keyboard (Optional)

ADB Keyboard is needed for text input. Download the [ADBKeyboard.apk](https://github.com/senzhk/ADBKeyBoard/blob/master/ADBKeyboard.apk) and install it on your device:

```bash
adb install ADBKeyboard.apk
adb shell ime enable com.android.adbkeyboard/.AdbIME
```

> **Note:** This step is optional — MobileWorld will install it automatically if not present.

### Step 4: Clone MobileWorld

```bash
git clone https://github.com/Tongyi-MAI/MobileWorld.git
cd MobileWorld
uv sync
```

### Step 5: Start the MobileWorld Server

```bash
uv run mobile-world server
```

This starts the backend API server that bridges the model and the device.

### Step 6: Run a Task on Your Real Device

```bash
uv run mw test "set an alarm at 8:00 am" \
    --agent-type general_e2e \
    --model_name anthropic/claude-sonnet-4-5 \
    --llm_base_url https://openrouter.ai/api/v1 \
    --aw-host http://127.0.0.1:6800 \
    --api_key YOUR_API_KEY
```

Replace `--model_name`, `--llm_base_url`, and `--api_key` with the model and credentials you want to use. Any OpenAI-compatible endpoint works. The `--agent-type general_e2e` prompt works across most frontier models. For Seed-2.0-Pro, use `--agent-type seed_agent` for better performance.

### Supported End-to-End Models

| Model             | Agent Type    | Coordinate System | Notes                                         |
|-------------------|---------------|-------------------|-----------------------------------------------|
| Gemini 3 Pro      | `general_e2e` | Relative (0–1000) | Normalized coordinates                        |
| Claude Sonnet 4.5 | `general_e2e` | Absolute pixels   | Requires image resize to 1280×720             |
| Qwen-3.5          | `general_e2e` | Relative (0–1000) |                                               |
| KIMI K2.5         | `general_e2e` | Relative (0–1)    |                                               |
| Seed-2.0-Pro      | `seed_agent`  | Relative (0–1000) | Best with specialized `seed_agent` agent type |

> **Tip:** You can view the live device screen at any time with `uv run mw device`.

---

## 🔧 Available Commands

MobileWorld provides a comprehensive CLI (`mw` or `mobile-world`) with the following commands:

| Command           | Description                                             |
|-------------------|---------------------------------------------------------|
| `mw env check`    | Check prerequisites (Docker, KVM) and pull latest image |
| `mw env run`      | Launch Docker container(s) with Android emulators       |
| `mw env list`     | List running MobileWorld containers                     |
| `mw env rm`       | Remove/destroy containers                               |
| `mw env info`     | Get detailed info about a container                     |
| `mw env restart`  | Restart the server in a container                       |
| `mw env exec`     | Open a shell in a container                             |
| `mw eval`         | Run benchmark evaluation suite                          |
| `mw test`         | Run a single ad-hoc task for testing                    |
| `mw info task`    | Display available tasks                                 |
| `mw info agent`   | Display available agents                                |
| `mw info app`     | Display available apps                                  |
| `mw info mcp`     | Display available MCP tools                             |
| `mw logs view`    | Launch interactive log viewer                           |
| `mw logs results` | Print results summary table                             |
| `mw logs export`  | Export logs as static HTML site                         |
| `mw device`       | View live Android device screen                         |
| `mw server`       | Start the backend API server                            |

Use `mw <command> --help` for detailed options.

---

## 📚 Documentation

For detailed documentation, see the `docs/` directory:

| Document                                                        | Description                                                        |
|-----------------------------------------------------------------|--------------------------------------------------------------------|
| [Development Guide](docs/development.md)                        | Dev mode, debugging, container management workflows                |
| [MCP Setup](docs/mcp_setup.md)                                  | Configure MCP servers for external tool integration                |
| [Windows Setup](docs/setup_for_windows.md)                      | WSL2 and KVM setup instructions for Windows                        |
| [AVD Configuration](docs/configure_avd.md)                      | Customize and save Android Virtual Device snapshots                |
| [AndroidWorld Integration](docs/android_world_integration.md)   | Run AndroidWorld tasks on the shared AVD (experimental)            |

---

## 🎯 Benchmark Statistics

<table align="center">
  <tr>
    <td><img src="./assets/scenario_distribution.jpg" alt="Scenario Distribution" width="420"></td>
    <td><img src="./assets/mw_statistics.jpg" alt="MobileWorld Statistics" width="380"></td>
  </tr>
</table>


## 📬 Contact

For questions, issues, or collaboration inquiries:

- **GitHub Issues**: [Open an issue](https://github.com/Tongyi-MAI/MobileWorld/issues)
- **Email**: Contact the maintainers
- **Discord**: [Join our Discord server](https://discord.gg/yuX6t5qs)
- **WeChat Group**: Scan to join our discussion group

<p align="center">
  <img src="site/assets/wechat_qr.png" alt="WeChat Group QR Code" width="200">
</p>


## Acknowledgements

We thank [Android World](https://github.com/google-research/android_world) and [Android-Lab](https://github.com/THUDM/Android-Lab) for their open source contributions.
We also thank all the open-source contributors!

<a href="https://github.com/Tongyi-MAI/MobileWorld/graphs/contributors">
  <img src="https://contrib.rocks/image?repo=Tongyi-MAI/MobileWorld" />
</a>


## Citation

If you find MobileWorld useful in your research, please cite our paper:

```bibtex
@misc{kong2025mobileworldbenchmarkingautonomousmobile,
      title={MobileWorld: Benchmarking Autonomous Mobile Agents in Agent-User Interactive, and MCP-Augmented Environments}, 
      author={Quyu Kong and Xu Zhang and Zhenyu Yang and Nolan Gao and Chen Liu and Panrong Tong and Chenglin Cai and Hanzhang Zhou and Jianan Zhang and Liangyu Chen and Zhidan Liu and Steven Hoi and Yue Wang},
      year={2025},
      eprint={2512.19432},
      archivePrefix={arXiv},
      primaryClass={cs.AI},
      url={https://arxiv.org/abs/2512.19432}, 
}
```

---

## ⭐ Star History

If you find MobileWorld helpful, please consider giving us a star ⭐!

[![Star History Chart](https://api.star-history.com/svg?repos=Tongyi-MAI/MobileWorld&type=Date)](https://star-history.com/#Tongyi-MAI/MobileWorld&Date)
