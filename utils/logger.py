import logging
import sys

# Create logger object
logger = logging.getLogger("ServerMonitor")
logger.setLevel(logging.INFO)  # Get all logs at level INFO and higher

# Set format output: [data time] | level | Message
formatter = logging.Formatter(
    fmt="%(asctime)s | %(levelname)-8s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)

# 1. Handler for output in console instead print function
console_handler = logging.StreamHandler(sys.stdout)
console_handler.setFormatter(formatter)
logger.addHandler(console_handler)

# 2. Handler for logfile writer in root project folder
# encoding="utf-8" required, because i have cyrillic symbols in log
file_handler = logging.FileHandler("telebot.log", mode="a", encoding="utf-8")
file_handler.setFormatter(formatter)
logger.addHandler(file_handler)
