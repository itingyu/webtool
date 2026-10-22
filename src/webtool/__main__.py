"""`python -m webtool` 入口: 与 console script 走同一条快速路径"""
import sys

from webtool.cli.fastpath import main

if __name__ == "__main__":
    sys.exit(main())
