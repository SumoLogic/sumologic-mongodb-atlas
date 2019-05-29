import sys
import logging
import logging.handlers as handlers


EXCLUDED_MODULE_LOGGING = ("requests", "urllib3")
LOG_FORMAT = "%(levelname)s | %(asctime)s | %(threadName)s | %(name)s | %(message)s"
LOG_FILEPATH = "/tmp/sumoapiclient.log"
ROTATION_TYPE = "D"  # use H for hourly W6 for weekly(ie Sunday)
ROTATION_INTERVAL = 10  # in hours
ENABLE_CONSOLE_LOG = True
ENABLE_LOGFILE = True


def get_logger(name, LOG_FORMAT=LOG_FORMAT, LOG_FILEPATH=LOG_FILEPATH, ROTATION_TYPE=ROTATION_TYPE,
               ROTATION_INTERVAL=ROTATION_INTERVAL, ENABLE_LOGFILE=ENABLE_LOGFILE,
               ENABLE_CONSOLE_LOG=ENABLE_CONSOLE_LOG, force_create=False):
    name = name or __name__
    log = logging.getLogger(name)
    if (not log.handlers) or force_create:
        if force_create:
            # removing existing handlers
            for hdlr in log.handlers:
                log.removeHandler(hdlr)

        log.setLevel(logging.DEBUG)
        logFormatter = logging.Formatter(LOG_FORMAT)

        if ENABLE_CONSOLE_LOG:
            consoleHandler = logging.StreamHandler(sys.stdout)
            consoleHandler.setFormatter(logFormatter)
            log.addHandler(consoleHandler)
        if ENABLE_LOGFILE:
            filehandler = handlers.TimedRotatingFileHandler(
                LOG_FILEPATH, backupCount=5,
                when=ROTATION_TYPE, interval=ROTATION_INTERVAL,
                # encoding='bz2',  # uncomment for bz2 compression
            )
            # filehandler = logging.FileHandler()
            filehandler.setFormatter(logFormatter)
            log.addHandler(filehandler)

        #disabling logging for requests/urllib3
        for module_name in EXCLUDED_MODULE_LOGGING:
            logging.getLogger(module_name).setLevel(logging.WARNING)
    return log
