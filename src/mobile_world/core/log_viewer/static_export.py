"""Static site export for log viewer."""

import json
import os
import shutil
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed

from loguru import logger
from PIL import Image
from rich.progress import BarColumn, Progress, SpinnerColumn, TaskProgressColumn, TextColumn

from mobile_world.core.log_viewer.styles import DARK_THEME_CSS
from mobile_world.core.log_viewer.utils import (
    calculate_task_stats,
    get_all_trajectory_steps,
    get_latest_screenshot,
    get_latest_trajectory_action,
    get_screenshots,
    get_task_folders,
    get_task_goal,
    get_task_info,
    get_task_status,
    get_task_tags,
    read_log_metadata,
)


def _escape_html(text: str) -> str:
    """Escape HTML special characters."""
    if not text:
        return ""
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&#39;")
    )


def _resize_and_save_image(
    src_path: str, dst_path: str, max_size: tuple[int, int] = (540, 1200)
) -> bool:
    """Resize an image to fit within max_size while maintaining aspect ratio.

    Returns True on success, False on failure.
    """
    try:
        with Image.open(src_path) as img:
            # Calculate the scaling factor to fit within max_size
            width_ratio = max_size[0] / img.width
            height_ratio = max_size[1] / img.height
            ratio = min(width_ratio, height_ratio, 1.0)  # Don't upscale

            if ratio < 1.0:
                new_size = (int(img.width * ratio), int(img.height * ratio))
                # Use BILINEAR for speed (LANCZOS is much slower)
                resized = img.resize(new_size, Image.Resampling.BILINEAR)
                resized.save(dst_path, format="PNG", optimize=False)
            else:
                # No resize needed, just copy the file directly
                shutil.copy2(src_path, dst_path)
        return True
    except Exception as e:
        logger.warning(f"Failed to resize image {src_path}: {e}, copying original")
        shutil.copy2(src_path, dst_path)
        return False


def _process_task_screenshots(
    task_name: str,
    task_folder: str,
    screenshots_dir: str,
    max_size: tuple[int, int] = (540, 1200),
) -> int:
    """Process all screenshots for a single task. Returns number of images processed."""
    task_screenshot_dir = os.path.join(screenshots_dir, task_name)
    os.makedirs(task_screenshot_dir, exist_ok=True)

    screenshots = get_screenshots(task_folder)
    count = 0
    for step_num, filename, subfolder in screenshots:
        src_path = os.path.join(task_folder, subfolder, filename)
        if os.path.exists(src_path):
            dst_path = os.path.join(task_screenshot_dir, filename)
            _resize_and_save_image(src_path, dst_path, max_size)
            count += 1
    return count


