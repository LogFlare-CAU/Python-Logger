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
logger.set_broadcastlevel(logging.ERROR)
logger.broadcasturl = "http://127.0.0.1:8080"
logger.broadcast = True  # if not, it will not push new errors
```
