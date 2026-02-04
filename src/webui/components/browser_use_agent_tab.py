import asyncio
import json
import logging
import os
import uuid
from typing import Any, AsyncGenerator, Dict, Optional

import gradio as gr

from browser_use import Agent
from browser_use.agent.views import AgentHistoryList, AgentOutput
from browser_use.browser.session import BrowserSession
from browser_use.browser.views import BrowserStateSummary
from browser_use.llm.base import BaseChatModel
from browser_use.mcp.client import MCPClient
from browser_use.tools.service import Tools
from gradio.components import Component

from src.agent.code_agent_runner import create_flow_script
from src.utils import llm_provider
from src.webui.webui_manager import WebuiManager

logger = logging.getLogger(__name__)


def _as_chatbot_messages(history: list[dict[str, Optional[str]]]) -> list[tuple[str, str]]:
    if not history:
        return []
    first = history[0]
    if isinstance(first, (list, tuple)) and len(first) == 2:
        return history  # already in tuples format
    converted = []
    for msg in history:
        role = msg.get("role", "assistant") if isinstance(msg, dict) else "assistant"
        content = msg.get("content", "") if isinstance(msg, dict) else str(msg)
        prefix = "User" if role == "user" else "Assistant"
        converted.append((prefix, content))
    return converted


async def _initialize_llm(
        provider: Optional[str],
        model_name: Optional[str],
        temperature: float,
        base_url: Optional[str],
        api_key: Optional[str],
        num_ctx: Optional[int] = None,
) -> Optional[BaseChatModel]:
    """Initializes the LLM based on settings. Returns None if provider/model is missing."""
    if not provider or not model_name:
        logger.info("LLM Provider or Model Name not specified, LLM will be None.")
        return None
    try:
        logger.info(
            f"Initializing LLM: Provider={provider}, Model={model_name}, Temp={temperature}"
        )
        llm = llm_provider.get_llm_model(
            provider=provider,
            model_name=model_name,
            temperature=temperature,
            base_url=base_url or None,
            api_key=api_key or None,
            num_ctx=num_ctx if provider == "ollama" else None,
        )
        return llm
    except Exception as e:
        logger.error(f"Failed to initialize LLM: {e}", exc_info=True)
        gr.Warning(
            f"Failed to initialize LLM '{model_name}' for provider '{provider}'. Please check settings. Error: {e}"
        )
        return None


def _get_config_value(
        webui_manager: WebuiManager,
        comp_dict: Dict[gr.components.Component, Any],
        comp_id_suffix: str,
        default: Any = None,
) -> Any:
    """Safely get value from component dictionary using its ID suffix relative to the tab."""
    tab_name = "browser_use_agent"
    comp_id = f"{tab_name}.{comp_id_suffix}"
    try:
        comp = webui_manager.get_component_by_id(comp_id)
        return comp_dict.get(comp, default)
    except KeyError:
        for prefix in ["agent_settings", "browser_settings"]:
            try:
                comp_id = f"{prefix}.{comp_id_suffix}"
                comp = webui_manager.get_component_by_id(comp_id)
                return comp_dict.get(comp, default)
            except KeyError:
                continue
        logger.warning(
            f"Component with suffix '{comp_id_suffix}' not found in manager for value lookup."
        )
        return default


def _format_agent_output(model_output: AgentOutput) -> str:
    """Formats AgentOutput for display in the chatbot using JSON."""
    content = ""
    if model_output:
        try:
            action_dump = [
                action.model_dump(exclude_none=True) for action in model_output.action
            ]

            state_dump = model_output.current_state.model_dump(exclude_none=True)
            model_output_dump = {
                "current_state": state_dump,
                "action": action_dump,
            }
            json_string = json.dumps(model_output_dump, indent=4, ensure_ascii=False)
            content = f"<pre><code class='language-json'>{json_string}</code></pre>"

        except AttributeError as ae:
            logger.error(
                f"AttributeError during model dump: {ae}. Check if 'action' or 'current_state' or their items support 'model_dump'."
            )
            content = f"<pre><code>Error: Could not format agent output (AttributeError: {ae}).\nRaw output: {str(model_output)}</code></pre>"
        except Exception as e:
            logger.error(f"Error formatting agent output: {e}", exc_info=True)
            content = f"<pre><code>Error formatting agent output.\nRaw output:\n{str(model_output)}</code></pre>"

    return content.strip()


