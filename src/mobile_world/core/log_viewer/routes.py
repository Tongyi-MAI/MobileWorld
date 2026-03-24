"""Route handlers for the log viewer."""

import json
import os
import time
from urllib.parse import quote, unquote

from fasthtml.common import *  # noqa: F403
from loguru import logger
from starlette.responses import FileResponse

from mobile_world.core.log_viewer.styles import DARK_THEME_CSS, HTML_BODY_CSS
from mobile_world.core.log_viewer.utils import (
    calculate_task_stats,
    get_all_tags,
    get_all_trajectory_steps,
    get_child_trajectory_dirs,
    get_latest_screenshot,
    get_latest_trajectory_action,
    get_log_root_state,
    get_screenshots,
    get_task_folders,
    get_task_goal,
    get_task_info,
    get_task_status,
    get_task_tags,
    get_task_token_usage,
    get_task_tools,
    get_user_trajectory_folders,
    get_user_trajectory_task_folder,
    is_user_trajectory_log,
    is_valid_trajectory_dir,
    read_log_metadata,
)


def register_routes(rt, base_path: str = "/"):
    """Register all routes with the given router.

    Args:
        rt: The router to register routes with.
        base_path: Base path for all URLs (e.g., "/" or "/site/").
    """
    # Normalize base_path
    if not base_path.endswith("/"):
        base_path = base_path + "/"

    def url(path: str) -> str:
        """Build a URL with the base path prefix."""
        if path.startswith("/"):
            path = path[1:]
        return base_path + path

    ITEMS_PER_PAGE = 20
    GOAL_TRUNCATE_LENGTH = 80

    def _status_badge(status):
        cls_map = {
            "Finished": "finished",
            "Running": "running",
            "Stale": "stale",
        }
        return Span(status, cls=f"badge {cls_map.get(status, 'neutral')}")

    def _truncated_goal(goal: str, task_id: str) -> Div:
        """Render goal with show more/less toggle if too long."""
        if not goal or goal == "N/A" or len(goal) <= GOAL_TRUNCATE_LENGTH:
            return Div(goal if goal else "N/A")

        truncated = goal[:GOAL_TRUNCATE_LENGTH] + "..."
        unique_id = f"goal-{hash(task_id) % 100000}"
        return Div(
            Span(truncated, id=f"{unique_id}-short"),
            Span(goal, id=f"{unique_id}-full", style="display: none;"),
            A(
                "show more",
                href="javascript:void(0)",
                cls="show-more-link",
                onclick=f"document.getElementById('{unique_id}-short').style.display='none';"
                f"document.getElementById('{unique_id}-full').style.display='inline';"
                f"this.style.display='none';"
                f"this.nextElementSibling.style.display='inline';",
            ),
            A(
                "show less",
                href="javascript:void(0)",
                cls="show-more-link",
                style="display: none;",
                onclick=f"document.getElementById('{unique_id}-short').style.display='inline';"
                f"document.getElementById('{unique_id}-full').style.display='none';"
                f"this.style.display='none';"
                f"this.previousElementSibling.style.display='inline';",
            ),
        )

    def _build_pagination(
        current_page: int,
        total_pages: int,
        log_root: str,
        status_filter: str,
        score_filter: str,
        tag_filter: str,
        search_query: str = "",
    ) -> Div:
        """Build pagination controls."""
        if total_pages <= 1:
            return Div()

        def page_link(page_num: int, label: str, is_current: bool = False, disabled: bool = False):
            if disabled:
                return Span(label, cls="page-link disabled")
            if is_current:
                return Span(label, cls="page-link current")
            return A(
                label,
                href=url(
                    f"?log_root={quote(log_root)}&status_filter={status_filter}&score_filter={score_filter}&tag_filter={tag_filter}&search_query={quote(search_query)}&page={page_num}"
                ),
                cls="page-link",
            )

        items = []
        # Previous
        items.append(page_link(current_page - 1, "« Prev", disabled=current_page <= 1))

        # Page numbers with ellipsis
        if total_pages <= 7:
            for i in range(1, total_pages + 1):
                items.append(page_link(i, str(i), is_current=i == current_page))
        else:
            # Always show first page
            items.append(page_link(1, "1", is_current=current_page == 1))

            if current_page > 3:
                items.append(Span("...", cls="page-ellipsis"))

            # Pages around current
            start = max(2, current_page - 1)
            end = min(total_pages - 1, current_page + 1)
            for i in range(start, end + 1):
                items.append(page_link(i, str(i), is_current=i == current_page))

            if current_page < total_pages - 2:
                items.append(Span("...", cls="page-ellipsis"))

            # Always show last page
            items.append(
                page_link(total_pages, str(total_pages), is_current=current_page == total_pages)
            )

        # Next
        items.append(page_link(current_page + 1, "Next »", disabled=current_page >= total_pages))

        return Div(*items, cls="pagination")

    def _build_stats_ui(stats):
        return Div(
            # Row 1: General stats
            Div(
                Div(
                    Div(stats["total"], cls="stat-value"),
                    Div("Total Tasks", cls="stat-label"),
                    cls="stat-card",
                ),
                Div(
                    Div(stats["finished"], cls="stat-value"),
                    Div("Finished", cls="stat-label"),
                    cls="stat-card",
                ),
                Div(
                    Div(stats["running"], cls="stat-value warning"),
                    Div("Running", cls="stat-label"),
                    cls="stat-card",
                ),
                Div(
                    Div(stats["stale"], cls="stat-value danger"),
                    Div("Stale", cls="stat-label"),
                    cls="stat-card",
                ),
                Div(
                    Div(stats["success"], cls="stat-value success"),
                    Div("Success", cls="stat-label"),
                    cls="stat-card",
                ),
                Div(
                    Div(stats["failed"], cls="stat-value danger"),
                    Div("Failed", cls="stat-label"),
                    cls="stat-card",
                ),
                Div(
                    Div(f"{stats['avg_steps']:.1f}", cls="stat-value"),
                    Div("Avg Steps", cls="stat-label"),
                    cls="stat-card",
                ),
                cls="stats-grid",
            ),
            # Row 2: Success rates by category
            Div(
                Div(
                    Div(
                        f"{stats['success_rate']:.1f}%",
                        cls="stat-value success",
                    ),
                    Div(
                        f"Overall ({stats['success']}/{stats['total_task_no']})",
                        cls="stat-label",
                    ),
                    cls="stat-card stat-card-wide",
                ),
                Div(
                    Div(
                        f"{stats['standard_success_rate']:.1f}%",
                        cls="stat-value",
                    ),
                    Div(
                        f"Standard ({stats['standard_success']}/{stats['standard_finished']})",
                        cls="stat-label",
                    ),
                    cls="stat-card stat-card-wide",
                ),
                Div(
                    Div(
                        f"{stats['mcp_success_rate']:.1f}%",
                        cls="stat-value",
                    ),
                    Div(
                        f"MCP ({stats['mcp_success']}/{stats['mcp_finished']})",
                        cls="stat-label",
                    ),
                    cls="stat-card stat-card-wide",
                ),
                Div(
                    Div(
                        f"{stats['user_interaction_success_rate']:.1f}%",
                        cls="stat-value",
                    ),
                    Div(
                        f"User Interaction ({stats['user_interaction_success']}/{stats['user_interaction_finished']})",
                        cls="stat-label",
                    ),
                    cls="stat-card stat-card-wide",
                ),
                Div(
                    Div(
                        f"{stats['uiq']:.3f}",
                        cls="stat-value",
                    ),
                    Div(
                        "UIQ",
                        cls="stat-label",
                        title="User Interaction Quality: measures ask_user effectiveness",
                    ),
                    cls="stat-card stat-card-wide",
                ),
                cls="stats-grid stats-grid-rates",
            ),
        )

    def _process_tasks_for_display(
        log_root, status_filter, score_filter, tag_filter, search_query="", suite_family="mobile_world"
    ):
        task_folders = get_task_folders(log_root)
        task_rows = []
        filtered_count = 0
        total_count = len(task_folders)

        # Normalize search query for case-insensitive matching
        search_query_lower = search_query.lower().strip() if search_query else ""

        for task_name in task_folders:
            task_folder = os.path.join(log_root, task_name)
            trajectory_steps = get_all_trajectory_steps(task_folder)

            if not trajectory_steps:
                continue

            # Search filter (partial match on task name)
            if search_query_lower and search_query_lower not in task_name.lower():
                continue

            status, score, reason = get_task_status(task_folder)
            task_tags = get_task_tags(task_name, suite_family=suite_family)

            # Filtering
            if status_filter != "all":
                if status_filter == "running" and status != "Running":
                    continue
                if status_filter == "stale" and status != "Stale":
                    continue
                if status_filter == "finished" and status != "Finished":
                    continue

            if score_filter != "all":
                if score is None:
                    if score_filter not in ["no_score", "failed"]:
                        continue
                elif score_filter == "success" and score <= 0.99:
                    continue
                elif score_filter == "failed" and score > 0.99:
                    continue

            if tag_filter != "all":
                if tag_filter not in task_tags:
                    continue

            filtered_count += 1

            # Data gathering for row
            latest_screenshot = get_latest_screenshot(task_folder)
            latest_action = get_latest_trajectory_action(task_folder)
            task_goal = get_task_goal(task_folder)
            score_display = f"{score:.2f}" if score is not None else "N/A"

            screenshot_url = None
            if latest_screenshot:
                filename, subfolder = latest_screenshot
                screenshot_url = url(
                    f"static/screenshots/{task_name}/{subfolder}/{filename.replace('.png', '')}?log_root={quote(log_root)}"
                )

            task_rows.append(
                Tr(
                    Td(
                        Img(
                            src=screenshot_url,
                            cls="thumb",
                            alt="Latest screenshot",
                        )
                        if screenshot_url
                        else Span("No screenshot", style="color: #666;"),
                        cls="col-screenshot",
                    ),
                    Td(
                        A(
                            task_name,
                            href=url(f"task/{task_name}?log_root={quote(log_root)}"),
                            target="_blank",
                        ),
                        cls="task-name-col",
                    ),
                    Td(_truncated_goal(task_goal, task_name), cls="col-goal"),
                    Td(
                        ", ".join(sorted(task_tags)) if task_tags else "-",
                        cls="col-tags",
                    ),
                    Td(_status_badge(status), cls="col-status"),
                    Td(score_display, cls="col-score"),
                    Td(reason if reason else "", cls="col-reason"),
                    Td(
                        str(latest_action["step"]) if latest_action else "N/A",
                        cls="col-step",
                    ),
                    Td(
                        latest_action["action_type"] if latest_action else "N/A",
                        cls="col-action",
                    ),
                    Td(
                        latest_action["prediction"][:100] + "..."
                        if latest_action
                        and latest_action.get("prediction")
                        and len(latest_action["prediction"]) > 100
                        else (
                            latest_action["prediction"]
                            if latest_action and latest_action.get("prediction")
                            else ""
                        ),
                        cls="col-prediction",
                    ),
                )
            )
        return task_rows, filtered_count, total_count

    def _process_user_trajectories_for_display(log_root, search_query=""):
        """Process user trajectory logs for display (simplified, no metadata)."""
        traj_folders = get_user_trajectory_folders(log_root)
        task_rows = []
        filtered_count = 0
        total_count = len(traj_folders)

        search_query_lower = search_query.lower().strip() if search_query else ""

        for traj_id in traj_folders:
            task_folder = get_user_trajectory_task_folder(log_root, traj_id)
            trajectory_steps = get_all_trajectory_steps(task_folder)

            if not trajectory_steps:
                continue

            # Search filter
            if search_query_lower and search_query_lower not in traj_id.lower():
                task_goal = get_task_goal(task_folder)
                if search_query_lower not in task_goal.lower():
                    continue

            filtered_count += 1

            latest_screenshot = get_latest_screenshot(task_folder)
            latest_action = get_latest_trajectory_action(task_folder)
            task_goal = get_task_goal(task_folder)

            screenshot_url = None
            if latest_screenshot:
                filename, subfolder = latest_screenshot
                screenshot_url = url(
                    f"static/user_screenshots/{traj_id}/{subfolder}/{filename.replace('.png', '')}?log_root={quote(log_root)}"
                )

            task_rows.append(
                Tr(
                    Td(
                        Img(
                            src=screenshot_url,
                            cls="thumb",
                            alt="Latest screenshot",
                        )
                        if screenshot_url
                        else Span("No screenshot", style="color: #666;"),
                        cls="col-screenshot",
                    ),
                    Td(
                        A(
                            traj_id,
                            href=url(f"user_task/{traj_id}?log_root={quote(log_root)}"),
                            target="_blank",
                        ),
                        cls="task-name-col",
                    ),
                    Td(_truncated_goal(task_goal, traj_id), cls="col-goal"),
                    Td(
                        str(latest_action["step"]) if latest_action else "N/A",
                        cls="col-step",
                    ),
                    Td(
                        latest_action["action_type"] if latest_action else "N/A",
                        cls="col-action",
                    ),
                    Td(
                        latest_action["prediction"][:100] + "..."
                        if latest_action
                        and latest_action.get("prediction")
                        and len(latest_action["prediction"]) > 100
                        else (
                            latest_action["prediction"]
                            if latest_action and latest_action.get("prediction")
                            else ""
                        ),
                        cls="col-prediction",
                    ),
                )
            )
        return task_rows, filtered_count, total_count

    @rt("/static/screenshots/{task_name}/{subfolder}/{filename}")
    async def serve_screenshot(task_name: str, subfolder: str, filename: str, request):
        """Serve screenshot files from screenshots or marked_screenshots folder."""
        filename = filename + ".png"
        log_root_state = get_log_root_state()
        log_root_raw = request.query_params.get("log_root") or log_root_state.get("log_root", "")
        if not log_root_raw:
            return "Log root not specified", 400

        log_root = unquote(log_root_raw)
        if not os.path.isabs(log_root):
            log_root = os.path.abspath(log_root)

        # Validate subfolder to prevent path traversal
        if subfolder not in ("screenshots", "marked_screenshots"):
            return "Invalid subfolder", 400

        task_folder = os.path.join(log_root, task_name)
        screenshot_path = os.path.join(task_folder, subfolder, filename)

        if not os.path.exists(screenshot_path):
            return "Screenshot not found", 404

        return FileResponse(screenshot_path)

    @rt("/static/user_screenshots/{traj_id}/{subfolder}/{filename}")
    async def serve_user_screenshot(traj_id: str, subfolder: str, filename: str, request):
        """Serve screenshot files from user trajectory folders."""
        filename = filename + ".png"
        log_root_state = get_log_root_state()
        log_root_raw = request.query_params.get("log_root") or log_root_state.get("log_root", "")
        if not log_root_raw:
            return "Log root not specified", 400

        log_root = unquote(log_root_raw)
        if not os.path.isabs(log_root):
            log_root = os.path.abspath(log_root)

        if subfolder not in ("screenshots", "marked_screenshots"):
            return "Invalid subfolder", 400

        task_folder = get_user_trajectory_task_folder(log_root, traj_id)
        screenshot_path = os.path.join(task_folder, subfolder, filename)

        if not os.path.exists(screenshot_path):
            return "Screenshot not found", 404

        return FileResponse(screenshot_path)

    @rt("/user_task/{traj_id}")
    def user_task_detail(traj_id: str, request):
        """Display detailed information for a user trajectory (simplified, no metadata)."""
        log_root_state = get_log_root_state()
        log_root_raw = request.query_params.get("log_root") or log_root_state.get("log_root", "")
        log_root = unquote(log_root_raw) if log_root_raw else ""

        if not log_root:
            return (
                Titled("Error"),
                Style(DARK_THEME_CSS),
                Style(HTML_BODY_CSS),
                Div("Log root not specified", cls="empty-state"),
            )

        task_folder = get_user_trajectory_task_folder(log_root, traj_id)
        if not os.path.exists(task_folder):
            return (
                Titled("Trajectory Not Found"),
                Style(DARK_THEME_CSS),
                Style(HTML_BODY_CSS),
                Div(f"Trajectory '{traj_id}' not found", cls="empty-state"),
            )

        screenshots = get_screenshots(task_folder)
        trajectory_steps = get_all_trajectory_steps(task_folder)
        task_goal = get_task_goal(task_folder)
        tools = get_task_tools(task_folder)
        token_usage = get_task_token_usage(task_folder)

        # Build gallery items
        gallery_items = []
        step_map = {step.get("step", -1): step for step in trajectory_steps}
        steps_data = []

        for i, (step_num, screenshot_file, subfolder) in enumerate(screenshots):
            step_data = step_map.get(step_num, {})
            action = step_data.get("action", {})
            action_type = action.get("action_type", "N/A")
            prediction = step_data.get("prediction", "")
            screenshot_url = url(
                f"static/user_screenshots/{traj_id}/{subfolder}/{screenshot_file.replace('.png', '')}?log_root={quote(log_root)}"
            )

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

            gallery_items.append(
                Div(
                    Img(
                        src=screenshot_url,
                        cls="gallery-thumb",
                        alt=f"Step {step_num}",
                        loading="lazy",
                    ),
                    Div(
                        Span(f"Step {step_num}", cls="gallery-step-num"),
                        Span(action_type, cls="gallery-action-type"),
                        cls="gallery-item-info",
                    ),
                    cls="gallery-item" + (" selected" if i == 0 else ""),
                    id=f"gallery-item-{i}",
                    data_step_index=str(i),
                    onclick=f"selectStep({i})",
                )
            )

        steps_data_json = json.dumps(steps_data, ensure_ascii=False)
        steps_data_json = (
            steps_data_json.replace("</script>", "<\\/script>")
            .replace("</Script>", "<\\/Script>")
            .replace("</SCRIPT>", "<\\/SCRIPT>")
            .replace("<!--", "<\\!--")
        )

        script = Script(f"""
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
        """)

        return (
            Title(f"Trajectory: {traj_id}"),
            Style(DARK_THEME_CSS),
            Style(HTML_BODY_CSS),
            Div(
                # Header with task info (simplified)
                Div(
                    Div(
                        A(
                            "← Back to Trajectory List",
                            href=url(f"?log_root={quote(log_root)}"),
                        ),
                        cls="back-nav",
                    ),
                    H1(f"Trajectory: {traj_id}"),
                    Div(
                        Div(
                            Span("Goal", cls="meta-label"),
                            Span(task_goal if task_goal else "N/A", cls="meta-value"),
                            cls="meta-item",
                        ),
                        Div(
                            Span("Steps", cls="meta-label"),
                            Span(str(len(trajectory_steps)), cls="meta-value"),
                            cls="meta-item",
                        ),
                        Div(
                            Span("Tools", cls="meta-label"),
                            A(
                                f"{len(tools)} tools",
                                href="#",
                                cls="meta-value tools-link",
                                onclick="document.getElementById('tools-modal').style.display='flex'; return false;",
                            )
                            if tools
                            else Span("-", cls="meta-value"),
                            cls="meta-item",
                        )
                        if tools
                        else None,
                        Div(
                            Span("Token Usage", cls="meta-label"),
                            A(
                                "View",
                                href="#",
                                cls="meta-value tools-link",
                                onclick="document.getElementById('token-usage-modal').style.display='flex'; return false;",
                            )
                            if token_usage
                            else Span("-", cls="meta-value"),
                            cls="meta-item",
                        )
                        if token_usage
                        else None,
                        cls="detail-meta-grid",
                    ),
                    cls="detail-header",
                ),
                # Main content: waterfall gallery left, detail panel right
                Div(
                    Div(
                        Div(
                            *gallery_items
                            if gallery_items
                            else [Div("No steps available", cls="empty-state")],
                            cls="gallery-grid",
                        ),
                        cls="steps-gallery",
                    ),
                    Div(
                        Div(
                            Span("Step Details", cls="detail-panel-title", id="panel-title"),
                            Div(
                                Button(
                                    "←",
                                    id="prev-step",
                                    cls="nav-btn",
                                    disabled=True,
                                    title="Previous step",
                                ),
                                Button("→", id="next-step", cls="nav-btn", title="Next step"),
                                cls="detail-nav",
                            ),
                            cls="detail-panel-header",
                        ),
                        Div(
                            Div("Select a step to view details", cls="detail-panel-empty")
                            if not gallery_items
                            else None,
                            cls="detail-panel-content",
                            id="panel-content",
                        ),
                        cls="detail-panel",
                    ),
                    cls="detail-main",
                ),
                # Tools modal
                Div(
                    Div(
                        Div(
                            Span("Available Tools", cls="modal-title"),
                            Button(
                                "×",
                                cls="modal-close",
                                onclick="document.getElementById('tools-modal').style.display='none';",
                            ),
                            cls="modal-header",
                        ),
                        Div(
                            *[
                                Div(
                                    Div(
                                        Span(tool.get("name", "Unknown"), cls="tool-name"),
                                        cls="tool-header",
                                    ),
                                    Div(
                                        tool.get("description", "No description"),
                                        cls="tool-description",
                                    ),
                                    Div(
                                        Pre(
                                            json.dumps(
                                                tool.get("inputSchema", {}),
                                                indent=2,
                                                ensure_ascii=False,
                                            ),
                                            cls="tool-schema",
                                        ),
                                        cls="tool-schema-container",
                                    )
                                    if tool.get("inputSchema")
                                    else None,
                                    cls="tool-item",
                                )
                                for tool in tools
                            ]
                            if tools
                            else [Div("No tools available", cls="empty-state")],
                            cls="modal-body",
                        ),
                        cls="modal-content",
                    ),
                    id="tools-modal",
                    cls="modal-overlay",
                    style="display: none;",
                    onclick="if(event.target === this) this.style.display='none';",
                )
                if tools
                else None,
                # Token Usage modal
                Div(
                    Div(
                        Div(
                            Span("Token Usage", cls="modal-title"),
                            Button(
                                "×",
                                cls="modal-close",
                                onclick="document.getElementById('token-usage-modal').style.display='none';",
                            ),
                            cls="modal-header",
                        ),
                        Div(
                            *[
                                Div(
                                    Span(key.replace("_", " ").title(), cls="token-usage-label"),
                                    Span(f"{value:,}", cls="token-usage-value"),
                                    cls="token-usage-item",
                                )
                                for key, value in token_usage.items()
                            ]
                            if token_usage
                            else [Div("No token usage data available", cls="empty-state")],
                            cls="modal-body token-usage-body",
                        ),
                        cls="modal-content modal-content-small",
                    ),
                    id="token-usage-modal",
                    cls="modal-overlay",
                    style="display: none;",
                    onclick="if(event.target === this) this.style.display='none';",
                )
                if token_usage
                else None,
                script,
                cls="detail-page",
            ),
        )

    @rt("/task/{task_name}")
    def task_detail(task_name: str, request):
        """Display detailed information for a specific task."""
        log_root_state = get_log_root_state()
        log_root_raw = request.query_params.get("log_root") or log_root_state.get("log_root", "")
        log_root = unquote(log_root_raw) if log_root_raw else ""

        if not log_root:
            return (
                Titled("Error"),
                Style(DARK_THEME_CSS),
                Style(HTML_BODY_CSS),
                Div("Log root not specified", cls="empty-state"),
            )

        # Read suite family metadata
        metadata = read_log_metadata(log_root)
        suite_family = metadata.get("suite_family", "mobile_world")

        task_info = get_task_info(log_root, task_name)
        if not task_info:
            return (
                Titled("Task Not Found"),
                Style(DARK_THEME_CSS),
                Style(HTML_BODY_CSS),
                Div(f"Task '{task_name}' not found", cls="empty-state"),
            )

        # Build gallery items and step data for detail panel
        gallery_items = []
        screenshots = task_info["screenshots"]
        trajectory_steps = task_info["trajectory_steps"]
        step_map = {step.get("step", -1): step for step in trajectory_steps}

        # Prepare step data for JS
        steps_data = []

        for i, (step_num, screenshot_file, subfolder) in enumerate(screenshots):
            step_data = step_map.get(step_num, {})
            action = step_data.get("action", {})
            action_type = action.get("action_type", "N/A")
            prediction = step_data.get("prediction", "")
            screenshot_url = url(
                f"static/screenshots/{task_name}/{subfolder}/{screenshot_file.replace('.png', '')}?log_root={quote(log_root)}"
            )

            # Get ask_user_response and tool_call from next step
            next_step_data = step_map.get(step_num + 1, {})
            ask_user_response = next_step_data.get("ask_user_response")
            tool_call = next_step_data.get("tool_call")

            # Build step data for JS
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

            # Gallery item
            gallery_items.append(
                Div(
                    Img(
                        src=screenshot_url,
                        cls="gallery-thumb",
                        alt=f"Step {step_num}",
                        loading="lazy",
                    ),
                    Div(
                        Span(f"Step {step_num}", cls="gallery-step-num"),
                        Span(action_type, cls="gallery-action-type"),
                        cls="gallery-item-info",
                    ),
                    cls="gallery-item" + (" selected" if i == 0 else ""),
                    id=f"gallery-item-{i}",
                    data_step_index=str(i),
                    onclick=f"selectStep({i})",
                )
            )

        score_display = f"{task_info['score']:.2f}" if task_info["score"] is not None else "N/A"

        # Embed step data as JSON for JS
        # Escape </script> and <!-- to prevent breaking the script tag
        steps_data_json = json.dumps(steps_data, ensure_ascii=False)
        steps_data_json = (
            steps_data_json.replace("</script>", "<\\/script>")
            .replace("</Script>", "<\\/Script>")
            .replace("</SCRIPT>", "<\\/SCRIPT>")
            .replace("<!--", "<\\!--")
        )

        script = Script(f"""
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

                // Update gallery selection
                document.querySelectorAll('.gallery-item').forEach((item, i) => {{
                    item.classList.toggle('selected', i === index);
                }});

                currentStep = index;
                const step = stepsData[index];

                // Update detail panel
                const panelTitle = document.getElementById('panel-title');
                const panelContent = document.getElementById('panel-content');
                const prevBtn = document.getElementById('prev-step');
                const nextBtn = document.getElementById('next-step');

                panelTitle.textContent = 'Step ' + step.step_num;

                // Build detail content
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

                // Update nav buttons
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
        """)

        return (
            Title(f"Task: {unquote(task_name)}"),
            Style(DARK_THEME_CSS),
            Style(HTML_BODY_CSS),
            Div(
                # Header with task info
                Div(
                    Div(
                        A(
                            "← Back to Task List",
                            href=url(f"?log_root={quote(log_root)}"),
                        ),
                        cls="back-nav",
                    ),
                    H1(f"Task: {task_name}"),
                    Div(
                        Div(
                            Span("Suite", cls="meta-label"),
                            Span(suite_family.replace("_", " ").title(), cls="meta-value"),
                            cls="meta-item",
                        ),
                        Div(
                            Span("Status", cls="meta-label"),
                            _status_badge(task_info["status"]),
                            cls="meta-item",
                        ),
                        Div(
                            Span("Score", cls="meta-label"),
                            Span(score_display, cls="meta-value"),
                            cls="meta-item",
                        ),
                        Div(
                            Span("Goal", cls="meta-label"),
                            Span(task_info.get("task_goal", "N/A"), cls="meta-value"),
                            cls="meta-item",
                        ),
                        Div(
                            Span("Reason", cls="meta-label"),
                            Span(task_info.get("reason", "-"), cls="meta-value"),
                            cls="meta-item",
                        ),
                        Div(
                            Span("Tools", cls="meta-label"),
                            A(
                                f"{len(task_info.get('tools', []))} tools",
                                href="#",
                                cls="meta-value tools-link",
                                onclick="document.getElementById('tools-modal').style.display='flex'; return false;",
                            )
                            if task_info.get("tools")
                            else Span("-", cls="meta-value"),
                            cls="meta-item",
                        ),
                        Div(
                            Span("Token Usage", cls="meta-label"),
                            A(
                                "View",
                                href="#",
                                cls="meta-value tools-link",
                                onclick="document.getElementById('token-usage-modal').style.display='flex'; return false;",
                            )
                            if task_info.get("token_usage")
                            else Span("-", cls="meta-value"),
                            cls="meta-item",
                        ),
                        cls="detail-meta-grid",
                    ),
                    cls="detail-header",
                ),
                # Main content: waterfall gallery left, detail panel right
                Div(
                    # Left: Waterfall gallery
                    Div(
                        Div(
                            *gallery_items
                            if gallery_items
                            else [Div("No steps available", cls="empty-state")],
                            cls="gallery-grid",
                        ),
                        cls="steps-gallery",
                    ),
                    # Right: Sticky detail panel
                    Div(
                        Div(
                            Span("Step Details", cls="detail-panel-title", id="panel-title"),
                            Div(
                                Button(
                                    "←",
                                    id="prev-step",
                                    cls="nav-btn",
                                    disabled=True,
                                    title="Previous step",
                                ),
                                Button("→", id="next-step", cls="nav-btn", title="Next step"),
                                cls="detail-nav",
                            ),
                            cls="detail-panel-header",
                        ),
                        Div(
                            Div("Select a step to view details", cls="detail-panel-empty")
                            if not gallery_items
                            else None,
                            cls="detail-panel-content",
                            id="panel-content",
                        ),
                        cls="detail-panel",
                    ),
                    cls="detail-main",
                ),
                # Tools modal
                Div(
                    Div(
                        Div(
                            Span("Available Tools", cls="modal-title"),
                            Button(
                                "×",
                                cls="modal-close",
                                onclick="document.getElementById('tools-modal').style.display='none';",
                            ),
                            cls="modal-header",
                        ),
                        Div(
                            *[
                                Div(
                                    Div(
                                        Span(tool.get("name", "Unknown"), cls="tool-name"),
                                        cls="tool-header",
                                    ),
                                    Div(
                                        tool.get("description", "No description"),
                                        cls="tool-description",
                                    ),
                                    Div(
                                        Pre(
                                            json.dumps(
                                                tool.get("inputSchema", {}),
                                                indent=2,
                                                ensure_ascii=False,
                                            ),
                                            cls="tool-schema",
                                        ),
                                        cls="tool-schema-container",
                                    )
                                    if tool.get("inputSchema")
                                    else None,
                                    cls="tool-item",
                                )
                                for tool in task_info.get("tools", [])
                            ]
                            if task_info.get("tools")
                            else [Div("No tools available", cls="empty-state")],
                            cls="modal-body",
                        ),
                        cls="modal-content",
                    ),
                    id="tools-modal",
                    cls="modal-overlay",
                    style="display: none;",
                    onclick="if(event.target === this) this.style.display='none';",
                ),
                # Token Usage modal
                Div(
                    Div(
                        Div(
                            Span("Token Usage", cls="modal-title"),
                            Button(
                                "×",
                                cls="modal-close",
                                onclick="document.getElementById('token-usage-modal').style.display='none';",
                            ),
                            cls="modal-header",
                        ),
                        Div(
                            *[
                                Div(
                                    Span(key.replace("_", " ").title(), cls="token-usage-label"),
                                    Span(f"{value:,}", cls="token-usage-value"),
                                    cls="token-usage-item",
                                )
                                for key, value in task_info.get("token_usage", {}).items()
                            ]
                            if task_info.get("token_usage")
                            else [Div("No token usage data available", cls="empty-state")],
                            cls="modal-body token-usage-body",
                        ),
                        cls="modal-content modal-content-small",
                    ),
                    id="token-usage-modal",
                    cls="modal-overlay",
                    style="display: none;",
                    onclick="if(event.target === this) this.style.display='none';",
                ),
                script,
                cls="detail-page",
            ),
        )

    def _build_user_trajectory_pagination(
        current_page: int,
        total_pages: int,
        log_root: str,
        search_query: str = "",
    ) -> Div:
        """Build pagination controls for user trajectories."""
        if total_pages <= 1:
            return Div()

        def page_link(page_num: int, label: str, is_current: bool = False, disabled: bool = False):
            if disabled:
                return Span(label, cls="page-link disabled")
            if is_current:
                return Span(label, cls="page-link current")
            return A(
                label,
                href=url(
                    f"?log_root={quote(log_root)}&search_query={quote(search_query)}&page={page_num}"
                ),
                cls="page-link",
            )

        items = []
        items.append(page_link(current_page - 1, "« Prev", disabled=current_page <= 1))

        if total_pages <= 7:
            for i in range(1, total_pages + 1):
                items.append(page_link(i, str(i), is_current=i == current_page))
        else:
            items.append(page_link(1, "1", is_current=current_page == 1))
            if current_page > 3:
                items.append(Span("...", cls="page-ellipsis"))
            start = max(2, current_page - 1)
            end = min(total_pages - 1, current_page + 1)
            for i in range(start, end + 1):
                items.append(page_link(i, str(i), is_current=i == current_page))
            if current_page < total_pages - 2:
                items.append(Span("...", cls="page-ellipsis"))
            items.append(
                page_link(total_pages, str(total_pages), is_current=current_page == total_pages)
            )

        items.append(page_link(current_page + 1, "Next »", disabled=current_page >= total_pages))
        return Div(*items, cls="pagination")

    def _build_log_root_controls(
        log_root_input: str,
        selected_subdir: str,
        child_dirs: list[str],
        search_query: str,
        extra_hx_include: str = "",
    ) -> Div:
        """Build the log root input and optional subdirectory dropdown."""
        controls = [
            Div(
                Label("Log Root"),
                Input(
                    type="text",
                    name="log_root",
                    value=log_root_input,
                    placeholder="e.g., traj_logs/logs_20251029_4 or traj_logs/",
                    hx_get=url(""),
                    hx_target="body",
                    hx_trigger="keyup changed delay:500ms",
                    hx_swap="outerHTML",
                    hx_include=f"[name='search_query']{extra_hx_include}",
                ),
                cls="input-group-item input-group-wide" if not child_dirs else "input-group-item",
            ),
        ]

        if child_dirs:
            controls.append(
                Div(
                    Label("Trajectory Dir"),
                    Select(
                        Option("-- Select --", value="", selected=not selected_subdir),
                        *[Option(d, value=d, selected=selected_subdir == d) for d in child_dirs],
                        name="selected_subdir",
                        hx_get=url(""),
                        hx_target="body",
                        hx_trigger="change",
                        hx_swap="outerHTML",
                        hx_include=f"[name='log_root'], [name='search_query']{extra_hx_include}",
                    ),
                    cls="input-group-item",
                )
            )

        return Div(*controls, cls="input-row-logroot")

    @rt("/")
    def index(request):
        """Main page showing all tasks."""
        log_root_state = get_log_root_state()
        log_root_raw = request.query_params.get("log_root", "")
        log_root_input = unquote(log_root_raw) if log_root_raw else ""
        selected_subdir = request.query_params.get("selected_subdir", "")

        # Determine effective log_root (combining input + subdir if applicable)
        child_dirs: list[str] = []
        log_root = ""

        if log_root_input:
            if is_valid_trajectory_dir(log_root_input):
                # Direct trajectory directory
                log_root = log_root_input
            else:
                # Check if it's a parent directory with child trajectory dirs
                child_dirs = get_child_trajectory_dirs(log_root_input)
                if child_dirs and selected_subdir and selected_subdir in child_dirs:
                    log_root = os.path.join(log_root_input, selected_subdir)
                elif not child_dirs:
                    # Not a valid trajectory dir and no children - still set it for display
                    log_root = log_root_input

        if log_root:
            log_root_state["log_root"] = log_root
        elif not log_root_input:
            log_root = log_root_state.get("log_root", "")
            if log_root:
                logger.info(f"Retrieved log root from state: {log_root}")

        search_query = request.query_params.get("search_query", "")

        # Read suite family metadata
        metadata = read_log_metadata(log_root) if log_root else {}
        suite_family = metadata.get("suite_family", "mobile_world")

        # Pagination
        try:
            current_page = max(1, int(request.query_params.get("page", "1")))
        except ValueError:
            current_page = 1

        current_time = time.strftime("%Y-%m-%d %H:%M:%S")

        # Check if this is a user trajectory log
        is_user_traj = log_root and is_user_trajectory_log(log_root)

        if is_user_traj:
            # User trajectory mode - simplified view
            task_rows = []
            filtered_count = 0
            total_count = 0
            total_pages = 1

            task_rows, filtered_count, total_count = _process_user_trajectories_for_display(
                log_root, search_query
            )
            total_pages = max(1, (filtered_count + ITEMS_PER_PAGE - 1) // ITEMS_PER_PAGE)
            current_page = min(current_page, total_pages)
            start_idx = (current_page - 1) * ITEMS_PER_PAGE
            end_idx = start_idx + ITEMS_PER_PAGE
            task_rows = task_rows[start_idx:end_idx]

            return (
                Style(DARK_THEME_CSS),
                Div(
                    # Header
                    Div(
                        Div(
                            H1("📱 MobileWorld Trajectory Viewer"),
                            Div(
                                f"Last Updated: {current_time}",
                                cls="last-update",
                                id="last-update-time",
                            ),
                            cls="app-title",
                        ),
                        cls="app-header",
                    ),
                    # Controls (simplified)
                    Div(
                        Form(
                            Div(
                                _build_log_root_controls(
                                    log_root_input, selected_subdir, child_dirs, search_query
                                ),
                                Div(
                                    Label("Search"),
                                    Input(
                                        type="text",
                                        name="search_query",
                                        value=search_query,
                                        placeholder="Filter by ID or goal...",
                                        hx_get=url(""),
                                        hx_target="body",
                                        hx_trigger="keyup changed delay:300ms",
                                        hx_swap="outerHTML",
                                        hx_include="[name='log_root'], [name='selected_subdir']",
                                    ),
                                    cls="input-group-item",
                                ),
                                cls="input-row",
                            ),
                            Input(type="hidden", name="page", value=str(current_page)),
                            cls="controls-section",
                        ),
                    ),
                    # Content (Table only, no stats)
                    Div(
                        Div(
                            H2(
                                f"Trajectories ({filtered_count}/{total_count}) - Page {current_page}/{total_pages}"
                            ),
                            Div(
                                Table(
                                    Thead(
                                        Tr(
                                            Th("Screenshot"),
                                            Th("ID"),
                                            Th("Goal"),
                                            Th("Step"),
                                            Th("Action"),
                                            Th("Prediction"),
                                        )
                                    ),
                                    Tbody(
                                        *task_rows
                                        if task_rows
                                        else [
                                            Tr(
                                                Td(
                                                    "No trajectories found",
                                                    colspan=6,
                                                    style="text-align: center; padding: 40px; color: var(--text-secondary);",
                                                )
                                            )
                                        ]
                                    ),
                                    cls="task-table",
                                ),
                                cls="table-container",
                            ),
                            _build_user_trajectory_pagination(
                                current_page,
                                total_pages,
                                log_root,
                                search_query,
                            )
                            if total_pages > 1
                            else None,
                        ),
                        id="refreshable-content",
                    ),
                    cls="container",
                ),
            )

        # Standard task log mode
        status_filter = request.query_params.get("status_filter", "all")
        score_filter = request.query_params.get("score_filter", "all")
        tag_filter = request.query_params.get("tag_filter", "all")

        # Auto-refresh
        if "log_root" in request.query_params:
            is_auto_refresh = request.query_params.get("auto_refresh") == "true"
        else:
            is_auto_refresh = True

        all_tags = get_all_tags(suite_family=suite_family)

        # Get Stats
        stats = (
            calculate_task_stats(log_root, suite_family=suite_family)
            if log_root
            else {
                "total_task_no": 0,
                "total": 0,
                "finished": 0,
                "running": 0,
                "stale": 0,
                "success": 0,
                "failed": 0,
                "success_rate": 0.0,
                "total_steps": 0,
                "avg_steps": 0.0,
                "mcp_success": 0,
                "mcp_finished": 0,
                "mcp_success_rate": 0.0,
                "user_interaction_success": 0,
                "user_interaction_finished": 0,
                "user_interaction_success_rate": 0.0,
                "standard_success": 0,
                "standard_finished": 0,
                "standard_success_rate": 0.0,
                "uiq": 0.0,
                "avg_queries": 0.0,
                "avg_mcp_calls": 0.0,
            }
        )

        # Get Tasks
        task_rows = []
        filtered_count = 0
        total_count = 0
        total_pages = 1

        if log_root:
            task_rows, filtered_count, total_count = _process_tasks_for_display(
                log_root, status_filter, score_filter, tag_filter, search_query, suite_family=suite_family
            )
            # Pagination
            total_pages = max(1, (filtered_count + ITEMS_PER_PAGE - 1) // ITEMS_PER_PAGE)
            current_page = min(current_page, total_pages)
            start_idx = (current_page - 1) * ITEMS_PER_PAGE
            end_idx = start_idx + ITEMS_PER_PAGE
            task_rows = task_rows[start_idx:end_idx]

        suite_label = suite_family.replace("_", " ").title() if log_root else ""
        suite_badge_cls = {"mobile_world": "badge finished", "android_world": "badge running", "user_task": "badge stale"}.get(suite_family, "badge neutral")

        return (
            Title("📱 MobileWorld Log Viewer"),
            Style(DARK_THEME_CSS),
            Div(
                # Header
                Div(
                    Div(
                        Div(
                            H1("📱 MobileWorld Log Viewer"),
                            Span(
                                suite_label,
                                cls=suite_badge_cls,
                                style="margin-left: 12px; font-size: 14px; vertical-align: middle;",
                            ) if suite_label else None,
                            style="display: flex; align-items: center;",
                        ),
                        Div(
                            f"Last Updated: {current_time}",
                            cls="last-update",
                            id="last-update-time",
                        ),
                        cls="app-title",
                    ),
                    cls="app-header",
                ),
                # Controls & Filters
                Div(
                    Form(
                        Div(
                            _build_log_root_controls(
                                log_root_input,
                                selected_subdir,
                                child_dirs,
                                search_query,
                                ", [name='status_filter'], [name='score_filter'], [name='tag_filter'], [name='auto_refresh']",
                            ),
                            Div(
                                Label("Search Task"),
                                Input(
                                    type="text",
                                    name="search_query",
                                    value=search_query,
                                    placeholder="Filter by task name...",
                                    hx_get=url(""),
                                    hx_target="body",
                                    hx_trigger="keyup changed delay:300ms",
                                    hx_swap="outerHTML",
                                    hx_include="[name='log_root'], [name='selected_subdir'], [name='status_filter'], [name='score_filter'], [name='tag_filter'], [name='auto_refresh']",
                                ),
                                cls="input-group-item",
                            ),
                            cls="input-row",
                        ),
                        Div(
                            Div(
                                Label("Status"),
                                Select(
                                    Option(
                                        "All",
                                        value="all",
                                        selected=status_filter == "all",
                                    ),
                                    Option(
                                        "Running",
                                        value="running",
                                        selected=status_filter == "running",
                                    ),
                                    Option(
                                        "Stale",
                                        value="stale",
                                        selected=status_filter == "stale",
                                    ),
                                    Option(
                                        "Finished",
                                        value="finished",
                                        selected=status_filter == "finished",
                                    ),
                                    name="status_filter",
                                    hx_get=url(""),
                                    hx_target="body",
                                    hx_trigger="change",
                                    hx_swap="outerHTML",
                                    hx_include="[name='log_root'], [name='selected_subdir'], [name='score_filter'], [name='tag_filter'], [name='auto_refresh'], [name='search_query']",
                                ),
                                cls="filter-item",
                            ),
                            Div(
                                Label("Score"),
                                Select(
                                    Option(
                                        "All",
                                        value="all",
                                        selected=score_filter == "all",
                                    ),
                                    Option(
                                        "Success",
                                        value="success",
                                        selected=score_filter == "success",
                                    ),
                                    Option(
                                        "Failed",
                                        value="failed",
                                        selected=score_filter == "failed",
                                    ),
                                    name="score_filter",
                                    hx_get=url(""),
                                    hx_target="body",
                                    hx_trigger="change",
                                    hx_swap="outerHTML",
                                    hx_include="[name='log_root'], [name='selected_subdir'], [name='status_filter'], [name='tag_filter'], [name='auto_refresh'], [name='search_query']",
                                ),
                                cls="filter-item",
                            ),
                            Div(
                                Label("Tag"),
                                Select(
                                    Option(
                                        "All",
                                        value="all",
                                        selected=tag_filter == "all",
                                    ),
                                    *[
                                        Option(
                                            tag,
                                            value=tag,
                                            selected=tag_filter == tag,
                                        )
                                        for tag in all_tags
                                    ],
                                    name="tag_filter",
                                    hx_get=url(""),
                                    hx_target="body",
                                    hx_trigger="change",
                                    hx_swap="outerHTML",
                                    hx_include="[name='log_root'], [name='selected_subdir'], [name='status_filter'], [name='score_filter'], [name='auto_refresh'], [name='search_query']",
                                ),
                                cls="filter-item",
                            ),
                            Div(
                                Label("Auto-refresh"),
                                Div(
                                    Label(
                                        Input(
                                            type="checkbox",
                                            name="auto_refresh",
                                            value="true",
                                            checked=is_auto_refresh,
                                            hx_get=url("refresh"),
                                            hx_target="#refreshable-content",
                                            hx_swap="outerHTML",
                                            hx_include="[name='log_root'], [name='selected_subdir'], [name='status_filter'], [name='score_filter'], [name='tag_filter'], [name='page'], [name='search_query']",
                                        ),
                                        " Enabled",
                                        cls="checkbox-label",
                                    ),
                                    cls="checkbox-wrapper",
                                ),
                                cls="filter-item",
                            ),
                            Input(type="hidden", name="page", value=str(current_page)),
                            cls="filters-row",
                        ),
                        cls="controls-section",
                    ),
                ),
                # Content (Stats + Table)
                Div(
                    _build_stats_ui(stats) if log_root and stats["total"] > 0 else None,
                    Div(
                        H2(
                            f"Task Overview ({filtered_count}/{total_count}) - Page {current_page}/{total_pages}"
                            if log_root
                            else "Task Overview"
                        ),
                        Div(
                            Table(
                                Thead(
                                    Tr(
                                        Th("Screenshot"),
                                        Th("Task Name"),
                                        Th("Goal"),
                                        Th("Tags"),
                                        Th("Status"),
                                        Th("Score"),
                                        Th("Reason"),
                                        Th("Step"),
                                        Th("Action"),
                                        Th("Prediction"),
                                    )
                                ),
                                Tbody(
                                    *task_rows
                                    if task_rows
                                    else [
                                        Tr(
                                            Td(
                                                "No tasks found matching criteria",
                                                colspan=10,
                                                style="text-align: center; padding: 40px; color: var(--text-secondary);",
                                            )
                                        )
                                    ]
                                ),
                                cls="task-table",
                            ),
                            cls="table-container",
                        ),
                        _build_pagination(
                            current_page,
                            total_pages,
                            log_root,
                            status_filter,
                            score_filter,
                            tag_filter,
                            search_query,
                        )
                        if log_root and total_pages > 1
                        else None,
                    )
                    if log_root
                    else Div(
                        H2("Welcome"),
                        P("Please enter a log root directory above to start."),
                        cls="empty-state",
                    ),
                    id="refreshable-content",
                    hx_get=url("refresh") if (log_root and is_auto_refresh) else None,
                    hx_target="this" if (log_root and is_auto_refresh) else None,
                    hx_trigger="every 5s" if (log_root and is_auto_refresh) else None,
                    hx_swap="outerHTML" if (log_root and is_auto_refresh) else None,
                    hx_include="[name='log_root'], [name='selected_subdir'], [name='status_filter'], [name='score_filter'], [name='tag_filter'], [name='auto_refresh'], [name='page'], [name='search_query']"
                    if (log_root and is_auto_refresh)
                    else None,
                    hx_on_after_swap="document.getElementById('last-update-time').textContent = 'Last Updated: ' + new Date().toLocaleString();"
                    if (log_root and is_auto_refresh)
                    else None,
                ),
                # Floating Refresh Button
                Button(
                    "↻",
                    type="button",
                    cls="btn-floating",
                    title="Refresh Now",
                    hx_get=url("refresh") if log_root else None,
                    hx_target="#refreshable-content",
                    hx_swap="outerHTML",
                    hx_include="[name='log_root'], [name='selected_subdir'], [name='status_filter'], [name='score_filter'], [name='tag_filter'], [name='auto_refresh'], [name='search_query']",
                    onclick="document.getElementById('last-update-time').textContent = 'Last Updated: ' + new Date().toLocaleString();",
                )
                if log_root
                else None,
                cls="container",
            ),
        )

    @rt("/refresh")
    def refresh(request):
        """Refresh endpoint for auto-refresh."""
        log_root_state = get_log_root_state()
        log_root_raw = request.query_params.get("log_root", "") or log_root_state.get(
            "log_root", ""
        )
        log_root_input = unquote(log_root_raw) if log_root_raw else ""
        selected_subdir = request.query_params.get("selected_subdir", "")

        # Determine effective log_root
        log_root = ""
        if log_root_input:
            if is_valid_trajectory_dir(log_root_input):
                log_root = log_root_input
            else:
                child_dirs = get_child_trajectory_dirs(log_root_input)
                if child_dirs and selected_subdir and selected_subdir in child_dirs:
                    log_root = os.path.join(log_root_input, selected_subdir)
                elif not child_dirs:
                    log_root = log_root_input

        if not log_root:
            return Div("No log root specified", cls="empty-state", id="refreshable-content")

        # Read suite family metadata
        metadata = read_log_metadata(log_root)
        suite_family = metadata.get("suite_family", "mobile_world")

        status_filter = request.query_params.get("status_filter", "all")
        score_filter = request.query_params.get("score_filter", "all")
        tag_filter = request.query_params.get("tag_filter", "all")
        search_query = request.query_params.get("search_query", "")
        auto_refresh = request.query_params.get("auto_refresh") == "true"

        # Pagination
        try:
            current_page = max(1, int(request.query_params.get("page", "1")))
        except ValueError:
            current_page = 1

        stats = calculate_task_stats(log_root, suite_family=suite_family)
        task_rows, filtered_count, total_count = _process_tasks_for_display(
            log_root, status_filter, score_filter, tag_filter, search_query, suite_family=suite_family
        )

        # Pagination
        total_pages = max(1, (filtered_count + ITEMS_PER_PAGE - 1) // ITEMS_PER_PAGE)
        current_page = min(current_page, total_pages)
        start_idx = (current_page - 1) * ITEMS_PER_PAGE
        end_idx = start_idx + ITEMS_PER_PAGE
        task_rows = task_rows[start_idx:end_idx]

        return Div(
            _build_stats_ui(stats) if stats["total"] > 0 else None,
            Div(
                H2(
                    f"Task Overview ({filtered_count}/{total_count}) - Page {current_page}/{total_pages}"
                ),
                Div(
                    Table(
                        Thead(
                            Tr(
                                Th("Screenshot"),
                                Th("Task Name"),
                                Th("Goal"),
                                Th("Tags"),
                                Th("Status"),
                                Th("Score"),
                                Th("Reason"),
                                Th("Step"),
                                Th("Action"),
                                Th("Prediction"),
                            )
                        ),
                        Tbody(
                            *task_rows
                            if task_rows
                            else [
                                Tr(
                                    Td(
                                        "No tasks found matching criteria",
                                        colspan=10,
                                        style="text-align: center; padding: 40px; color: var(--text-secondary);",
                                    )
                                )
                            ]
                        ),
                        cls="task-table",
                    ),
                    cls="table-container",
                ),
                _build_pagination(
                    current_page,
                    total_pages,
                    log_root,
                    status_filter,
                    score_filter,
                    tag_filter,
                    search_query,
                )
                if total_pages > 1
                else None,
            ),
            id="refreshable-content",
            hx_get=url("refresh") if auto_refresh else None,
            hx_target="this" if auto_refresh else None,
            hx_trigger="every 5s" if auto_refresh else None,
            hx_swap="outerHTML" if auto_refresh else None,
            hx_include="[name='log_root'], [name='selected_subdir'], [name='status_filter'], [name='score_filter'], [name='tag_filter'], [name='auto_refresh'], [name='page'], [name='search_query']"
            if auto_refresh
            else None,
            hx_on_after_swap="document.getElementById('last-update-time').textContent = 'Last Updated: ' + new Date().toLocaleString();"
            if auto_refresh
            else None,
        )
