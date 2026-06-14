"""Entry point: python -m desktop_tools
   python -m desktop_tools annotator  # 启动标注台
"""

import sys

if len(sys.argv) > 1 and sys.argv[1] == "annotator":
    from .annotator import main
else:
    from .mcp_server import main

if __name__ == "__main__":
    main()
