import argparse
import os

import gradio as gr
import uvicorn
from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from src.api import api_router
from src.utils.bubus_patch import apply_eventbus_memory_warning_threshold
from src.webui.interface import theme_map, create_ui

load_dotenv()
apply_eventbus_memory_warning_threshold(default_mb=500)


def _create_app(theme_name: str) -> FastAPI:
    app = FastAPI(title="Browser Use WebUI")
    app.include_router(api_router, prefix="/api")
    app.mount("/workflow", StaticFiles(directory="public/workflow", html=True), name="workflow")

    demo = create_ui(theme_name=theme_name)
    app = gr.mount_gradio_app(app, demo, path="/")
    return app


app = _create_app(theme_name=os.getenv("WEBUI_THEME", "Ocean"))


def main():
    parser = argparse.ArgumentParser(description="Gradio WebUI for Browser Agent", allow_abbrev=False)
    parser.add_argument("--ip", type=str, default="127.0.0.1", help="IP address to bind to")
    parser.add_argument("--port", type=int, default=7788, help="Port to listen on")
    parser.add_argument("--theme", type=str, default="Ocean", choices=theme_map.keys(), help="Theme to use for the UI")
    args = parser.parse_args()

    runtime_app = _create_app(theme_name=args.theme)
    uvicorn.run(runtime_app, host=args.ip, port=args.port, reload=False)


if __name__ == "__main__":
    main()