def export_static_site(log_root: str, output_dir: str, max_workers: int = 8) -> None:
    """Export trajectory logs as a static HTML site.

    Args:
        log_root: Path to the log root directory.
        output_dir: Path to the output directory.
        max_workers: Number of parallel workers for image processing.
    """
    if not os.path.exists(log_root):
        logger.error(f"Log root does not exist: {log_root}")
        sys.exit(1)

    # Create output directories
    os.makedirs(output_dir, exist_ok=True)
    tasks_dir = os.path.join(output_dir, "tasks")
    screenshots_dir = os.path.join(output_dir, "screenshots")
    os.makedirs(tasks_dir, exist_ok=True)
    os.makedirs(screenshots_dir, exist_ok=True)

    metadata = read_log_metadata(log_root)
    suite_family = metadata.get("suite_family", "mobile_world")

    task_folders = get_task_folders(log_root)
    stats = calculate_task_stats(log_root, suite_family=suite_family)

    logger.info(f"Exporting {len(task_folders)} tasks to {output_dir}")

    # First pass: collect task data and prepare screenshot jobs
    task_data_list = []
    screenshot_jobs = []  # (task_name, task_folder) for parallel processing

    for task_name in task_folders:
        task_folder = os.path.join(log_root, task_name)
        trajectory_steps = get_all_trajectory_steps(task_folder)

        if not trajectory_steps:
            continue

        status, score, reason = get_task_status(task_folder)
        task_tags = get_task_tags(task_name, suite_family=suite_family)
        latest_screenshot = get_latest_screenshot(task_folder)
        latest_action = get_latest_trajectory_action(task_folder)
        task_goal = get_task_goal(task_folder)

        # Queue screenshot processing
        screenshot_jobs.append((task_name, task_folder))

        # Get relative screenshot path for index
        screenshot_url = None
        if latest_screenshot:
            filename, _ = latest_screenshot
            screenshot_url = f"screenshots/{task_name}/{filename}"

        task_data_list.append(
            {
                "name": task_name,
                "goal": task_goal,
                "tags": task_tags,
                "status": status,
                "score": score,
                "reason": reason,
                "screenshot_url": screenshot_url,
                "latest_action": latest_action,
            }
        )

    # Process screenshots in parallel with progress bar
    total_images = 0
    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TaskProgressColumn(),
        TextColumn("[cyan]{task.completed}/{task.total}"),
    ) as progress:
        screenshot_task = progress.add_task(
            "[green]Processing screenshots...", total=len(screenshot_jobs)
        )

        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {
                executor.submit(
                    _process_task_screenshots, task_name, task_folder, screenshots_dir
                ): task_name
                for task_name, task_folder in screenshot_jobs
            }
            for future in as_completed(futures):
                task_name = futures[future]
                try:
                    count = future.result()
                    total_images += count
                except Exception as e:
                    logger.warning(f"Failed to process screenshots for {task_name}: {e}")
                progress.update(screenshot_task, advance=1)

        logger.info(f"Processed {total_images} screenshots")

        # Generate task detail pages with progress bar
        page_task = progress.add_task("[blue]Generating task pages...", total=len(screenshot_jobs))
        for task_name, task_folder in screenshot_jobs:
            _generate_task_page(task_name, log_root, tasks_dir, DARK_THEME_CSS)
            progress.update(page_task, advance=1)

    # Generate index page
    _generate_index_page(
        task_data_list, stats, output_dir, DARK_THEME_CSS, os.path.basename(log_root),
        suite_family=suite_family,
    )

    logger.info(f"✅ Static site exported to: {output_dir}")
    logger.info(f"   Open {os.path.join(output_dir, 'index.html')} in a browser")


def _generate_index_page(
    task_data_list: list[dict],
    stats: dict,
    output_dir: str,
    css: str,
    title: str,
    suite_family: str = "mobile_world",
) -> None:
    """Generate the main index.html page."""
    # Build stats HTML
    stats_html = f"""
    <div class="stats-grid">
        <div class="stat-card">
            <div class="stat-value">{stats["total"]}</div>
            <div class="stat-label">Total Tasks</div>
        </div>
        <div class="stat-card">
            <div class="stat-value">{stats["finished"]}</div>
            <div class="stat-label">Finished</div>
        </div>
        <div class="stat-card">
            <div class="stat-value warning">{stats["running"]}</div>
            <div class="stat-label">Running</div>
        </div>
        <div class="stat-card">
            <div class="stat-value danger">{stats["stale"]}</div>
            <div class="stat-label">Stale</div>
        </div>
        <div class="stat-card">
            <div class="stat-value success">{stats["success"]}</div>
            <div class="stat-label">Success</div>
        </div>
        <div class="stat-card">
            <div class="stat-value danger">{stats["failed"]}</div>
            <div class="stat-label">Failed</div>
        </div>
        <div class="stat-card">
            <div class="stat-value">{stats["avg_steps"]:.1f}</div>
            <div class="stat-label">Avg Steps</div>
        </div>
    </div>
    <div class="stats-grid stats-grid-rates">
        <div class="stat-card stat-card-wide">
            <div class="stat-value success">{stats["success_rate"]:.1f}%</div>
            <div class="stat-label">Overall ({stats["success"]}/{stats.get("total_task_no", stats["total"])})</div>
        </div>
        <div class="stat-card stat-card-wide">
            <div class="stat-value">{stats["standard_success_rate"]:.1f}%</div>
            <div class="stat-label">Standard ({stats["standard_success"]}/{stats["standard_finished"]})</div>
        </div>
        <div class="stat-card stat-card-wide">
            <div class="stat-value">{stats["mcp_success_rate"]:.1f}%</div>
            <div class="stat-label">MCP ({stats["mcp_success"]}/{stats["mcp_finished"]})</div>
        </div>
        <div class="stat-card stat-card-wide">
            <div class="stat-value">{stats["user_interaction_success_rate"]:.1f}%</div>
            <div class="stat-label">User Interaction ({stats["user_interaction_success"]}/{stats["user_interaction_finished"]})</div>
        </div>
        <div class="stat-card stat-card-wide">
            <div class="stat-value">{stats["uiq"]:.3f}</div>
            <div class="stat-label">UIQ</div>
        </div>
    </div>
    """

    # Build task rows
    task_rows = []
    for task in task_data_list:
        status_class = {
            "Finished": "finished",
            "Running": "running",
            "Stale": "stale",
        }.get(task["status"], "neutral")

        screenshot_html = (
            f'<img src="{_escape_html(task["screenshot_url"])}" class="thumb" alt="Screenshot">'
            if task["screenshot_url"]
            else '<span style="color: #666;">No screenshot</span>'
        )

        score_display = f"{task['score']:.2f}" if task["score"] is not None else "N/A"
        tags_display = ", ".join(sorted(task["tags"])) if task["tags"] else "-"
        goal_display = _escape_html(task["goal"]) if task["goal"] else "N/A"
        reason_display = _escape_html(task["reason"]) if task["reason"] else ""

        latest = task.get("latest_action") or {}
        step_display = str(latest.get("step", "N/A"))
        action_display = _escape_html(latest.get("action_type", "N/A"))
        prediction = latest.get("prediction", "")
        prediction_display = (
            _escape_html(prediction[:100] + "...")
            if len(prediction) > 100
            else _escape_html(prediction)
        )

        task_rows.append(f"""
        <tr>
            <td class="col-screenshot">{screenshot_html}</td>
            <td class="task-name-col"><a href="tasks/{task["name"]}.html">{_escape_html(task["name"])}</a></td>
            <td class="col-goal">{goal_display}</td>
            <td class="col-tags">{tags_display}</td>
            <td class="col-status"><span class="badge {status_class}">{task["status"]}</span></td>
            <td class="col-score">{score_display}</td>
            <td class="col-reason">{reason_display}</td>
            <td class="col-step">{step_display}</td>
            <td class="col-action">{action_display}</td>
            <td class="col-prediction">{prediction_display}</td>
        </tr>
        """)

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>📱 MobileWorld Log Viewer - {_escape_html(title)}</title>
    <style>{css}</style>
