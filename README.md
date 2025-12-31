Override of python logging library for logflare

## Setting up

1. set logger class with logflare
```python
logging.setLoggerClass(LogFlare)
logger = logging.getLogger("LogFlare")
logger.setLevel(logging.INFO)
```


2. change broadcasting level and url
> We Highly recomend setting the level above the `WARNING`, as low level broadcasting will result in large consumption of resources.
```python
logger.set_broadcastlevel(logging.WARNING)
logger.broadcasturl = os.getenv("LOGFLARE_URL", "")
logger.project_name = os.getenv("DISCORD_LOGFLARE_NAME", "")
logger.project_key = os.getenv("DISCORD_LOGFLARE_KEY", "")
logger.broadcast = True  # if not it will not broadcast
```


## Setup Function
> This is a simple function you can call at start of your code to simply initialize the logger
```python
def set_logger(name="LogFlare"):
    logging.setLoggerClass(LogFlare)
    logger = logging.getLogger(name)
    logger.setLevel(logging.INFO)
    # FORMAT, DO NOT CHANGE
    formatter = logging.Formatter(
        "%(asctime)s | %(levelname)s | %(message)s", "%Y-%m-%d %H:%M:%S"
    )

    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)

    file_debug_handler = logging.FileHandler(var.debugfile, encoding="utf-8", mode="w")
    file_debug_handler.setLevel(logging.DEBUG)
    file_debug_handler.setFormatter(formatter)
    logger.addHandler(file_debug_handler)

    file_error_handler = logging.FileHandler(var.errorfile, encoding="utf-8", mode="a")
    file_error_handler.setLevel(logging.ERROR)
    file_error_handler.setFormatter(formatter)
    logger.addHandler(file_error_handler)

    logger.set_broadcastlevel(logging.WARNING)
    logger.broadcasturl = os.getenv("LOGFLARE_URL", "")
    logger.project_name = os.getenv("DISCORD_LOGFLARE_NAME", "")
    logger.project_key = os.getenv("DISCORD_LOGFLARE_KEY", "")
    logger.test_connection()

    logger.broadcast = broadcast_initial
    if broadcast_delay > 0:
        logger.enable_broadcast_after(broadcast_delay)

    return logger
  ```

**It is CRITICAL to user this format**
```python
    formatter = logging.Formatter(
        "%(asctime)s | %(levelname)s | %(message)s", "%Y-%m-%d %H:%M:%S"
    )
```
for your logger, or else it won't be parsed correctly

