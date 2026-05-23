"""HuggingFace Spaces entry point."""
from gradio_ui import CoordinatorUI

ui = CoordinatorUI()
ui.build().launch()