</head>
<body>
<div class="container">
    <div class="app-header">
        <div class="app-title">
            <div style="display: flex; align-items: center;">
                <h1>📱 MobileWorld Log Viewer</h1>
                <span class="badge {'finished' if suite_family == 'mobile_world' else 'running' if suite_family == 'android_world' else 'stale'}" style="margin-left: 12px; font-size: 14px;">{_escape_html(suite_family.replace('_', ' ').title())}</span>
            </div>
            <div class="last-update">Log: {_escape_html(title)}</div>
        </div>
    </div>

    {stats_html}

    <h2>Task Overview ({len(task_data_list)} tasks)</h2>
    <div class="table-container">
        <table class="task-table">
            <thead>
                <tr>
                    <th>Screenshot</th>
                    <th>Task Name</th>
                    <th>Goal</th>
                    <th>Tags</th>
                    <th>Status</th>
                    <th>Score</th>
                    <th>Reason</th>
                    <th>Step</th>
                    <th>Action</th>
                    <th>Prediction</th>
                </tr>
            </thead>
            <tbody>
                {"".join(task_rows) if task_rows else '<tr><td colspan="10" style="text-align: center; padding: 40px; color: var(--text-secondary);">No tasks found</td></tr>'}
            </tbody>
        </table>
    </div>
