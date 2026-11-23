# Submit Your Results

Have a trajectory run from a new model or agent configuration? We welcome community contributions to the [leaderboard](https://tongyi-mai.github.io/MobileWorld/#leaderboard) and the [head-to-head arena](https://tongyi-mai.github.io/MobileWorld/arena).

## 1. Bundle your trajectory directory

Use [`site/bundle_trajs.py`](../site/bundle_trajs.py) to package a `traj_logs/<your_run>` directory into the format the arena expects:

```bash
# Minimal: bundle traj.json + result.txt across all tasks
uv run python site/bundle_trajs.py traj_logs/your_run \
    -o site/trajs/your-model.json.gz

# With screenshots: also produces a .mp4 of all task frames for the arena viewer
uv run python site/bundle_trajs.py traj_logs/your_run \
    -o site/trajs/your-model.json.gz \
    --with-screenshots \
    --video-base-url https://tongyi-mai.github.io/MAI-UI-blog/MobileWorld/trajs
```

## 2. Prepare your leaderboard entry

Draft a new object in the same format as the existing entries in `site/leaderboard.json`:

```json
{
  "model": "Your-Model-Name",
  "organization": "Your Org",
  "date": "2026-04-29",
  "link": "https://your-model-page.example.com",
  "category": "General",
  "model_type": "End-to-End Model",
  "max_steps": 50,
  "runs": 1,
  "gui_only": 50.0,
  "user_int": 50.0,
  "mcp": null,
  "agent_type": "general_e2e",
  "num_images_in_history": 3,
  "notes": null,
  "traj_file": "trajs/your-model.json.gz"
}
```

`category` must be one of `Agentic`, `General`, or `Specialized` — this drives the Type filter on the leaderboard.

For Agentic submissions, list the model used for each component, such as the planner, GUI operator, and verifier. Include the version, API model ID, or checkpoint when available. If one model serves multiple roles, list those roles together.

## 3. Send us the bundled output

Trajectory videos are hosted on a separate asset repo, so external contributors can't push them directly. Open a [GitHub issue](https://github.com/Tongyi-MAI/MobileWorld/issues) or reach out via the [Contact](../README.md#-contact) section, and attach:

- the bundled `.json.gz` (and `.mp4` if you used `--with-screenshots`)
- your proposed `leaderboard.json` entry

We'll handle the video upload and merge. Once landed, your model will appear on the leaderboard and in the arena for head-to-head comparison.