async def _handle_new_step(
        webui_manager: WebuiManager, state: BrowserStateSummary, output: AgentOutput, step_num: int
):
    """Callback for each step taken by the agent, including screenshot display."""
    if not hasattr(webui_manager, "bu_chat_history"):
        webui_manager.bu_chat_history = []
    step_num -= 1
    logger.info(f"Step {step_num} completed.")

    screenshot_html = ""
    screenshot_data = getattr(state, "screenshot", None)
    if screenshot_data:
        try:
            if isinstance(screenshot_data, str) and len(screenshot_data) > 100:
                img_tag = f'<img src="data:image/jpeg;base64,{screenshot_data}" alt="Step {step_num} Screenshot" style="max-width: 800px; max-height: 600px; object-fit:contain;" />'
                screenshot_html = img_tag + "<br/>"
            else:
                logger.warning(
                    f"Screenshot for step {step_num} seems invalid (type: {type(screenshot_data)}, len: {len(screenshot_data) if isinstance(screenshot_data, str) else 'N/A'})."
                )
                screenshot_html = "**[Invalid screenshot data]**<br/>"

        except Exception as e:
            logger.error(
                f"Error processing or formatting screenshot for step {step_num}: {e}",
                exc_info=True,
            )
            screenshot_html = "**[Error displaying screenshot]**<br/>"
    else:
        logger.debug(f"No screenshot available for step {step_num}.")

    formatted_output = _format_agent_output(output)

    step_header = f"--- **Step {step_num}** ---"
    final_content = step_header + "<br/>" + screenshot_html + formatted_output

    chat_message = {
        "role": "assistant",
        "content": final_content.strip(),
    }

    webui_manager.bu_chat_history.append(chat_message)

    await asyncio.sleep(0.05)


def _handle_done(webui_manager: WebuiManager, history: AgentHistoryList):
    """Callback when the agent finishes the task (success or failure)."""
    token_count = None
    if getattr(history, "usage", None) is not None:
        token_count = history.usage.total_tokens

    if token_count is not None:
        logger.info(
            f"Agent task finished. Duration: {history.total_duration_seconds():.2f}s, Tokens: {token_count}"
        )
    else:
        logger.info(
            f"Agent task finished. Duration: {history.total_duration_seconds():.2f}s"
        )
    final_summary = "**Task Completed**\n"
    final_summary += f"- Duration: {history.total_duration_seconds():.2f} seconds\n"
    if token_count is not None:
        final_summary += f"- Total Tokens: {token_count}\n"

    final_result = history.final_result()
    if final_result:
        final_summary += f"- Final Result: {final_result}\n"

    errors = history.errors()
    if errors and any(errors):
        final_summary += f"- **Errors:**\n```\n{errors}\n```\n"
    else:
        final_summary += "- Status: Success\n"

    webui_manager.bu_chat_history.append(
        {"role": "assistant", "content": final_summary}
    )