</div>
</body>
</html>"""

    with open(os.path.join(output_dir, "index.html"), "w") as f:
        f.write(html)


def _generate_task_page(
    task_name: str,
    log_root: str,
    tasks_dir: str,
    css: str,
) -> None:
    """Generate a detail page for a single task."""
    task_info = get_task_info(log_root, task_name)
    if not task_info:
        return

    screenshots = task_info["screenshots"]
    trajectory_steps = task_info["trajectory_steps"]
    step_map = {step.get("step", -1): step for step in trajectory_steps}

    # Build steps data for JS
    steps_data = []
    gallery_items = []

    for i, (step_num, screenshot_file, subfolder) in enumerate(screenshots):
        step_data = step_map.get(step_num, {})
        action = step_data.get("action", {})
        action_type = action.get("action_type", "N/A")
        prediction = step_data.get("prediction", "")
        screenshot_url = f"../screenshots/{task_name}/{screenshot_file}"

        next_step_data = step_map.get(step_num + 1, {})
        ask_user_response = next_step_data.get("ask_user_response")
        tool_call = next_step_data.get("tool_call")

        step_info = {
            "index": i,
            "step_num": step_num,
            "action_type": action_type,
            "prediction": prediction,
            "screenshot_url": screenshot_url,
            "ask_user_response": ask_user_response,
            "tool_call": tool_call,
        }
        steps_data.append(step_info)

        selected_class = " selected" if i == 0 else ""
        gallery_items.append(f"""
        <div class="gallery-item{selected_class}" id="gallery-item-{i}" data-step-index="{i}" onclick="selectStep({i})">
            <img src="{_escape_html(screenshot_url)}" class="gallery-thumb" alt="Step {step_num}" loading="lazy">
            <div class="gallery-item-info">
                <span class="gallery-step-num">Step {step_num}</span>
                <span class="gallery-action-type">{_escape_html(action_type)}</span>
            </div>
        </div>
        """)

    score_display = f"{task_info['score']:.2f}" if task_info["score"] is not None else "N/A"
    status_class = {
        "Finished": "finished",
        "Running": "running",
        "Stale": "stale",
    }.get(task_info["status"], "neutral")

    # Escape steps data for JS
    steps_data_json = json.dumps(steps_data, ensure_ascii=False)
    steps_data_json = (
        steps_data_json.replace("</script>", "<\\/script>")
        .replace("</Script>", "<\\/Script>")
        .replace("</SCRIPT>", "<\\/SCRIPT>")
        .replace("<!--", "<\\!--")
    )

    # Build tools HTML if available
    tools_html = ""
    if task_info.get("tools"):
        tools_items = []
        for tool in task_info["tools"]:
            schema_html = ""
            if tool.get("inputSchema"):
                schema_json = json.dumps(tool["inputSchema"], indent=2, ensure_ascii=False)
                schema_html = f'<div class="tool-schema-container"><pre class="tool-schema">{_escape_html(schema_json)}</pre></div>'
            tools_items.append(f"""
            <div class="tool-item">
                <div class="tool-header"><span class="tool-name">{_escape_html(tool.get("name", "Unknown"))}</span></div>
                <div class="tool-description">{_escape_html(tool.get("description", "No description"))}</div>
                {schema_html}
            </div>
            """)
        tools_html = f"""
        <div id="tools-modal" class="modal-overlay" style="display: none;" onclick="if(event.target === this) this.style.display='none';">
            <div class="modal-content">
                <div class="modal-header">
                    <span class="modal-title">Available Tools</span>
                    <button class="modal-close" onclick="document.getElementById('tools-modal').style.display='none';">×</button>
                </div>
                <div class="modal-body">{"".join(tools_items)}</div>
            </div>
        </div>
        """

    # Build token usage HTML if available
    token_usage_html = ""
    if task_info.get("token_usage"):
        usage_items = []
        for key, value in task_info["token_usage"].items():
            label = key.replace("_", " ").title()
            usage_items.append(f"""
            <div class="token-usage-item">
                <span class="token-usage-label">{_escape_html(label)}</span>
                <span class="token-usage-value">{value:,}</span>
            </div>
            """)
        token_usage_html = f"""
        <div id="token-usage-modal" class="modal-overlay" style="display: none;" onclick="if(event.target === this) this.style.display='none';">
            <div class="modal-content modal-content-small">
                <div class="modal-header">
                    <span class="modal-title">Token Usage</span>
                    <button class="modal-close" onclick="document.getElementById('token-usage-modal').style.display='none';">×</button>
                </div>
                <div class="modal-body token-usage-body">{"".join(usage_items)}</div>
            </div>
        </div>
        """

    tools_link = (
        f'<a href="#" class="meta-value tools-link" onclick="document.getElementById(\'tools-modal\').style.display=\'flex\'; return false;">{len(task_info.get("tools", []))} tools</a>'
        if task_info.get("tools")
        else '<span class="meta-value">-</span>'
    )
    token_link = (
        '<a href="#" class="meta-value tools-link" onclick="document.getElementById(\'token-usage-modal\').style.display=\'flex\'; return false;">View</a>'
        if task_info.get("token_usage")
        else '<span class="meta-value">-</span>'
    )

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Task: {_escape_html(task_name)}</title>
    <style>{css}</style>
</head>
<body>
<div class="detail-page">
    <div class="detail-header">
        <div class="back-nav"><a href="../index.html">← Back to Task List</a></div>
        <h1>Task: {_escape_html(task_name)}</h1>
        <div class="detail-meta-grid">
            <div class="meta-item">
                <span class="meta-label">Status</span>
                <span class="badge {status_class}">{task_info["status"]}</span>
            </div>
            <div class="meta-item">
                <span class="meta-label">Score</span>
                <span class="meta-value">{score_display}</span>
            </div>
            <div class="meta-item">
                <span class="meta-label">Goal</span>
                <span class="meta-value">{_escape_html(task_info.get("task_goal", "N/A"))}</span>
            </div>
            <div class="meta-item">
                <span class="meta-label">Reason</span>
                <span class="meta-value">{_escape_html(task_info.get("reason") or "-")}</span>
            </div>
            <div class="meta-item">
                <span class="meta-label">Tools</span>
                {tools_link}
            </div>
            <div class="meta-item">
                <span class="meta-label">Token Usage</span>
                {token_link}
            </div>
        </div>
    </div>

    <div class="detail-main">
        <div class="steps-gallery">
            <div class="gallery-grid">
                {"".join(gallery_items) if gallery_items else '<div class="empty-state">No steps available</div>'}
            </div>
        </div>

        <div class="detail-panel">
            <div class="detail-panel-header">
                <span class="detail-panel-title" id="panel-title">Step Details</span>
                <div class="detail-nav">
                    <button id="prev-step" class="nav-btn" disabled title="Previous step">←</button>
                    <button id="next-step" class="nav-btn" title="Next step">→</button>
                </div>
            </div>
            <div class="detail-panel-content" id="panel-content">
                {'<div class="detail-panel-empty">Select a step to view details</div>' if not gallery_items else ""}
            </div>
        </div>
    </div>

    {tools_html}
    {token_usage_html}
</div>

<script>
const stepsData = {steps_data_json};
let currentStep = 0;

function escapeHtml(text) {{
    if (!text) return '';
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}}

function selectStep(index) {{
    if (index < 0 || index >= stepsData.length) return;

    document.querySelectorAll('.gallery-item').forEach((item, i) => {{
        item.classList.toggle('selected', i === index);
    }});

    currentStep = index;
    const step = stepsData[index];

    const panelTitle = document.getElementById('panel-title');
    const panelContent = document.getElementById('panel-content');
    const prevBtn = document.getElementById('prev-step');
    const nextBtn = document.getElementById('next-step');

    panelTitle.textContent = 'Step ' + step.step_num;

    let html = `
        <div class="detail-group">
            <label>Action Type</label>
            <div class="font-mono">${{escapeHtml(step.action_type)}}</div>
        </div>
    `;

    if (step.prediction) {{
        html += `
            <div class="detail-group">
                <label>Prediction</label>
                <div class="prediction-box">${{escapeHtml(step.prediction)}}</div>
            </div>
        `;
    }}

    if (step.ask_user_response) {{
        html += `
            <div class="detail-group">
                <label>Ask User Response</label>
                <div class="prediction-box">${{escapeHtml(step.ask_user_response)}}</div>
            </div>
        `;
    }}

    if (step.tool_call) {{
        const toolCallStr = typeof step.tool_call === 'object'
            ? JSON.stringify(step.tool_call, null, 2)
            : String(step.tool_call);
        html += `
            <div class="detail-group">
                <label>Tool Call</label>
                <pre class="prediction-box font-mono">${{escapeHtml(toolCallStr)}}</pre>
            </div>
        `;
    }}

    panelContent.innerHTML = html;

    if (prevBtn) prevBtn.disabled = currentStep === 0;
    if (nextBtn) nextBtn.disabled = currentStep === stepsData.length - 1;
}}

document.addEventListener('DOMContentLoaded', () => {{
    if (stepsData.length > 0) {{
        selectStep(0);
    }}

    document.getElementById('prev-step')?.addEventListener('click', () => {{
        selectStep(currentStep - 1);
    }});

    document.getElementById('next-step')?.addEventListener('click', () => {{
        selectStep(currentStep + 1);
    }});

    document.addEventListener('keydown', (e) => {{
        if (document.activeElement.tagName === 'INPUT') return;
        if (e.key === 'ArrowLeft' || e.key === 'ArrowUp') {{
            selectStep(currentStep - 1);
            e.preventDefault();
        }} else if (e.key === 'ArrowRight' || e.key === 'ArrowDown') {{
            selectStep(currentStep + 1);
            e.preventDefault();
        }}
    }});
}});
</script>
</body>
</html>"""

    with open(os.path.join(tasks_dir, f"{task_name}.html"), "w") as f:
        f.write(html)
