"""`python -m webtool` 入口: 走包内那一份 app, 避免 __main__ 双导入"""
import sys

from webtool.cli.app import main

if __name__ == "__main__":
    sys.exit(main())
