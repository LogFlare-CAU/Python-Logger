Override of python logging library for logflare

## Setting up

1. set logger class with logflare
```python
logging.setLoggerClass(LogFlare)
logger = logging.getLogger("LogFlare")
```


2. change broadcasting level and url
> We Highly recomend setting the level above the `WARNING`, as low level broadcasting will result in large consumption of resources.
```python
logger.broadcastlevel = "WARNING"
logger.broadcasturl = "http://url_to_my_logflare_backend:port"
```
