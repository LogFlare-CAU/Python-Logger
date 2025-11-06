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