async def run_agent_task(
        webui_manager: WebuiManager, components: Dict[gr.components.Component, Any]
) -> AsyncGenerator[Dict[gr.components.Component, Any], None]:
    """Handles the entire lifecycle of initializing and running the agent."""
    user_input_comp = webui_manager.get_component_by_id("browser_use_agent.user_input")
    run_button_comp = webui_manager.get_component_by_id("browser_use_agent.run_button")
    stop_button_comp = webui_manager.get_component_by_id(
        "browser_use_agent.stop_button"
    )
    pause_resume_button_comp = webui_manager.get_component_by_id(
        "browser_use_agent.pause_resume_button"
    )
    clear_button_comp = webui_manager.get_component_by_id(
        "browser_use_agent.clear_button"
    )
    chatbot_comp = webui_manager.get_component_by_id("browser_use_agent.chatbot")
    history_file_comp = webui_manager.get_component_by_id(
        "browser_use_agent.agent_history_file"
    )
    gif_comp = webui_manager.get_component_by_id("browser_use_agent.recording_gif")
    browser_view_comp = webui_manager.get_component_by_id(
        "browser_use_agent.browser_view"
    )

    task = components.get(user_input_comp, "").strip()
    if not task:
        gr.Warning("Please enter a task.")
        yield {run_button_comp: gr.update(interactive=True)}
        return

    webui_manager.bu_chat_history.append({"role": "user", "content": task})
    webui_manager.bu_last_task = task

    yield {
        user_input_comp: gr.Textbox(
            value="", interactive=False, placeholder="Agent is running..."
        ),
        run_button_comp: gr.Button(value="⏳ Running...", interactive=False),
        stop_button_comp: gr.Button(interactive=True),
        pause_resume_button_comp: gr.Button(value="⏸️ Pause", interactive=True),
        clear_button_comp: gr.Button(interactive=False),
        chatbot_comp: gr.update(value=_as_chatbot_messages(webui_manager.bu_chat_history)),
        history_file_comp: gr.update(value=None),
        gif_comp: gr.update(value=None),
    }

    def get_setting(key, default=None):
        comp = webui_manager.id_to_component.get(f"agent_settings.{key}")
        return components.get(comp, default) if comp else default

    override_system_prompt = get_setting("override_system_prompt") or None
    extend_system_prompt = get_setting("extend_system_prompt") or None
    llm_provider_name = get_setting("llm_provider", None)
    llm_model_name = get_setting("llm_model_name", None)
    llm_temperature = get_setting("llm_temperature", 0.6)
    use_vision = get_setting("use_vision", True)
    ollama_num_ctx = get_setting("ollama_num_ctx", 16000)
    llm_base_url = get_setting("llm_base_url") or None
    llm_api_key = get_setting("llm_api_key") or None
    max_steps = get_setting("max_steps", 100)
    max_actions = get_setting("max_actions", 10)
    mcp_server_config_comp = webui_manager.id_to_component.get(
        "agent_settings.mcp_server_config"
    )
    mcp_server_config_str = (
        components.get(mcp_server_config_comp) if mcp_server_config_comp else None
    )

    def get_browser_setting(key, default=None):
        comp = webui_manager.id_to_component.get(f"browser_settings.{key}")
        return components.get(comp, default) if comp else default

    browser_binary_path = get_browser_setting("browser_binary_path") or None
    browser_user_data_dir = get_browser_setting("browser_user_data_dir") or None
    use_own_browser = get_browser_setting("use_own_browser", False)
    keep_browser_open = get_browser_setting("keep_browser_open", False)
    headless = get_browser_setting("headless", False)
    disable_security = get_browser_setting("disable_security", False)
    accept_downloads = get_browser_setting("accept_downloads", True)
    window_w = int(get_browser_setting("window_w", 1280))
    window_h = int(get_browser_setting("window_h", 1100))
    cdp_url = get_browser_setting("cdp_url") or None
    wss_url = get_browser_setting("wss_url") or None
    save_recording_path = get_browser_setting("save_recording_path") or None
    save_trace_path = get_browser_setting("save_trace_path") or None
    save_agent_history_path = get_browser_setting(
        "save_agent_history_path", "./tmp/agent_history"
    )
    save_download_path = get_browser_setting("save_download_path", "./tmp/downloads")
    if save_download_path:
        os.makedirs(save_download_path, exist_ok=True)

    stream_vw = 70
    stream_vh = int(70 * window_h // window_w)

    os.makedirs(save_agent_history_path, exist_ok=True)
    if save_recording_path:
        os.makedirs(save_recording_path, exist_ok=True)
    if save_trace_path:
        os.makedirs(save_trace_path, exist_ok=True)
    if save_download_path:
        os.makedirs(save_download_path, exist_ok=True)

    main_llm = await _initialize_llm(
        llm_provider_name,
        llm_model_name,
        llm_temperature,
        llm_base_url,
        llm_api_key,
        ollama_num_ctx if llm_provider_name == "ollama" else None,
    )

    mcp_tools = None
    if mcp_server_config_str:
        try:
            mcp_config = json.loads(mcp_server_config_str)
            mcp_servers = mcp_config.get("mcpServers", mcp_config)
            if isinstance(mcp_servers, dict) and mcp_servers:
                mcp_tools = Tools()
                webui_manager.bu_mcp_clients = []
                for server_name, server_cfg in mcp_servers.items():
                    command = server_cfg.get("command")
                    args = server_cfg.get("args", [])
                    env = server_cfg.get("env")
                    if not command:
                        continue
                    client = MCPClient(server_name=server_name, command=command, args=args, env=env)
                    await client.register_to_tools(mcp_tools, prefix=f"{server_name}_")
                    webui_manager.bu_mcp_clients.append(client)
        except Exception as e:
            logger.error(f"Failed to initialize MCP tools: {e}", exc_info=True)
            gr.Warning(f"Failed to initialize MCP tools: {e}")

    should_close_browser_on_finish = not keep_browser_open

    try:
        if not keep_browser_open and webui_manager.bu_browser_session:
            logger.info("Closing previous browser session.")
            await webui_manager.bu_browser_session.kill()
            webui_manager.bu_browser_session = None

        if not webui_manager.bu_browser_session:
            logger.info("Launching new browser session.")
            browser_binary_path = browser_binary_path or os.getenv("BROWSER_PATH") or None
            browser_user_data = browser_user_data_dir or os.getenv("BROWSER_USER_DATA") or None
            if not use_own_browser:
                browser_binary_path = None
                browser_user_data = None

            cdp_endpoint = wss_url or cdp_url or None

            webui_manager.bu_browser_session = BrowserSession(
                headless=headless,
                disable_security=disable_security,
                accept_downloads=accept_downloads,
                executable_path=browser_binary_path,
                user_data_dir=browser_user_data,
                cdp_url=cdp_endpoint,
                window_size={"width": window_w, "height": window_h},
                downloads_path=save_download_path,
                traces_dir=save_trace_path if save_trace_path else None,
                record_video_dir=save_recording_path if save_recording_path else None,
                keep_alive=keep_browser_open,
            )

        webui_manager.bu_agent_task_id = str(uuid.uuid4())
        os.makedirs(
            os.path.join(save_agent_history_path, webui_manager.bu_agent_task_id),
            exist_ok=True,
        )
        history_file = os.path.join(
            save_agent_history_path,
            webui_manager.bu_agent_task_id,
            f"{webui_manager.bu_agent_task_id}.json",
        )
        gif_path = os.path.join(
            save_agent_history_path,
            webui_manager.bu_agent_task_id,
            f"{webui_manager.bu_agent_task_id}.gif",
        )

        async def step_callback_wrapper(
                state: BrowserStateSummary, output: AgentOutput, step_num: int
        ):
            await _handle_new_step(webui_manager, state, output, step_num)

        def done_callback_wrapper(history: AgentHistoryList):
            _handle_done(webui_manager, history)

        if not webui_manager.bu_agent:
            logger.info(f"Initializing new agent for task: {task}")
            if not webui_manager.bu_browser_session:
                raise ValueError("Browser session not initialized, cannot create agent.")
            webui_manager.bu_agent = Agent(
                task=task,
                llm=main_llm,
                browser_session=webui_manager.bu_browser_session,
                tools=mcp_tools,
                register_new_step_callback=step_callback_wrapper,
                register_done_callback=done_callback_wrapper,
                use_vision=use_vision,
                override_system_message=override_system_prompt,
                extend_system_message=extend_system_prompt,
                max_actions_per_step=max_actions,
                generate_gif=gif_path,
                source="webui",
            )
            if getattr(webui_manager.bu_agent, "state", None) is not None:
                if hasattr(webui_manager.bu_agent.state, "agent_id"):
                    webui_manager.bu_agent.state.agent_id = webui_manager.bu_agent_task_id
        else:
            webui_manager.bu_agent.add_new_task(task)
            if getattr(webui_manager.bu_agent, "state", None) is not None:
                if hasattr(webui_manager.bu_agent.state, "agent_id"):
                    webui_manager.bu_agent.state.agent_id = webui_manager.bu_agent_task_id
            if hasattr(webui_manager.bu_agent, "settings"):
                webui_manager.bu_agent.settings.generate_gif = gif_path
            webui_manager.bu_agent.browser_session = webui_manager.bu_browser_session
            if mcp_tools:
                webui_manager.bu_agent.tools = mcp_tools

        agent_run_coro = webui_manager.bu_agent.run(max_steps=max_steps)
        agent_task = asyncio.create_task(agent_run_coro)
        webui_manager.bu_current_task = agent_task

        last_chat_len = len(webui_manager.bu_chat_history)
        while not agent_task.done():
            is_paused = webui_manager.bu_agent.state.paused
            is_stopped = webui_manager.bu_agent.state.stopped

            if is_paused:
                yield {
                    pause_resume_button_comp: gr.update(
                        value="▶️ Resume", interactive=True
                    ),
                    stop_button_comp: gr.update(interactive=True),
                }
                while is_paused and not agent_task.done():
                    is_paused = webui_manager.bu_agent.state.paused
                    is_stopped = webui_manager.bu_agent.state.stopped
                    if is_stopped:
                        break
                    await asyncio.sleep(0.2)

                if agent_task.done() or is_stopped:
                    break

                yield {
                    pause_resume_button_comp: gr.update(
                        value="⏸️ Pause", interactive=True
                    ),
                    run_button_comp: gr.update(
                        value="⏳ Running...", interactive=False
                    ),
                }

            if is_stopped:
                logger.info("Agent has stopped (internally or via stop button).")
                if not agent_task.done():
                    try:
                        await asyncio.wait_for(
                            agent_task, timeout=1.0
                        )
                    except asyncio.TimeoutError:
                        logger.warning(
                            "Agent task did not finish quickly after stop signal, cancelling."
                        )
                        agent_task.cancel()
                    except Exception:
                        pass
                break

            update_dict = {}

            if len(webui_manager.bu_chat_history) > last_chat_len:
                update_dict[chatbot_comp] = gr.update(
                    value=_as_chatbot_messages(webui_manager.bu_chat_history)
                )
                last_chat_len = len(webui_manager.bu_chat_history)

            if headless and webui_manager.bu_browser_session:
                try:
                    screenshot_bytes = await webui_manager.bu_browser_session.take_screenshot()
                    if screenshot_bytes:
                        import base64

                        screenshot_b64 = base64.b64encode(screenshot_bytes).decode("utf-8")
                        html_content = f'<img src="data:image/png;base64,{screenshot_b64}" style="width:{stream_vw}vw; height:{stream_vh}vh ; border:1px solid #ccc;">'
                        update_dict[browser_view_comp] = gr.update(
                            value=html_content, visible=True
                        )
                    else:
                        html_content = f"<h1 style='width:{stream_vw}vw; height:{stream_vh}vh'>Waiting for browser session...</h1>"
                        update_dict[browser_view_comp] = gr.update(
                            value=html_content, visible=True
                        )
                except Exception as e:
                    logger.debug(f"Failed to capture screenshot: {e}")
                    update_dict[browser_view_comp] = gr.update(
                        value="<div style='...'>Error loading view...</div>",
                        visible=True,
                    )
            else:
                update_dict[browser_view_comp] = gr.update(visible=False)

            if update_dict:
                yield update_dict

            await asyncio.sleep(0.1)

        webui_manager.bu_agent.state.paused = False
        webui_manager.bu_agent.state.stopped = False
        final_update = {}
        try:
            logger.info("Agent task completing...")
            if not agent_task.done():
                await agent_task
            elif agent_task.exception():
                agent_task.result()
            logger.info("Agent task completed processing.")

            logger.info(f"Explicitly saving agent history to: {history_file}")
            webui_manager.bu_agent.save_history(history_file)

            if os.path.exists(history_file):
                final_update[history_file_comp] = gr.File(value=history_file)

            if gif_path and os.path.exists(gif_path):
                logger.info(f"GIF found at: {gif_path}")
                final_update[gif_comp] = gr.Image(value=gif_path)

        except asyncio.CancelledError:
            logger.info("Agent task was cancelled.")
            if not any(
                    "Cancelled" in msg.get("content", "")
                    for msg in webui_manager.bu_chat_history
                    if msg.get("role") == "assistant"
            ):
                webui_manager.bu_chat_history.append(
                    {"role": "assistant", "content": "**Task Cancelled**."}
                )
            final_update[chatbot_comp] = gr.update(value=_as_chatbot_messages(webui_manager.bu_chat_history))
        except Exception as e:
            logger.error(f"Error during agent execution: {e}", exc_info=True)
            error_message = (
                f"**Agent Execution Error:**\n```\n{type(e).__name__}: {e}\n```"
            )
            if not any(
                    error_message in msg.get("content", "")
                    for msg in webui_manager.bu_chat_history
                    if msg.get("role") == "assistant"
            ):
                webui_manager.bu_chat_history.append(
                    {"role": "assistant", "content": error_message}
                )
            final_update[chatbot_comp] = gr.update(value=webui_manager.bu_chat_history)
            gr.Error(f"Agent execution failed: {e}")

        finally:
            webui_manager.bu_current_task = None

            if webui_manager.bu_mcp_clients:
                for client in webui_manager.bu_mcp_clients:
                    try:
                        await client.disconnect()
                    except Exception:
                        pass
                webui_manager.bu_mcp_clients = []

            if should_close_browser_on_finish:
                if webui_manager.bu_browser_session:
                    logger.info("Closing browser session after task.")
                    await webui_manager.bu_browser_session.kill()
                    webui_manager.bu_browser_session = None

            final_update.update(
                {
                    user_input_comp: gr.update(
                        value="",
                        interactive=True,
                        placeholder="Enter your next task...",
                    ),
                    run_button_comp: gr.update(value="▶️ Submit Task", interactive=True),
                    stop_button_comp: gr.update(value="⏹️ Stop", interactive=False),
                    pause_resume_button_comp: gr.update(
                        value="⏸️ Pause", interactive=False
                    ),
                    clear_button_comp: gr.update(interactive=True),
                    chatbot_comp: gr.update(value=_as_chatbot_messages(webui_manager.bu_chat_history)),
                }
            )
            yield final_update

    except Exception as e:
        logger.error(f"Error setting up agent task: {e}", exc_info=True)
        webui_manager.bu_current_task = None
        yield {
            user_input_comp: gr.update(
                interactive=True, placeholder="Error during setup. Enter task..."
            ),
            run_button_comp: gr.update(value="▶️ Submit Task", interactive=True),
            stop_button_comp: gr.update(value="⏹️ Stop", interactive=False),
            pause_resume_button_comp: gr.update(value="⏸️ Pause", interactive=False),
            clear_button_comp: gr.update(interactive=True),
            chatbot_comp: gr.update(
                value=_as_chatbot_messages(
                    webui_manager.bu_chat_history
                    + [{"role": "assistant", "content": f"**Setup Error:** {e}"}]
                )
            ),
        }


async def handle_submit(
        webui_manager: WebuiManager, components: Dict[gr.components.Component, Any]
):
    """Handles clicks on the main 'Submit' button."""
    user_input_comp = webui_manager.get_component_by_id("browser_use_agent.user_input")
    user_input_value = components.get(user_input_comp, "").strip()

    if webui_manager.bu_current_task and not webui_manager.bu_current_task.done():
        logger.warning(
            "Submit button clicked while agent is already running and not asking for help."
        )
        gr.Info("Agent is currently running. Please wait or use Stop/Pause.")
        yield {}
    else:
        logger.info("Submit button clicked for new task.")
        async for update in run_agent_task(webui_manager, components):
            yield update


async def handle_stop(webui_manager: WebuiManager):
    """Handles clicks on the 'Stop' button."""
    logger.info("Stop button clicked.")
    agent = webui_manager.bu_agent
    task = webui_manager.bu_current_task

    if agent and task and not task.done():
        agent.stop()
        return {
            webui_manager.get_component_by_id(
                "browser_use_agent.stop_button"
            ): gr.update(interactive=False, value="⏹️ Stopping..."),
            webui_manager.get_component_by_id(
                "browser_use_agent.pause_resume_button"
            ): gr.update(interactive=False),
            webui_manager.get_component_by_id(
                "browser_use_agent.run_button"
            ): gr.update(interactive=False),
        }
    logger.warning("Stop clicked but agent is not running or task is already done.")
    return {
        webui_manager.get_component_by_id(
            "browser_use_agent.run_button"
        ): gr.update(interactive=True),
        webui_manager.get_component_by_id(
            "browser_use_agent.stop_button"
        ): gr.update(interactive=False),
        webui_manager.get_component_by_id(
            "browser_use_agent.pause_resume_button"
        ): gr.update(interactive=False),
        webui_manager.get_component_by_id(
            "browser_use_agent.clear_button"
        ): gr.update(interactive=True),
    }


async def handle_pause_resume(webui_manager: WebuiManager):
    """Handles clicks on the 'Pause/Resume' button."""
    agent = webui_manager.bu_agent
    task = webui_manager.bu_current_task

    if agent and task and not task.done():
        if agent.state.paused:
            logger.info("Resume button clicked.")
            agent.resume()
            return {
                webui_manager.get_component_by_id(
                    "browser_use_agent.pause_resume_button"
                ): gr.update(value="⏸️ Pause", interactive=True)
            }
        logger.info("Pause button clicked.")
        agent.pause()
        return {
            webui_manager.get_component_by_id(
                "browser_use_agent.pause_resume_button"
            ): gr.update(value="▶️ Resume", interactive=True)
        }
    logger.warning(
        "Pause/Resume clicked but agent is not running or doesn't support state."
    )
    return {}


async def handle_clear(webui_manager: WebuiManager):
    """Handles clicks on the 'Clear' button."""
    logger.info("Clear button clicked.")

    task = webui_manager.bu_current_task
    if task and not task.done():
        logger.info("Clearing requires stopping the current task.")
        webui_manager.bu_agent.stop()
        task.cancel()
        try:
            await asyncio.wait_for(task, timeout=2.0)
        except (asyncio.CancelledError, asyncio.TimeoutError):
            pass
        except Exception as e:
            logger.warning(f"Error stopping task on clear: {e}")
    webui_manager.bu_current_task = None

    webui_manager.bu_agent = None
    if webui_manager.bu_mcp_clients:
        for client in webui_manager.bu_mcp_clients:
            try:
                await client.disconnect()
            except Exception:
                pass
        webui_manager.bu_mcp_clients = []

    webui_manager.bu_chat_history = []
    webui_manager.bu_agent_task_id = None
    webui_manager.bu_last_task = None

    if webui_manager.bu_browser_session:
        await webui_manager.bu_browser_session.kill()
        webui_manager.bu_browser_session = None

    logger.info("Agent state and browser resources cleared.")

    return {
        webui_manager.get_component_by_id("browser_use_agent.chatbot"): gr.update(
            value=[]
        ),
        webui_manager.get_component_by_id("browser_use_agent.user_input"): gr.update(
            value="", placeholder="Enter your task here..."
        ),
        webui_manager.get_component_by_id(
            "browser_use_agent.agent_history_file"
        ): gr.update(value=None),
        webui_manager.get_component_by_id("browser_use_agent.recording_gif"): gr.update(
            value=None
        ),
        webui_manager.get_component_by_id("browser_use_agent.browser_view"): gr.update(
            value="<div style='...'>Browser Cleared</div>"
        ),
        webui_manager.get_component_by_id("browser_use_agent.run_button"): gr.update(
            value="▶️ Submit Task", interactive=True
        ),
        webui_manager.get_component_by_id("browser_use_agent.stop_button"): gr.update(
            interactive=False
        ),
        webui_manager.get_component_by_id(
            "browser_use_agent.pause_resume_button"
        ): gr.update(value="⏸️ Pause", interactive=False),
        webui_manager.get_component_by_id("browser_use_agent.clear_button"): gr.update(
            interactive=True
        ),
        webui_manager.get_component_by_id("browser_use_agent.flow_script_status"): gr.update(
            value="Generate a Python script from your task."
        ),
        webui_manager.get_component_by_id("browser_use_agent.flow_script_file"): gr.update(
            value=None
        ),
        webui_manager.get_component_by_id("browser_use_agent.flow_script_preview"): gr.update(
            value=""
        ),
    }


async def handle_export_script(
        webui_manager: WebuiManager, components: Dict[gr.components.Component, Any]
):
    """Generate a flow script using CodeAgent."""
    user_input_comp = webui_manager.get_component_by_id("browser_use_agent.user_input")
    task = components.get(user_input_comp, "").strip() or webui_manager.bu_last_task
    if not task:
        gr.Warning("Please enter a task or run the agent first.")
        return {}

    def get_setting(key, default=None):
        comp = webui_manager.id_to_component.get(f"agent_settings.{key}")
        return components.get(comp, default) if comp else default

    def get_browser_setting(key, default=None):
        comp = webui_manager.id_to_component.get(f"browser_settings.{key}")
        return components.get(comp, default) if comp else default

    flow_script_output_dir = get_setting("flow_script_output_dir", "./tmp/flows")
    use_vision = get_setting("use_vision", True)
    max_steps = get_setting("max_steps", 100)

    browser_binary_path = get_browser_setting("browser_binary_path") or None
    browser_user_data_dir = get_browser_setting("browser_user_data_dir") or None
    use_own_browser = get_browser_setting("use_own_browser", False)
    headless = get_browser_setting("headless", False)
    disable_security = get_browser_setting("disable_security", False)
    window_w = int(get_browser_setting("window_w", 1280))
    window_h = int(get_browser_setting("window_h", 1100))
    cdp_url = get_browser_setting("cdp_url") or None
    wss_url = get_browser_setting("wss_url") or None
    save_download_path = get_browser_setting("save_download_path", "./tmp/downloads")

    if not use_own_browser:
        browser_binary_path = None
        browser_user_data_dir = None

    browser_kwargs = {
        "headless": headless,
        "disable_security": disable_security,
        "executable_path": browser_binary_path or os.getenv("BROWSER_PATH") or None,
        "user_data_dir": browser_user_data_dir or os.getenv("BROWSER_USER_DATA") or None,
        "cdp_url": wss_url or cdp_url or None,
        "window_size": {"width": window_w, "height": window_h},
        "downloads_path": save_download_path,
    }

    status_comp = webui_manager.get_component_by_id("browser_use_agent.flow_script_status")
    file_comp = webui_manager.get_component_by_id("browser_use_agent.flow_script_file")
    preview_comp = webui_manager.get_component_by_id("browser_use_agent.flow_script_preview")

    try:
        run_id, script_path, script_text = await create_flow_script(
            task=task,
            output_dir=flow_script_output_dir,
            browser_kwargs=browser_kwargs,
            use_vision=use_vision,
            max_steps=max_steps,
        )
        return {
            status_comp: gr.update(value=f"✅ Script generated: {script_path} (run {run_id})"),
            file_comp: gr.update(value=script_path),
            preview_comp: gr.update(value=script_text),
        }
    except Exception as e:
        logger.error(f"Failed to generate script: {e}", exc_info=True)
        return {
            status_comp: gr.update(value=f"❌ Script generation failed: {e}"),
            file_comp: gr.update(value=None),
        }


def create_browser_use_agent_tab(webui_manager: WebuiManager):
    """
    Create the run agent tab, defining UI, state, and handlers.
    """
    webui_manager.init_browser_use_agent()

    tab_components = {}
    with gr.Column():
        chatbot = gr.Chatbot(
            lambda: _as_chatbot_messages(webui_manager.bu_chat_history),
            elem_id="browser_use_chatbot",
            label="Agent Interaction",
            height=600,
        )
        user_input = gr.Textbox(
            label="Your Task or Response",
            placeholder="Enter your task here or provide assistance when asked.",
            lines=3,
            interactive=True,
            elem_id="user_input",
        )
        with gr.Row():
            stop_button = gr.Button(
                "⏹️ Stop", interactive=False, variant="stop", scale=2
            )
            pause_resume_button = gr.Button(
                "⏸️ Pause", interactive=False, variant="secondary", scale=2, visible=True
            )
            clear_button = gr.Button(
                "🗑️ Clear", interactive=True, variant="secondary", scale=2
            )
            run_button = gr.Button("▶️ Submit Task", variant="primary", scale=3)

        browser_view = gr.HTML(
            value="<div style='width:100%; height:50vh; display:flex; justify-content:center; align-items:center; border:1px solid #ccc; background-color:#f0f0f0;'><p>Browser View (Requires Headless=True)</p></div>",
            label="Browser Live View",
            elem_id="browser_view",
            visible=False,
        )
        with gr.Column():
            gr.Markdown("### Task Outputs")
            agent_history_file = gr.File(label="Agent History JSON", interactive=False)
            recording_gif = gr.Image(
                label="Task Recording GIF",
                format="gif",
                interactive=False,
                type="filepath",
            )
            gr.Markdown("### Flow Script (CodeAgent)")
            flow_script_status = gr.Markdown(value="Generate a Python script from your task.")
            flow_script_file = gr.File(label="Flow Script File", interactive=False)
            flow_script_preview = gr.Code(label="Flow Script Preview", language="python")
            export_script_button = gr.Button("🧩 Generate Script", variant="secondary")

    tab_components.update(
        dict(
            chatbot=chatbot,
            user_input=user_input,
            clear_button=clear_button,
            run_button=run_button,
            stop_button=stop_button,
            pause_resume_button=pause_resume_button,
            agent_history_file=agent_history_file,
            recording_gif=recording_gif,
            browser_view=browser_view,
            flow_script_status=flow_script_status,
            flow_script_file=flow_script_file,
            flow_script_preview=flow_script_preview,
            export_script_button=export_script_button,
        )
    )
    webui_manager.add_components(
        "browser_use_agent", tab_components
    )

    all_managed_components = set(
        webui_manager.get_components()
    )
    run_tab_outputs = list(tab_components.values())

    async def submit_wrapper(
            components_dict: Dict[Component, Any],
    ) -> AsyncGenerator[Dict[Component, Any], None]:
        async for update in handle_submit(webui_manager, components_dict):
            yield update

    async def stop_wrapper() -> AsyncGenerator[Dict[Component, Any], None]:
        update_dict = await handle_stop(webui_manager)
        yield update_dict

    async def pause_resume_wrapper() -> AsyncGenerator[Dict[Component, Any], None]:
        update_dict = await handle_pause_resume(webui_manager)
        yield update_dict

    async def clear_wrapper() -> AsyncGenerator[Dict[Component, Any], None]:
        update_dict = await handle_clear(webui_manager)
        yield update_dict

    async def export_wrapper(
            components_dict: Dict[Component, Any],
    ) -> AsyncGenerator[Dict[Component, Any], None]:
        update_dict = await handle_export_script(webui_manager, components_dict)
        yield update_dict

    run_button.click(
        fn=submit_wrapper, inputs=all_managed_components, outputs=run_tab_outputs, trigger_mode="multiple"
    )
    user_input.submit(
        fn=submit_wrapper, inputs=all_managed_components, outputs=run_tab_outputs
    )
    stop_button.click(fn=stop_wrapper, inputs=None, outputs=run_tab_outputs)
    pause_resume_button.click(
        fn=pause_resume_wrapper, inputs=None, outputs=run_tab_outputs
    )
    clear_button.click(fn=clear_wrapper, inputs=None, outputs=run_tab_outputs)
    export_script_button.click(
        fn=export_wrapper,
        inputs=all_managed_components,
        outputs=run_tab_outputs,
    )
