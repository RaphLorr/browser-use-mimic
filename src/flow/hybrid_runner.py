import json
import os
import subprocess
import sys
import tempfile
from typing import Optional

from browser_use import Agent
from browser_use.browser.session import BrowserSession

from src.utils import llm_provider


async def run_hybrid_flow(
    script_path: str,
    task: str,
    llm_provider_name: str,
    llm_model_name: str,
    llm_temperature: float,
    llm_base_url: Optional[str],
    llm_api_key: Optional[str],
    use_vision: bool,
    max_steps: int,
    max_actions: int,
    browser_kwargs: dict,
    script_env_json: Optional[str] = None,
    cdp_url: Optional[str] = None,
) -> None:
    """
    Run a hard-coded Playwright script first, then an LLM-driven agent task.
    """
    if not os.path.exists(script_path):
        raise FileNotFoundError(f"Script not found: {script_path}")

    env = os.environ.copy()
    if script_env_json:
        env.update(json.loads(script_env_json))
    if cdp_url:
        env["PLAYWRIGHT_CDP_URL"] = cdp_url

    script_to_run = script_path
    if cdp_url:
        script_to_run = _patch_script_for_cdp(script_path)

    subprocess.run(
        [sys.executable, script_to_run],
        env=env,
        check=True,
    )

    llm = llm_provider.get_llm_model(
        provider=llm_provider_name,
        model_name=llm_model_name,
        temperature=llm_temperature,
        base_url=llm_base_url,
        api_key=llm_api_key,
    )

    browser_session = BrowserSession(**browser_kwargs)
    agent = Agent(
        task=task,
        llm=llm,
        browser_session=browser_session,
        use_vision=use_vision,
        max_actions_per_step=max_actions,
        source="hybrid",
    )

    try:
        await agent.run(max_steps=max_steps)
    finally:
        try:
            await browser_session.kill()
        except Exception:
            pass


def _patch_script_for_cdp(script_path: str) -> str:
    with open(script_path, "r", encoding="utf-8") as f:
        content = f.read()

    if "PLAYWRIGHT_CDP_URL" not in content:
        if "import os" not in content:
            content = "import os\n" + content

        content = _replace_launch_block(
            content,
            "await p.chromium.launch(",
            "await p.chromium.connect_over_cdp(cdp_url)",
        )
        content = _replace_launch_block(
            content,
            "p.chromium.launch(",
            "p.chromium.connect_over_cdp(cdp_url)",
        )

    fd, temp_path = tempfile.mkstemp(prefix="playwright_cdp_", suffix=".py")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(content)
    return temp_path


def _replace_launch_block(content: str, launch_token: str, cdp_call: str) -> str:
    if launch_token not in content:
        return content

    replacement = (
        "cdp_url = os.environ.get(\"PLAYWRIGHT_CDP_URL\")\n"
        f"    if cdp_url:\n"
        f"        browser = {cdp_call}\n"
        f"    else:\n"
        f"        browser = {launch_token}"
    )

    return content.replace(f"browser = {launch_token}", replacement)
