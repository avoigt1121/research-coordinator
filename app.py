"""HuggingFace Spaces entry point."""
from gradio_ui import CoordinatorUI

ui = CoordinatorUI()
ui.build().launch(server_name="0.0.0.0", server_port=7860)
